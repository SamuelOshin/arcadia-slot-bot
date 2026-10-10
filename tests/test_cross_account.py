"""Cross-account drop broadcasting and even poll staggering."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.scheduler import BotScheduler
from app.services.campaign_monitor import CampaignMonitor, DropBroadcaster


def _campaign(cid, lockable=True):
    return SimpleNamespace(id=cid, is_lockable=lockable)


def _monitor(name, broadcaster):
    client = MagicMock()
    client.router.list_campaigns = AsyncMock(return_value=[])
    return CampaignMonitor(
        client=client,
        notifier=MagicMock(),
        account=SimpleNamespace(name=name, session_cookie="a=b", api_token=None,
                                csrf_token=None, resolved_storage_path=f"/tmp/x_{name}.json"),
        broadcaster=broadcaster,
    )


class TestDropDetection:
    def test_new_lockable_campaign_is_a_drop(self):
        m = _monitor("a", None)
        m._known_campaigns = {"old"}
        assert m._detect_drops([_campaign("new")]) == ["new"]

    def test_known_campaign_is_not_a_drop(self):
        m = _monitor("a", None)
        m._known_campaigns = {"c1"}
        m._last_campaign_states = {"c1": {"slots_available": True}}
        assert m._detect_drops([_campaign("c1")]) == []

    def test_reopened_slots_are_a_drop(self):
        m = _monitor("a", None)
        m._known_campaigns = {"c1"}
        m._last_campaign_states = {"c1": {"slots_available": False}}
        assert m._detect_drops([_campaign("c1")]) == ["c1"]

    def test_unlockable_campaign_is_ignored(self):
        m = _monitor("a", None)
        assert m._detect_drops([_campaign("new", lockable=False)]) == []


class TestBroadcaster:
    def test_announce_triggers_every_other_account(self):
        b = DropBroadcaster()
        mons = [_monitor(n, b) for n in "abc"]
        for m in mons:
            m.trigger_now = MagicMock(return_value=True)
        assert b.announce(mons[0], ["c1"]) == 2
        mons[0].trigger_now.assert_not_called()
        mons[1].trigger_now.assert_called_once()
        mons[2].trigger_now.assert_called_once()

    def test_same_campaign_is_not_rebroadcast_within_ttl(self):
        b = DropBroadcaster()
        mons = [_monitor(n, b) for n in "ab"]
        for m in mons:
            m.trigger_now = MagicMock(return_value=True)
        assert b.announce(mons[0], ["c1"]) == 1
        assert b.announce(mons[1], ["c1"]) == 0  # second account saw the same drop

    def test_paused_bot_does_not_broadcast(self):
        b = DropBroadcaster()
        mons = [_monitor(n, b) for n in "ab"]
        mons[1].trigger_now = MagicMock(return_value=True)
        b.is_paused = lambda: True
        assert b.announce(mons[0], ["c1"]) == 0
        mons[1].trigger_now.assert_not_called()


class TestTriggerNow:
    @pytest.mark.asyncio
    async def test_trigger_runs_a_cycle_once(self):
        m = _monitor("a", None)
        m.check_and_lock = AsyncMock(return_value=3)
        with patch("app.services.campaign_monitor.settings") as s:
            s.auto_lock_enabled = True
            assert m.trigger_now() is True
            assert m.trigger_now() is False  # already queued
            await asyncio.sleep(0.05)
        m.check_and_lock.assert_awaited_once()
        assert m._trigger_pending is False

    @pytest.mark.asyncio
    async def test_no_trigger_when_autolock_off_or_cycle_running(self):
        m = _monitor("a", None)
        with patch("app.services.campaign_monitor.settings") as s:
            s.auto_lock_enabled = False
            assert m.trigger_now() is False
            s.auto_lock_enabled = True
            m._cycles_in_flight = 1
            assert m.trigger_now() is False


class TestEvenStagger:
    def test_poll_offsets_are_interval_divided_by_account_count(self):
        mons = [SimpleNamespace(account_label=n) for n in ("a", "b", "c", "d")]
        sched = BotScheduler(mons)
        added = []
        sched.scheduler = MagicMock()
        sched.scheduler.add_job.side_effect = lambda fn, trigger=None, id=None, **k: added.append((id, trigger))
        sched._make_poll_job = lambda m: None
        with patch("app.core.scheduler.settings") as s:
            s.poll_interval_seconds = 3
            sched.current_intervals = {m.account_label: 3 for m in mons}
            sched.start()
        polls = [(i, t) for i, t in added if i.startswith("poll_campaigns_")]
        starts = [t.start_date for _, t in polls]
        gaps = [(starts[i + 1] - starts[i]).total_seconds() for i in range(3)]
        assert all(abs(g - 0.75) < 0.05 for g in gaps), gaps
