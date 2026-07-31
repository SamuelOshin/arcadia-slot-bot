"""Campaign monitoring service.

Polls for new campaigns, detects drops, and triggers locks.
"""
import json
import os
import asyncio
from typing import Set, Optional, List
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


class LockCoordinator:
    """Prevents multiple accounts from redundantly targeting the same campaign.

    When a campaign has only 1 slot, sending 3 concurrent lock attempts from
    3 accounts wastes 2 daily quotas. The coordinator ensures only ONE account
    per campaign wins the right to attempt a lock. Others skip gracefully.
    """

    def __init__(self):
        self._claimed: dict[str, str] = {}  # campaign_id → account_label
        self._lock = asyncio.Lock()

    async def try_claim(self, campaign_id: str, account_label: str) -> bool:
        """Return True if this account should proceed with locking.

        The first caller wins. Subsequent callers for the same campaign_id
        return False and should skip without logging an error.
        """
        async with self._lock:
            if campaign_id in self._claimed:
                return False
            self._claimed[campaign_id] = account_label
            return True

    def release(self, campaign_id: str) -> None:
        """Release a campaign claim so it can be re-attempted if the lock fails."""
        self._claimed.pop(campaign_id, None)

    def release_all(self) -> None:
        """Release all claims (call on each new poll cycle)."""
        self._claimed.clear()


