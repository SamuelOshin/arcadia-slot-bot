"""High-level client for Arcadia operations.

Wraps the strategy router with business logic:
- Campaign filtering
- Rate limiting
- Slot quota enforcement
- Analytics tracking
"""
import asyncio
from datetime import datetime, date
from typing import List, Optional
import structlog
from app.config import settings
from app.models import Campaign, SlotLockResult, CampaignFilter
from app.strategies.strategy_router import StrategyRouter

logger = structlog.get_logger()


class ArcadiaClient:
    """High-level client with business rules."""

    def __init__(self, strategy_router: StrategyRouter):
        self.router = strategy_router
        self._slots_locked_today = 0
        self._last_reset = date.today()
        self._locked_campaigns: set = set()
        self.logger = logger.bind(component="arcadia_client")

    def _check_quota(self) -> bool:
        """Check if we've hit the daily slot limit."""
        # Reset counter if day changed
        if date.today() != self._last_reset:
            self._slots_locked_today = 0
            self._last_reset = date.today()
            self._locked_campaigns.clear()

        return self._slots_locked_today < settings.campaign_filter_max_slots_per_day

    def _filter_campaigns(
        self,
        campaigns: List[Campaign],
        filters: Optional[CampaignFilter] = None,
    ) -> List[Campaign]:
        """Apply business filters to campaign list."""
        if filters is None:
            filters = CampaignFilter(
                min_payout=settings.campaign_filter_min_payout,
                auto_lock=settings.auto_lock_enabled,
            )

        filtered = []
        for c in campaigns:
            # Skip already locked
            if c.id in self._locked_campaigns:
                continue

            # Skip if not lockable
            if not c.is_lockable:
                continue

            # Reservation check for Bronze tier
            if c.reservation and c.reservation.get("enabled"):
                eligible = c.reservation.get("reservedEligibleForMe", False)
                if not eligible:
                    # User is Bronze, can only access general slots
                    gen_capacity = c.reservation.get("generalCapacity", 0)
                    gen_locked = c.reservation.get("generalLocked", 0)
                    gen_available = gen_capacity - gen_locked
                    if gen_available <= 0:
                        continue
                else:
                    # User is eligible for reserved slots
                    gen_capacity = c.reservation.get("generalCapacity", 0)
                    gen_locked = c.reservation.get("generalLocked", 0)
                    res_total = c.reservation.get("reservedTotal", 0)
                    res_locked = c.reservation.get("reservedLocked", 0)
                    total_available = (gen_capacity - gen_locked) + (res_total - res_locked)
                    if total_available <= 0:
                        continue

            # Minimum payout filter
            if filters.min_payout and c.payout_amount < filters.min_payout:
                continue

            # Type filter (kinds)
            if filters.kind and c.kind not in filters.kind:
                continue

            # Backward compatibility type filter
            if filters.preferred_types and c.type not in filters.preferred_types:
                continue

            # Exclude locked filter
            if filters.exclude_locked and c.myLock is not None:
                continue

            # Exclude submitted filter
            if filters.exclude_submitted and c.mySubmission is not None:
                continue

            filtered.append(c)

        # Sort by payout desc, then slots remaining asc (race for scarce slots)
        filtered.sort(key=lambda c: (-c.payout_amount, c.slots_remaining if c.slots_remaining is not None else float('inf')))

        return filtered

    async def get_available_campaigns(
        self,
        filters: Optional[CampaignFilter] = None,
    ) -> List[Campaign]:
        """Fetch and filter available campaigns."""
        raw_campaigns = await self.router.list_campaigns()
        return self._filter_campaigns(raw_campaigns, filters)

    async def lock_campaign(
        self,
        campaign_id: str,
        strategy: Optional[str] = None,
        force: bool = False,
    ) -> SlotLockResult:
        """Lock a campaign slot with quota checks.

        For ugcSlotMode == 'claim_slot' campaigns, routes directly to
        APIStrategy.lock_slot_for_claim_campaign() which handles slot
        iteration and 409 collisions internally.  This keeps the circuit
        breaker clean — slot-level 409s are business events, not failures.

        For all other campaign types (open_submit, etc.) the existing
        StrategyRouter path is used unchanged.

        Args:
            campaign_id: Campaign to lock.
            strategy: Force specific strategy (open_submit path only).
            force: Bypass quota checks (manual override).

        Returns:
            SlotLockResult with outcome.
        """
        if not force and not self._check_quota():
            return SlotLockResult(
                success=False,
                campaign_id=campaign_id,
                campaign_title=campaign_id,
                message=f"Daily quota exceeded ({settings.campaign_filter_max_slots_per_day} slots/day)",
                strategy_used="quota",
                response_time_ms=0,
            )

        # --- Branch on campaign type ---
        # Fetch campaign to determine ugcSlotMode.
        # get_campaign() also hydrates scheduledSlots so it does double duty.
        api_strategy = self.router._get_strategy("api")
        campaign = await api_strategy.get_campaign(campaign_id)

        if campaign and campaign.needs_claim:
            # claim_slot path: slot-aware locking entirely within APIStrategy.
            # StrategyRouter / CircuitBreaker are intentionally bypassed here.
            self.logger.info(
                "client.claim_slot_path",
                campaign_id=campaign_id,
                slots=len(campaign.scheduledSlots),
            )
            result = await api_strategy.lock_slot_for_claim_campaign(campaign)
        else:
            # Standard path: open_submit and all other campaign types.
            result = await self.router.lock_slot(campaign_id, preferred_strategy=strategy)

        if result.success:
            self._slots_locked_today += 1
            self._locked_campaigns.add(campaign_id)
            self.logger.info(
                "client.slot_locked",
                campaign=campaign_id,
                daily_count=self._slots_locked_today,
            )

        return result

    def score_campaign(self, c: Campaign) -> float:
        """Calculate a priority score for campaign locking."""
        score = c.payout_amount * 10.0
        if c.slots_remaining and c.slots_remaining <= 3:
            score += 50.0
        if c.kind == "ugc":
            score += 20.0
        if c.ends_at:
            now = datetime.now(c.ends_at.tzinfo) if c.ends_at.tzinfo else datetime.utcnow()
            time_to_end = (c.ends_at - now).total_seconds()
            if time_to_end < 3600:  # Less than 1 hour
                score += 30.0
        return score

    async def fast_lock_campaign(self, campaign_id: str) -> SlotLockResult:
        """Lock a campaign slot quickly bypassing standard checks/fallbacks."""
        return await self.router.fast_lock(campaign_id)

    async def auto_lock_available(
        self,
        filters: Optional[CampaignFilter] = None,
        campaigns: Optional[List[Campaign]] = None,
    ) -> List[SlotLockResult]:
        """Automatically lock all available campaigns matching filters concurrently."""
        if not settings.auto_lock_enabled:
            return []

        if campaigns is None:
            campaigns = await self.get_available_campaigns(filters)
        else:
            campaigns = self._filter_campaigns(campaigns, filters)

        if not campaigns:
            return []

        # Sort campaigns by score descending
        scored_campaigns = []
        for c in campaigns:
            score = self.score_campaign(c)
            scored_campaigns.append((score, c))
        
        scored_campaigns.sort(key=lambda x: x[0], reverse=True)
        sorted_campaigns = [c for _, c in scored_campaigns]

        # Determine how many we can attempt based on remaining quota
        quota_remaining = max(0, settings.campaign_filter_max_slots_per_day - self._slots_locked_today)
        if quota_remaining <= 0:
            self.logger.info("client.quota_exhausted_on_autolock")
            return []

        # Limit to the max concurrent allowed, and no more than the remaining daily quota
        limit = min(settings.auto_lock_max_concurrent, quota_remaining)
        campaigns_to_attempt = sorted_campaigns[:limit]

        if not campaigns_to_attempt:
            return []

        self.logger.info("client.auto_lock_concurrent_start", count=len(campaigns_to_attempt))

        # We will use fast_lock concurrently!
        tasks = [self.fast_lock_campaign(c.id) for c in campaigns_to_attempt]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            cid = campaigns_to_attempt[i].id
            if isinstance(result, Exception):
                self.logger.error("client.auto_lock_concurrent_exception", campaign_id=cid, error=str(result))
                processed_results.append(SlotLockResult(
                    success=False,
                    campaign_id=cid,
                    campaign_title=campaigns_to_attempt[i].title,
                    message=f"Concurrent exception: {str(result)}",
                    strategy_used="concurrent",
                    response_time_ms=0,
                ))
            else:
                processed_results.append(result)
                if result.success:
                    # Update quota
                    self._slots_locked_today += 1
                    self._locked_campaigns.add(cid)
                    self.logger.info(
                        "client.slot_locked",
                        campaign=cid,
                        daily_count=self._slots_locked_today,
                    )
                else:
                    # Near-miss notification: if result was a 409 conflict, we trigger a near-miss alert!
                    if result.message == "taken":
                        # Fire task to notify near miss
                        asyncio.create_task(self.router.notifier.notify_near_miss(campaigns_to_attempt[i], result.response_time_ms))

        return processed_results

    def get_stats(self) -> dict:
        """Get client statistics."""
        return {
            "slots_locked_today": self._slots_locked_today,
            "daily_limit": settings.campaign_filter_max_slots_per_day,
            "locked_campaigns": list(self._locked_campaigns),
            "quota_remaining": max(0, settings.campaign_filter_max_slots_per_day - self._slots_locked_today),
        }