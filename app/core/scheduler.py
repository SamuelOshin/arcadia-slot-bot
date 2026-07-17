"""Background task scheduler for campaign monitoring.

Runs as a separate process or integrated with FastAPI lifespan.
"""
import asyncio
from datetime import datetime
from typing import List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import structlog
from app.config import settings
from app.services.campaign_monitor import CampaignMonitor

logger = structlog.get_logger()


class BotScheduler:
    """Manages background polling and monitoring tasks."""

    def __init__(self, monitors: List[CampaignMonitor]):
        self.monitors = monitors
        self.monitor = monitors[0] if monitors else None
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self.current_interval = settings.poll_interval_seconds

    def start(self) -> None:
        """Start the scheduler with configured jobs."""
        if self._running:
            return

        # Main campaign polling job per monitor
        for monitor in self.monitors:
            safe_label = monitor.account_label.lower().replace(" ", "_")
            self.scheduler.add_job(
                self._make_poll_job(monitor),
                trigger=IntervalTrigger(seconds=self.current_interval),
                id=f"poll_campaigns_{safe_label}",
                replace_existing=True,
                max_instances=1,
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

    def _make_poll_job(self, monitor: CampaignMonitor):
        async def _poll_campaigns() -> None:
            try:
                logger.debug("scheduler.poll_start", account=monitor.account_label)
                next_interval = await monitor.check_and_lock()
                
                safe_label = monitor.account_label.lower().replace(" ", "_")
                if self._running and next_interval != self.current_interval:
                    logger.info("scheduler.reschedule", account=monitor.account_label, old_interval=self.current_interval, new_interval=next_interval)
                    self.scheduler.reschedule_job(
                        f"poll_campaigns_{safe_label}",
                        trigger=IntervalTrigger(seconds=next_interval)
                    )
                    self.current_interval = next_interval
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