"""Campaign monitoring service.

Polls for new campaigns, detects drops, and triggers locks.
"""
from typing import Set, Optional
from datetime import datetime
import structlog
from app.config import settings
from app.models import Campaign, CampaignFilter
from app.services.arcadia_client import ArcadiaClient
from app.strategies.strategy_router import StrategyRouter
from app.core.notifier import Notifier
from app.core.session_manager import SessionManager
from app.core.circuit_breaker import CircuitBreaker

logger = structlog.get_logger()


class CampaignMonitor:
    """Monitors Arcadia for campaign drops and available slots."""

    def __init__(
        self,
        client: Optional[ArcadiaClient] = None,
        notifier: Optional[Notifier] = None,
    ):
        self.session = SessionManager()
        self.circuit_breaker = CircuitBreaker()
        self.notifier = notifier or Notifier()

        if client:
            self.client = client
        else:
            router = StrategyRouter(self.session, self.notifier, self.circuit_breaker)
            self.client = ArcadiaClient(router)

        self._known_campaigns: Set[str] = set()
        self._last_check: Optional[datetime] = None
        self._last_campaign_states: dict[str, dict] = {}
        self.logger = logger.bind(component="campaign_monitor")

    async def check_and_lock(self) -> int:
        """Main monitoring loop — check campaigns, act, and return next poll interval."""
        self.logger.debug("monitor.check_start")
        next_interval = settings.poll_interval_seconds

        try:
            # Fetch raw campaign list via router directly to get all states
            raw_campaigns = await self.client.router.list_campaigns()

            any_full = False
            recently_filled = False
            new_campaigns = []

            for c in raw_campaigns:
                if c.id not in self._known_campaigns:
                    new_campaigns.append(c)

                # Determine if campaign is full
                is_full = False
                slots = c.slotsRemaining if c.slotsRemaining is not None else float('inf')
                if slots <= 0:
                    is_full = True

                # Check reservation constraints
                if c.reservation:
                    eligible = c.reservation.get("reservedEligibleForMe", False)
                    if not eligible:
                        gen_capacity = c.reservation.get("generalCapacity", 0)
                        gen_locked = c.reservation.get("generalLocked", 0)
                        if gen_capacity - gen_locked <= 0:
                            is_full = True
                    else:
                        gen_capacity = c.reservation.get("generalCapacity", 0)
                        gen_locked = c.reservation.get("generalLocked", 0)
                        res_total = c.reservation.get("reservedTotal", 0)
                        res_locked = c.reservation.get("reservedLocked", 0)
                        if (gen_capacity - gen_locked) + (res_total - res_locked) <= 0:
                            is_full = True

                if c.status == "active":
                    if is_full:
                        any_full = True
                        prev_state = self._last_campaign_states.get(c.id)
                        if prev_state and prev_state.get("slots_available", False):
                            recently_filled = True

                    self._last_campaign_states[c.id] = {
                        "slots_available": not is_full,
                        "timestamp": datetime.utcnow()
                    }

            # Notify on new campaign drops
            for campaign in new_campaigns:
                self.logger.info("monitor.new_campaign", campaign=campaign.id, payout=campaign.payout_amount)
                await self.notifier.notify_campaign_dropped(campaign)

            # Update known set
            self._known_campaigns = {c.id for c in raw_campaigns}
            self._last_check = datetime.utcnow()

            # Auto-lock if enabled (pass raw campaigns to reuse connection results concurrently)
            if settings.auto_lock_enabled and raw_campaigns:
                results = await self.client.auto_lock_available(campaigns=raw_campaigns)
                for r in results:
                    if r.success:
                        self.logger.info("monitor.auto_locked", campaign=r.campaign_id)
                    else:
                        self.logger.warning("monitor.auto_lock_failed", campaign=r.campaign_id, reason=r.message)

            # Determine next dynamic interval trigger
            if recently_filled:
                next_interval = 3
                self.logger.info("monitor.interval_aggressive_release", interval=3)
            elif any_full:
                next_interval = 5
                self.logger.debug("monitor.interval_aggressive_full", interval=5)
            else:
                next_interval = settings.poll_interval_seconds

            self.logger.debug("monitor.check_complete", campaigns_found=len(raw_campaigns), new=len(new_campaigns))

        except Exception as e:
            self.logger.error("monitor.check_failed", error=str(e))
            await self.notifier.notify_error("Campaign check failed", {"error": str(e)})

        return next_interval

    async def force_check(self) -> list:
        """Manual check — returns all available campaigns without locking."""
        return await self.client.get_available_campaigns()

    def get_status(self) -> dict:
        """Get monitor status."""
        return {
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "known_campaigns": len(self._known_campaigns),
            "client_stats": self.client.get_stats(),
        }