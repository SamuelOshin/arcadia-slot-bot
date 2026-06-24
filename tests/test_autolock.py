"""
Auto-Lock Pipeline Tests
========================
Tests the full auto-lock pipeline to prevent regressions in:

1.  fast_lock cookie injection  — uses _request(), not raw aiohttp
2.  _filter_campaigns rules     — payout, slots, reservation, lockable
3.  auto_lock_available routing — claim_slot vs fast_lock branching
4.  400/409/2xx response handling in fast_lock
5.  Campaign model is_lockable property
6.  Quota enforcement
"""

import asyncio
import sys
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup — works both locally and on Railway CI
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Campaign, SlotLockResult, CampaignFilter
from app.config import settings
from app.services.campaign_monitor import CampaignMonitor


# ===========================================================================
# Helpers
# ===========================================================================

def _future_date(days: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _make_campaign(
    id: str = "abc123",
    title: str = "Test Campaign",
    status: str = "active",
    kind: str = "ugc",
    payout: float = 5.0,
    slots_remaining: int = 10,
    my_lock: dict = None,
    my_submission: dict = None,
    reservation: dict = None,
    ugc_slot_mode: str = "open_submit",
) -> Campaign:
    """Build a minimal Campaign object for testing."""
    return Campaign.model_validate({
        "_id": id,
        "campaignCode": f"TEST-{id}",
        "title": title,
        "description": "Test campaign description",
        "startDate": datetime.now(timezone.utc).isoformat(),
        "endDate": _future_date(30).isoformat(),
        "maxSlots": 30,
        "slotsLocked": 30 - slots_remaining,
        "slotsRemaining": slots_remaining,
        "kind": kind,
        "status": status,
        "postPrice": payout if kind == "ugc" else None,
        "cpmRules": [{"tier": "bronze", "ratePerThousand": payout}] if kind != "ugc" else [],
        "myLock": my_lock,
        "mySubmission": my_submission,
        "reservation": reservation,
        "ugcSlotMode": ugc_slot_mode,
    })


def _make_session(cookie: str = "session=abc; __Secure-next-auth.session-token=tok123") -> MagicMock:
    """Build a mock SessionManager."""
    session = MagicMock()
    session.is_valid = True
    session.headers = {"Cookie": cookie, "Accept": "*/*"}
    session.cookie_jar = {"session": "abc", "__Secure-next-auth.session-token": "tok123"}
    session.refresh = AsyncMock(return_value=False)
    session.update_cookies_from_response = MagicMock()
    return session


# ===========================================================================
# 1. Campaign.is_lockable property
# ===========================================================================

class TestIsLockable:
    def test_lockable_normal_campaign(self):
        c = _make_campaign()
        assert c.is_lockable is True

    def test_not_lockable_when_already_locked_by_user(self):
        c = _make_campaign(my_lock={"slotNumber": 1})
        assert c.is_lockable is False

    def test_not_lockable_when_already_submitted(self):
        c = _make_campaign(my_submission={"id": "sub1"})
        assert c.is_lockable is False

    def test_not_lockable_when_no_slots(self):
        c = _make_campaign(slots_remaining=0)
        assert c.is_lockable is False

    def test_not_lockable_when_status_locked(self):
        c = _make_campaign(status="locked")
        assert c.is_lockable is False

    def test_not_lockable_reservation_full_for_bronze(self):
        """Bronze user cannot lock when generalLocked >= generalCapacity."""
        c = _make_campaign(reservation={
            "enabled": True,
            "reservedEligibleForMe": False,
            "generalCapacity": 5,
            "generalLocked": 5,
            "reservedTotal": 5,
            "reservedLocked": 0,
        })
        assert c.is_lockable is False

    def test_lockable_reservation_has_general_slots_for_bronze(self):
        """Bronze user CAN lock when general slots still available."""
        c = _make_campaign(reservation={
            "enabled": True,
            "reservedEligibleForMe": False,
            "generalCapacity": 5,
            "generalLocked": 3,
            "reservedTotal": 5,
            "reservedLocked": 0,
        })
        assert c.is_lockable is True

    def test_lockable_no_reservation(self):
        c = _make_campaign(reservation=None)
        assert c.is_lockable is True

    def test_needs_claim_ugcSlotMode(self):
        c = _make_campaign(ugc_slot_mode="claim_slot")
        assert c.needs_claim is True

    def test_not_needs_claim_open_submit(self):
        c = _make_campaign(ugc_slot_mode="open_submit")
        assert c.needs_claim is False


# ===========================================================================
# 2. ArcadiaClient._filter_campaigns
# ===========================================================================

class TestFilterCampaigns:
    def setup_method(self):
        """Set up a real ArcadiaClient with mocked router."""
        from app.services.arcadia_client import ArcadiaClient
        self.router = MagicMock()
        self.client = ArcadiaClient(self.router)

    def _filter(self, campaigns, **filter_kwargs):
        filter_kwargs.setdefault("min_payout", 0.0)
        filter_kwargs.setdefault("auto_lock", True)
        f = CampaignFilter(**filter_kwargs)
        return self.client._filter_campaigns(campaigns, f)

    def test_passes_normal_campaign(self):
        c = _make_campaign()
        result = self._filter([c])
        assert len(result) == 1

    def test_filters_out_not_lockable(self):
        c = _make_campaign(slots_remaining=0)
        result = self._filter([c])
        assert len(result) == 0

    def test_filters_out_already_locked_by_bot(self):
        c = _make_campaign(id="locked-id")
        self.client._locked_campaigns.add("locked-id")
        result = self._filter([c])
        assert len(result) == 0

    def test_filters_out_below_min_payout(self):
        c = _make_campaign(payout=1.0)
        result = self._filter([c], min_payout=5.0)
        assert len(result) == 0

    def test_passes_at_exactly_min_payout(self):
        c = _make_campaign(payout=5.0)
        result = self._filter([c], min_payout=5.0)
        assert len(result) == 1

    def test_filters_general_slots_full_for_bronze(self):
        c = _make_campaign(reservation={
            "enabled": True,
            "reservedEligibleForMe": False,
            "generalCapacity": 5,
            "generalLocked": 5,
        })
        result = self._filter([c])
        assert len(result) == 0

    def test_passes_general_slots_available_for_bronze(self):
        c = _make_campaign(reservation={
            "enabled": True,
            "reservedEligibleForMe": False,
            "generalCapacity": 5,
            "generalLocked": 2,
        })
        result = self._filter([c])
        assert len(result) == 1

    def test_sorts_by_payout_descending(self):
        c1 = _make_campaign(id="a", payout=2.0)
        c2 = _make_campaign(id="b", payout=5.0)
        c3 = _make_campaign(id="c", payout=3.0)
        result = self._filter([c1, c2, c3])
        assert [r.id for r in result] == ["b", "c", "a"]

    def test_zero_min_payout_passes_everything(self):
        """$0.0 min payout should NOT filter anything by payout."""
        c = _make_campaign(payout=0.5)
        result = self._filter([c], min_payout=0.0)
        assert len(result) == 1


# ===========================================================================
# 3. fast_lock uses _request() — the core regression test
# ===========================================================================

class TestFastLock:
    def _make_strategy(self):
        from app.strategies.api_strategy import APIStrategy
        session = _make_session()
        strategy = APIStrategy.__new__(APIStrategy)
        strategy.session = session
        strategy.base_url = "https://arcadia-roster.up.railway.app/api"
        strategy.logger = MagicMock()
        strategy.logger.warning = MagicMock()
        # We patch _request, not the raw aiohttp client
        strategy._request = AsyncMock()
        return strategy

    @pytest.mark.asyncio
    async def test_fast_lock_calls_request_not_raw_aiohttp(self):
        """CRITICAL: fast_lock must call _request(), not self.client.post() directly.

        This is the regression test for the cookie bug that caused 400 errors
        on every campaign drop. Raw aiohttp calls bypass the session cookie jar.
        """
        strategy = self._make_strategy()
        strategy._request.return_value = (200, {"title": "Win!"}, '{"title":"Win!"}', {})

        result = await strategy.fast_lock("campaign-abc")

        # _request must have been called with POST and the lock URL
        strategy._request.assert_called_once()
        args, kwargs = strategy._request.call_args
        assert args[0] == "POST"
        assert "campaign-abc/lock" in args[1]
        assert result.success is True

    @pytest.mark.asyncio
    async def test_fast_lock_200_returns_success(self):
        strategy = self._make_strategy()
        strategy._request.return_value = (
            200,
            {"title": "Wire Network", "myLock": {"slotNumber": 3}},
            '{"title":"Wire Network"}',
            {},
        )
        result = await strategy.fast_lock("abc")
        assert result.success is True
        assert result.campaign_title == "Wire Network"
        assert result.slot_number == 3
        assert result.strategy_used == "api-fast"

    @pytest.mark.asyncio
    async def test_fast_lock_201_returns_success(self):
        strategy = self._make_strategy()
        strategy._request.return_value = (201, {"title": "Test"}, "", {})
        result = await strategy.fast_lock("abc")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_fast_lock_409_returns_taken(self):
        strategy = self._make_strategy()
        strategy._request.return_value = (409, {"message": "Conflict"}, "Conflict", {})
        result = await strategy.fast_lock("abc")
        assert result.success is False
        assert result.message == "taken"
        assert result.definitive is True

    @pytest.mark.asyncio
    async def test_fast_lock_400_logs_body_and_returns_failure(self):
        """400 must log the full response body so we can diagnose the problem."""
        strategy = self._make_strategy()
        strategy._request.return_value = (
            400,
            {"message": "Campaign already locked"},
            '{"message":"Campaign already locked"}',
            {},
        )
        result = await strategy.fast_lock("abc")
        assert result.success is False
        assert "bad_request" in result.message
        # Must log the warning with the body
        strategy.logger.warning.assert_called_once()
        warn_call = strategy.logger.warning.call_args
        assert "bad_request" in warn_call[0][0]

    @pytest.mark.asyncio
    async def test_fast_lock_500_returns_failure(self):
        strategy = self._make_strategy()
        strategy._request.return_value = (500, None, "Internal Server Error", {})
        result = await strategy.fast_lock("abc")
        assert result.success is False
        assert "500" in result.message

    @pytest.mark.asyncio
    async def test_fast_lock_exception_returns_error_not_definitive(self):
        """Network errors should NOT be marked definitive so caller can retry."""
        strategy = self._make_strategy()
        strategy._request.side_effect = Exception("connection refused")
        result = await strategy.fast_lock("abc")
        assert result.success is False
        assert result.definitive is False
        assert "connection refused" in result.message


# ===========================================================================
# 4. API list_campaigns failover behavior
# ===========================================================================

class TestApiListCampaignsFailures:
    @pytest.mark.asyncio
    async def test_list_campaigns_propagates_request_timeout(self):
        """Timeouts must propagate so StrategyRouter can fail over to fallback strategies."""
        from app.strategies.api_strategy import APIStrategy

        strategy = APIStrategy.__new__(APIStrategy)
        strategy.base_url = "https://arcadia-roster.up.railway.app/api"
        strategy.logger = MagicMock()
        strategy._request = AsyncMock(side_effect=TimeoutError("request timed out"))

        with pytest.raises(TimeoutError):
            await strategy.list_campaigns()
        strategy._request.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_campaigns_raises_on_non_200_status(self):
        """Non-auth HTTP failures must propagate for strategy fallback."""
        from app.strategies.api_strategy import APIStrategy

        strategy = APIStrategy.__new__(APIStrategy)
        strategy.base_url = "https://arcadia-roster.up.railway.app/api"
        strategy.logger = MagicMock()
        strategy._request = AsyncMock(return_value=(500, None, "", {}))

        with pytest.raises(RuntimeError, match="status 500"):
            await strategy.list_campaigns()
        strategy._request.assert_called_once()


# ===========================================================================
# 5. auto_lock_available routing — claim_slot vs fast_lock
# ===========================================================================

class TestAutoLockRouting:
    def _make_client(self):
        from app.services.arcadia_client import ArcadiaClient
        router = MagicMock()
        router._get_strategy = MagicMock()
        client = ArcadiaClient(router)
        return client

    @pytest.mark.asyncio
    async def test_open_submit_uses_fast_lock(self):
        """Regular open_submit campaigns must go through fast_lock_campaign."""
        client = self._make_client()
        campaign = _make_campaign(ugc_slot_mode="open_submit")

        client.fast_lock_campaign = AsyncMock(return_value=SlotLockResult(
            success=True, campaign_id=campaign.id, campaign_title=campaign.title,
            message="locked", strategy_used="api-fast", response_time_ms=50,
        ))

        mock_api = MagicMock()
        mock_api.lock_slot_for_claim_campaign = AsyncMock()
        client.router._get_strategy.return_value = mock_api

        with patch.object(settings, "auto_lock_enabled", True), \
             patch.object(settings, "campaign_filter_min_payout", 0.0), \
             patch.object(settings, "campaign_filter_max_slots_per_day", 3), \
             patch.object(settings, "auto_lock_max_concurrent", 2):
            results = await client.auto_lock_available(campaigns=[campaign])

        # fast_lock_campaign called; claim path NOT called
        client.fast_lock_campaign.assert_called_once_with(campaign.id)
        mock_api.lock_slot_for_claim_campaign.assert_not_called()
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_claim_slot_uses_lock_slot_for_claim_campaign(self):
        """claim_slot campaigns must go through lock_slot_for_claim_campaign."""
        client = self._make_client()
        campaign = _make_campaign(ugc_slot_mode="claim_slot")

        mock_api = MagicMock()
        mock_api.lock_slot_for_claim_campaign = AsyncMock(return_value=SlotLockResult(
            success=True, campaign_id=campaign.id, campaign_title=campaign.title,
            message="Slot claimed", strategy_used="api", response_time_ms=80,
        ))
        client.router._get_strategy.return_value = mock_api
        client.fast_lock_campaign = AsyncMock()

        with patch.object(settings, "auto_lock_enabled", True), \
             patch.object(settings, "campaign_filter_min_payout", 0.0), \
             patch.object(settings, "campaign_filter_max_slots_per_day", 3), \
             patch.object(settings, "auto_lock_max_concurrent", 2):
            results = await client.auto_lock_available(campaigns=[campaign])

        # claim path called; fast_lock NOT called
        mock_api.lock_slot_for_claim_campaign.assert_called_once_with(campaign)
        client.fast_lock_campaign.assert_not_called()
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_auto_lock_disabled_returns_empty(self):
        client = self._make_client()
        campaign = _make_campaign()
        with patch.object(settings, "auto_lock_enabled", False):
            results = await client.auto_lock_available(campaigns=[campaign])
        assert results == []

    @pytest.mark.asyncio
    async def test_auto_lock_respects_daily_quota(self):
        """If quota exhausted, should return empty and not attempt any lock."""
        client = self._make_client()
        client._slots_locked_today = 3   # already at limit
        campaign = _make_campaign()

        client.fast_lock_campaign = AsyncMock()

        with patch.object(settings, "auto_lock_enabled", True), \
             patch.object(settings, "campaign_filter_max_slots_per_day", 3), \
             patch.object(settings, "campaign_filter_min_payout", 0.0), \
             patch.object(settings, "auto_lock_max_concurrent", 2):
            results = await client.auto_lock_available(campaigns=[campaign])

        client.fast_lock_campaign.assert_not_called()
        assert results == []

    @pytest.mark.asyncio
    async def test_quota_increments_on_success(self):
        """Successful lock must increment _slots_locked_today."""
        client = self._make_client()
        campaign = _make_campaign()
        assert client._slots_locked_today == 0

        mock_api = MagicMock()
        mock_api.lock_slot_for_claim_campaign = AsyncMock()
        client.router._get_strategy.return_value = mock_api

        client.fast_lock_campaign = AsyncMock(return_value=SlotLockResult(
            success=True, campaign_id=campaign.id, campaign_title=campaign.title,
            message="locked", strategy_used="api-fast", response_time_ms=50,
        ))

        with patch.object(settings, "auto_lock_enabled", True), \
             patch.object(settings, "campaign_filter_min_payout", 0.0), \
             patch.object(settings, "campaign_filter_max_slots_per_day", 3), \
             patch.object(settings, "auto_lock_max_concurrent", 2):
            results = await client.auto_lock_available(campaigns=[campaign])

        assert client._slots_locked_today == 1
        assert campaign.id in client._locked_campaigns

    @pytest.mark.asyncio
    async def test_exception_in_lock_handled_gracefully(self):
        """If one campaign lock throws, the other campaigns still process."""
        client = self._make_client()
        c1 = _make_campaign(id="camp1")
        c2 = _make_campaign(id="camp2")

        mock_api = MagicMock()
        mock_api.lock_slot_for_claim_campaign = AsyncMock()
        client.router._get_strategy.return_value = mock_api

        async def flaky_lock(campaign_id):
            if campaign_id == "camp1":
                raise Exception("network timeout")
            return SlotLockResult(
                success=True, campaign_id=campaign_id, campaign_title="Camp2",
                message="locked", strategy_used="api-fast", response_time_ms=50,
            )

        client.fast_lock_campaign = flaky_lock

        with patch.object(settings, "auto_lock_enabled", True), \
             patch.object(settings, "campaign_filter_min_payout", 0.0), \
             patch.object(settings, "campaign_filter_max_slots_per_day", 3), \
             patch.object(settings, "auto_lock_max_concurrent", 2):
            results = await client.auto_lock_available(campaigns=[c1, c2])

        # Both results returned despite one exception
        assert len(results) == 2
        failed = next(r for r in results if r.campaign_id == "camp1")
        succeeded = next(r for r in results if r.campaign_id == "camp2")
        assert failed.success is False
        assert succeeded.success is True


# ===========================================================================
# 6. lock_campaign routes correctly based on campaign type
# ===========================================================================

class TestLockCampaignRouting:
    def _make_client(self):
        from app.services.arcadia_client import ArcadiaClient
        router = MagicMock()
        client = ArcadiaClient(router)
        return client

    @pytest.mark.asyncio
    async def test_open_submit_goes_to_router(self):
        """Non-claim campaigns must go through router.lock_slot, not APIStrategy directly."""
        client = self._make_client()

        mock_api = MagicMock()
        mock_api.get_campaign = AsyncMock(return_value=_make_campaign(ugc_slot_mode="open_submit"))
        mock_api.lock_slot_for_claim_campaign = AsyncMock()
        client.router._get_strategy.return_value = mock_api
        client.router.lock_slot = AsyncMock(return_value=SlotLockResult(
            success=True, campaign_id="abc", campaign_title="Test",
            message="ok", strategy_used="api", response_time_ms=50,
        ))

        result = await client.lock_campaign("abc")
        client.router.lock_slot.assert_called_once_with("abc", preferred_strategy=None)
        mock_api.lock_slot_for_claim_campaign.assert_not_called()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_claim_slot_skips_router(self):
        """claim_slot campaigns must bypass router and call lock_slot_for_claim_campaign."""
        client = self._make_client()
        campaign = _make_campaign(ugc_slot_mode="claim_slot")

        mock_api = MagicMock()
        mock_api.get_campaign = AsyncMock(return_value=campaign)
        mock_api.lock_slot_for_claim_campaign = AsyncMock(return_value=SlotLockResult(
            success=True, campaign_id=campaign.id, campaign_title=campaign.title,
            message="claimed", strategy_used="api", response_time_ms=80,
        ))
        client.router._get_strategy.return_value = mock_api
        client.router.lock_slot = AsyncMock()

        result = await client.lock_campaign(campaign.id)
        mock_api.lock_slot_for_claim_campaign.assert_called_once_with(campaign)
        client.router.lock_slot.assert_not_called()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_failure_without_locking(self):
        client = self._make_client()
        client._slots_locked_today = 3
        mock_api = MagicMock()
        mock_api.get_campaign = AsyncMock()
        client.router._get_strategy.return_value = mock_api

        with patch.object(settings, "campaign_filter_max_slots_per_day", 3):
            result = await client.lock_campaign("abc", force=False)

        assert result.success is False
        assert "quota" in result.message.lower()
        mock_api.get_campaign.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_bypasses_quota(self):
        """force=True (manual Telegram button) must bypass daily quota."""
        client = self._make_client()
        client._slots_locked_today = 3
        campaign = _make_campaign(ugc_slot_mode="open_submit")

        mock_api = MagicMock()
        mock_api.get_campaign = AsyncMock(return_value=campaign)
        client.router._get_strategy.return_value = mock_api
        client.router.lock_slot = AsyncMock(return_value=SlotLockResult(
            success=True, campaign_id=campaign.id, campaign_title=campaign.title,
            message="ok", strategy_used="api", response_time_ms=50,
        ))

        with patch.object(settings, "campaign_filter_max_slots_per_day", 3):
            result = await client.lock_campaign(campaign.id, force=True)

        assert result.success is True


# ===========================================================================
# 7. Campaign Monitor Tests
# ===========================================================================

class TestCampaignMonitor:
    @pytest.mark.asyncio
    async def test_warmup_seeds_and_skips_notifications_and_locking(self):
        """First check_and_lock call should warm up, seeding raw campaigns, returning interval, and doing no notification/locking."""
        mock_client = AsyncMock()
        mock_notifier = AsyncMock()
        
        c1 = _make_campaign(id="c1", slots_remaining=5)
        c2 = _make_campaign(id="c2", slots_remaining=0) # full
        mock_client.router.list_campaigns.return_value = [c1, c2]
        
        monitor = CampaignMonitor(client=mock_client, notifier=mock_notifier)
        assert monitor._is_warmed_up is False
        
        with patch.object(settings, "poll_interval_seconds", 30):
            interval = await monitor.check_and_lock()
            
        assert interval == 30
        assert monitor._is_warmed_up is True
        assert monitor._known_campaigns == {"c1", "c2"}
        mock_notifier.notify_campaign_dropped.assert_not_called()
        mock_client.auto_lock_available.assert_not_called()

    @pytest.mark.asyncio
    async def test_subsequent_poll_detects_new_campaign_and_notifies_and_locks(self):
        """Subsequent poll detects new campaigns, notifies, and invokes auto-lock."""
        mock_client = AsyncMock()
        mock_notifier = AsyncMock()
        
        c1 = _make_campaign(id="c1", slots_remaining=5)
        mock_client.router.list_campaigns.return_value = [c1]
        
        monitor = CampaignMonitor(client=mock_client, notifier=mock_notifier)
        # Manually warm up
        monitor._is_warmed_up = True
        monitor._known_campaigns = {"c1"}
        
        # New poll has c1, and a new c2
        c2 = _make_campaign(id="c2", slots_remaining=3)
        mock_client.router.list_campaigns.return_value = [c1, c2]
        
        # Mock auto-lock response
        mock_client.auto_lock_available.return_value = [
            SlotLockResult(success=True, campaign_id="c2", campaign_title="Test", message="locked", strategy_used="api", response_time_ms=50)
        ]
        
        with patch.object(settings, "auto_lock_enabled", True):
            await monitor.check_and_lock()
            
        # Should detect c2 as new
        mock_notifier.notify_campaign_dropped.assert_called_once_with(c2)
        mock_client.auto_lock_available.assert_called_once_with(campaigns=[c1, c2])
        assert monitor._known_campaigns == {"c1", "c2"}

    @pytest.mark.asyncio
    async def test_subsequent_poll_with_no_auto_lock(self):
        """Subsequent poll notifies but does not lock if auto-lock is disabled."""
        mock_client = AsyncMock()
        mock_notifier = AsyncMock()
        
        c1 = _make_campaign(id="c1", slots_remaining=5)
        mock_client.router.list_campaigns.return_value = [c1]
        
        monitor = CampaignMonitor(client=mock_client, notifier=mock_notifier)
        monitor._is_warmed_up = True
        monitor._known_campaigns = {"c1"}
        
        c2 = _make_campaign(id="c2", slots_remaining=3)
        mock_client.router.list_campaigns.return_value = [c1, c2]
        
        with patch.object(settings, "auto_lock_enabled", False):
            await monitor.check_and_lock()
            
        mock_notifier.notify_campaign_dropped.assert_called_once_with(c2)
        mock_client.auto_lock_available.assert_not_called()


# ===========================================================================
# Runner (also works with: uv run pytest tests/test_autolock.py -v)
# ===========================================================================

if __name__ == "__main__":
    import subprocess
    subprocess.run([sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"])