class CampaignMonitor:
    """Monitors Arcadia for campaign drops and available slots."""

    def __init__(
        self,
        client: Optional[ArcadiaClient] = None,
        notifier: Optional[Notifier] = None,
        account = None,  # Optional[AccountConfig]
        coordinator: Optional[LockCoordinator] = None,
        account_index: int = 0,
    ):
        self.account = account
        self.account_label: str = account.name if account else "default"
        self.account_index: int = account_index
        self.coordinator = coordinator
        self.session = SessionManager(account=account)
        self.circuit_breaker = CircuitBreaker()
        self.notifier = notifier or Notifier()

        if client:
            self.client = client
        else:
            router = StrategyRouter(self.session, self.notifier, self.circuit_breaker)
            self.client = ArcadiaClient(router, account_index=self.account_index)

        self._known_campaigns: Set[str] = set()
        self._last_check: Optional[datetime] = None
        self._last_campaign_states: dict[str, dict] = {}
        self._is_warmed_up: bool = False   # True after first silent poll
        
        # Per-account known campaigns database
        safe_name = self.account_label.lower().replace(" ", "_")
        self._known_path: str = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
            "data", 
            f"known_campaigns_{safe_name}.json"
        )
        self.logger = logger.bind(component="campaign_monitor", account=self.account_label)
        self._load_known_campaigns()

    def _load_known_campaigns(self) -> None:
        """Load known campaign IDs from disk (survives restarts)."""
        try:
            if os.path.exists(self._known_path):
                with open(self._known_path, "r") as f:
                    data = json.load(f)
                self._known_campaigns = set(data.get("ids", []))
                self.logger.info("monitor.known_loaded", count=len(self._known_campaigns), path=self._known_path)
        except Exception as e:
            self.logger.warning("monitor.known_load_failed", error=str(e))
            self._known_campaigns = set()

    def _save_known_campaigns(self) -> None:
        """Persist known campaign IDs to disk."""
        try:
            os.makedirs(os.path.dirname(self._known_path), exist_ok=True)
            with open(self._known_path, "w") as f:
                json.dump({"ids": list(self._known_campaigns)}, f)
        except Exception as e:
            self.logger.warning("monitor.known_save_failed", error=str(e))

    async def _send_autolock_summary(self, summary: dict) -> None:
        """Send a Telegram summary of the auto-lock cycle."""
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return

        succeeded = summary.get("succeeded", 0)
        total_raw = summary.get("total_raw", 0)
        total_filtered = summary.get("total_filtered", 0)
        attempts = summary.get("attempts", [])

        succeeded_attempts = [a for a in attempts if a.get("success")]
        failed_attempts = [a for a in attempts if not a.get("success")]

        lines = []

        label_suffix = f" [{self.account_label}]" if self.account_label != "default" else ""

        if succeeded > 0:
            lines.append(f"⚡ <b>Auto-Lock Successful!{label_suffix}</b> 🎉")
            lines.append("──────────────────")
            for attempt in succeeded_attempts:
                lines.append(f"🎯 <b>{attempt.get('campaign_title')}</b>")
                lines.append(f"💰 <b>Payout:</b> ${attempt.get('payout')}/{attempt.get('payout_unit')}")
                lines.append(f"⏱️ <b>Speed:</b> {attempt.get('response_time_ms', 0):.0f}ms")
                if attempt.get("slot_number"):
                    lines.append(f"🪑 <b>Slot Claimed:</b> #{attempt.get('slot_number')}")
                lines.append("──────────────────")
            
            if failed_attempts:
                lines.append("⚠️ <b>Lock Misses:</b>")
                for attempt in failed_attempts:
                    msg = attempt.get("message", "unknown error")
                    if msg == "taken" or "conflict" in msg.lower() or "taken" in msg.lower():
                        reason = "taken (collision)"
                    else:
                        reason = msg
                    lines.append(f"• <b>{attempt.get('campaign_title')}</b>: {reason} ({attempt.get('response_time_ms', 0):.0f}ms)")
                lines.append("──────────────────")
        else:
            # Succeeded == 0, meaning all attempts failed
            lines.append(f"⚠️ <b>Auto-Lock Missed{label_suffix}</b>")
            lines.append("──────────────────")
            for attempt in failed_attempts:
                lines.append(f"🎯 <b>{attempt.get('campaign_title')}</b>")
                lines.append(f"💰 <b>Payout:</b> ${attempt.get('payout')}/{attempt.get('payout_unit')}")
                lines.append(f"⏱️ <b>Speed:</b> {attempt.get('response_time_ms', 0):.0f}ms")
                
                msg = attempt.get("message", "unknown error")
                if msg == "taken" or "conflict" in msg.lower() or "taken" in msg.lower():
                    reason = "taken (collision)"
                else:
                    reason = msg
                lines.append(f"❌ <b>Reason:</b> {reason}")
                lines.append("──────────────────")

        # Cycle statistics footer
        lines.append("📈 <b>Cycle Stats:</b>")
        lines.append(f"• Checked: {total_raw} campaigns ({total_filtered} filtered)")
        
        # Build filter details for context
        rejections = summary.get("filter_rejections", {})
        filter_parts = []
        for reason, count in sorted(rejections.items(), key=lambda x: -x[1]):
            filter_parts.append(f"{count} {reason}")
        filter_str = ", ".join(filter_parts[:3])
        if len(filter_parts) > 3:
            filter_str += f" +{len(filter_parts)-3} more"
        if filter_str:
            lines.append(f"  └ {filter_str}")

        message = "\n".join(lines)
        await self.notifier._send_telegram(
            chat_id=settings.telegram_chat_id.split(",")[0].strip(),
            message=message,
        )
        self.logger.info("monitor.autolock_summary_sent", summary=summary)

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

            # --- Warm-up: first poll after (re)start silently seeds known campaigns ---
            # This prevents a deploy/restart from firing notifications for every
            # campaign that was already running before the restart.
            if not self._is_warmed_up:
                self._known_campaigns = {c.id for c in raw_campaigns}
                self._save_known_campaigns()
                self._is_warmed_up = True
                self._last_check = datetime.utcnow()
                self.logger.info(
                    "monitor.warmed_up",
                    seeded=len(self._known_campaigns),
                )
                # Still run the full state tracking below, but skip notifications.
                for c in raw_campaigns:
                    slots = c.slotsRemaining if c.slotsRemaining is not None else float('inf')
                    is_full = slots <= 0
                    if c.status == "active":
                        self._last_campaign_states[c.id] = {
                            "slots_available": not is_full,
                            "timestamp": datetime.utcnow()
                        }
                return next_interval

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

            # Notify on new campaign drops if they are lockable (have slots)
            for campaign in new_campaigns:
                # Always log full details so we can diagnose filter rejections
                reservation = campaign.reservation or {}
                self.logger.info(
                    "monitor.new_campaign_detected",
                    campaign_id=campaign.id,
                    title=campaign.title,
                    payout=campaign.payout_amount,
                    slots_remaining=campaign.slotsRemaining,
                    status=campaign.status,
                    is_lockable=campaign.is_lockable,
                    my_lock=campaign.myLock is not None,
                    my_submission=campaign.mySubmission is not None,
                    reservation_enabled=reservation.get("enabled"),
                    reserved_eligible_for_me=reservation.get("reservedEligibleForMe"),
                    general_capacity=reservation.get("generalCapacity"),
                    general_locked=reservation.get("generalLocked"),
                    auto_lock_enabled=settings.auto_lock_enabled,
                    min_payout_filter=settings.campaign_filter_min_payout,
                )
                if campaign.is_lockable:
                    self.logger.info("monitor.new_campaign", campaign=campaign.id, payout=campaign.payout_amount)
                    await self.notifier.notify_campaign_dropped(campaign)
                else:
                    rejection_reason = (
                        "already_locked" if campaign.myLock is not None else
                        "already_submitted" if campaign.mySubmission is not None else
                        "no_slots" if (campaign.slotsRemaining is not None and campaign.slotsRemaining <= 0) else
                        "reservation_full" if (
                            campaign.reservation and
                            not campaign.reservation.get("reservedEligibleForMe", False) and
                            campaign.reservation.get("generalLocked", 0) >= campaign.reservation.get("generalCapacity", 0)
                        ) else
                        "status_not_active" if campaign.status != "active" else
                        "expired" if (
                            campaign.ends_at and
                            campaign.ends_at < __import__('datetime').datetime.now(campaign.ends_at.tzinfo)
                        ) else
                        "unknown"
                    )
                    self.logger.warning(
                        "monitor.new_campaign_not_lockable",
                        campaign_id=campaign.id,
                        title=campaign.title,
                        reason=rejection_reason,
                    )
                    # Only notify if campaign is active and might become available later.
                    # Skip expired, no-slots, locked, submitted — user can't act on these.
                    if rejection_reason not in ("already_locked", "already_submitted", "no_slots", "expired", "status_not_active", "unknown"):
                        await self.notifier.notify_campaign_dropped(campaign)

            # Update known set
            self._known_campaigns = {c.id for c in raw_campaigns}
            self._save_known_campaigns()
            self._last_check = datetime.utcnow()

            # Auto-lock if enabled (pass raw campaigns to reuse connection results concurrently)
            if settings.auto_lock_enabled and raw_campaigns:
                results = await self.client.auto_lock_available(campaigns=raw_campaigns)
                for r in results:
                    if r.success:
                        self.logger.info("monitor.auto_locked", campaign=r.campaign_id, title=r.campaign_title)
                    else:
                        self.logger.warning("monitor.auto_lock_failed", campaign=r.campaign_id, title=r.campaign_title, reason=r.message)

                # Send Telegram summary if any lock was attempted
                summary = self.client.get_last_cycle_summary()
                if summary and summary.get("attempted", 0) > 0:
                    await self._send_autolock_summary(summary)

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