"""Dedicated slot locking service with race-condition handling.

Optimizes for speed when competing with other clippers.
"""
import asyncio
from datetime import datetime
from typing import Optional
import structlog
from app.models import SlotLockResult
from app.services.arcadia_client import ArcadiaClient

logger = structlog.get_logger()


class SlotLocker:
    """High-performance slot locker with retry logic.

    Handles the race condition where a slot opens up
    but gets taken between check and lock.
    """

    def __init__(self, client: ArcadiaClient):
        self.client = client
        self.logger = logger.bind(component="slot_locker")

    async def lock_with_retry(
        self,
        campaign_id: str,
        max_retries: int = 3,
        strategy: Optional[str] = None,
    ) -> SlotLockResult:
        """Attempt to lock with exponential backoff retry.

        Useful when slots release dynamically (previous holder backs out).
        """
        for attempt in range(1, max_retries + 1):
            result = await self.client.lock_campaign(campaign_id, strategy=strategy)

            if result.success:
                return result

            # If slot was taken, wait and retry
            if "already taken" in result.message.lower() or "conflict" in result.message.lower():
                wait = 2 ** attempt  # 2, 4, 8 seconds
                self.logger.info("locker.retry_wait", attempt=attempt, wait=wait, campaign=campaign_id)
                await asyncio.sleep(wait)
                continue

            # Other failure — don't retry
            return result

        return SlotLockResult(
            success=False,
            campaign_id=campaign_id,
            campaign_title=campaign_id,
            message=f"Failed after {max_retries} retries — slot consistently unavailable",
            strategy_used=strategy or "unknown",
            response_time_ms=0,
        )

    async def lock_all_available(self, campaign_ids: list) -> list:
        """Lock multiple campaigns concurrently.

        Warning: Only use if you can fulfill all slots!
        """
        tasks = [self.client.lock_campaign(cid) for cid in campaign_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append(SlotLockResult(
                    success=False,
                    campaign_id=campaign_ids[i],
                    campaign_title=campaign_ids[i],
                    message=f"Exception: {str(result)}",
                    strategy_used="concurrent",
                    response_time_ms=0,
                ))
            else:
                processed.append(result)

        return processed