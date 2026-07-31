"""Background task scheduler for campaign monitoring.

Runs as a separate process or integrated with FastAPI lifespan.
"""
import asyncio
import datetime as dt
from typing import List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import structlog
from app.config import settings
from app.services.campaign_monitor import CampaignMonitor

logger = structlog.get_logger()

# Hard cap (seconds) on a single poll cycle.
# Prevents a slow Playwright fallback from blocking the next tick.
_POLL_TIMEOUT_SECONDS = 8.0

# Startup jitter increment per account (seconds).
# Spreads accounts evenly across the poll window so coverage is near-continuous.
_JITTER_STEP_SECONDS = 0.4


class BotScheduler:
    """Manages background polling and monitoring tasks."""

    def __init__(self, monitors: List[CampaignMonitor]):
        self.monitors = monitors
        self.monitor = monitors[0] if monitors else None
        self.scheduler = AsyncIOScheduler()
        self._running = False
        # Per-monitor interval tracking — avoids one account overwriting another's state.
        self.current_intervals: dict[str, int] = {
            m.account_label: settings.poll_interval_seconds for m in monitors
        }
        # Keep legacy single-value for backwards compat with external callers
        self.current_interval = settings.poll_interval_seconds

    def start(self) -> None:
        """Start the scheduler with configured jobs."""
        if self._running:
            return

        # Main campaign polling job per monitor
        # Each account is staggered by _JITTER_STEP_SECONDS so they never poll in lockstep.
        # max_instances=2 allows one "late" in-flight cycle to coexist with the next tick
        # instead of silently dropping it (the root cause of missed campaign drops).
        for i, monitor in enumerate(self.monitors):
            safe_label = monitor.account_label.lower().replace(" ", "_")
            interval = self.current_intervals[monitor.account_label]
            jitter = i * _JITTER_STEP_SECONDS
            start_date = dt.datetime.now() + dt.timedelta(seconds=jitter)
            self.scheduler.add_job(
                self._make_poll_job(monitor),
                trigger=IntervalTrigger(seconds=interval, start_date=start_date),
                id=f"poll_campaigns_{safe_label}",
                replace_existing=True,
                max_instances=2,
            )

        # Connection warmup job run every 60s
        self.scheduler.add_job(
            self._warmup,
            trigger=IntervalTrigger(seconds=60),
            id="connection_warmup",
            replace_existing=True,
            max_instances=1,
        )

        # Health check / heartbeat
        self.scheduler.add_job(
            self._heartbeat,
            trigger=IntervalTrigger(minutes=5),
            id="heartbeat",
            replace_existing=True,
        )

        self.scheduler.start()
        self._running = True
        logger.info("scheduler.started", poll_interval=self.current_interval)

    def stop(self) -> None:
        """Gracefully stop the scheduler."""
        if not self._running:
            return
        self.scheduler.shutdown(wait=True)
        self._running = False
        logger.info("scheduler.stopped")

    def pause(self) -> None:
        """Pause all scheduler jobs."""
        self.scheduler.pause()
        logger.info("scheduler.paused")

    def resume(self) -> None:
        """Resume all scheduler jobs."""
        self.scheduler.resume()
        logger.info("scheduler.resumed")

    def _make_poll_job(self, monitor: CampaignMonitor):
        async def _poll_campaigns() -> None:
            try:
                logger.debug("scheduler.poll_start", account=monitor.account_label)
                # Hard timeout: if a poll cycle hangs (e.g. Playwright fallback slow),
                # cancel it rather than blocking the next scheduled tick.
                next_interval = await asyncio.wait_for(
                    monitor.check_and_lock(),
                    timeout=_POLL_TIMEOUT_SECONDS,
                )

                safe_label = monitor.account_label.lower().replace(" ", "_")
                prev_interval = self.current_intervals.get(monitor.account_label, self.current_interval)
                if self._running and next_interval != prev_interval:
                    logger.info(
                        "scheduler.reschedule",
                        account=monitor.account_label,
                        old_interval=prev_interval,
                        new_interval=next_interval,
                    )
                    self.scheduler.reschedule_job(
                        f"poll_campaigns_{safe_label}",
                        trigger=IntervalTrigger(seconds=next_interval),
                    )
                    self.current_intervals[monitor.account_label] = next_interval
                    # Keep legacy single-value in sync with the first monitor
                    if monitor == self.monitors[0]:
                        self.current_interval = next_interval

            except asyncio.TimeoutError:
                logger.warning(
                    "scheduler.poll_timeout",
                    account=monitor.account_label,
                    timeout=_POLL_TIMEOUT_SECONDS,
                )
            except Exception as e:
                logger.error("scheduler.poll_failed", account=monitor.account_label, error=str(e))
        return _poll_campaigns

    async def _poll_campaigns(self) -> None:
        """Fallback poll method (polls first monitor)."""
        if self.monitors:
            await self._make_poll_job(self.monitors[0])()

    async def _warmup(self) -> None:
        """Keep connection warm and refresh session to prevent expiry."""
        for monitor in self.monitors:
            try:
                strategy = monitor.client.router._get_strategy("api")
                url = f"{strategy.base_url}/auth/session"
                status, _, _, _ = await strategy._request("GET", url)
                logger.debug("scheduler.session_warmed_and_refreshed", account=monitor.account_label, status=status)
            except Exception as e:
                logger.debug("scheduler.warmup_failed", account=monitor.account_label, error=str(e))

    async def _heartbeat(self) -> None:
        """Log heartbeat for monitoring."""
        logger.info("scheduler.heartbeat", timestamp=datetime.utcnow().isoformat())

    def add_one_off_job(self, func, delay_seconds: int) -> None:
        """Schedule a one-off job."""
        from apscheduler.triggers.date import DateTrigger
        run_date = datetime.utcnow() + __import__("datetime").timedelta(seconds=delay_seconds)
        self.scheduler.add_job(
            func,
            trigger=DateTrigger(run_date=run_date),
            replace_existing=False,
        )


# Standalone runner for docker-compose scheduler service
if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/app")

    async def main():
        monitor = CampaignMonitor()
        scheduler = BotScheduler(monitor)
        scheduler.start()

        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            scheduler.stop()

    asyncio.run(main())