"""Slot locking endpoints."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from app.models import SlotLockResult, LockRequest
from app.services.arcadia_client import ArcadiaClient
from app.services.slot_locker import SlotLocker
from app.dependencies import get_strategy_router
from app.strategies.strategy_router import StrategyRouter

router = APIRouter(prefix="/slots", tags=["Slots"])


@router.post("/lock/{campaign_id}", response_model=SlotLockResult)
async def lock_slot(
    campaign_id: str,
    strategy: Optional[str] = None,
    force: bool = False,
    router: StrategyRouter = Depends(get_strategy_router),
):
    """Manually lock a slot on a specific campaign.

    Args:
        campaign_id: The campaign ID to lock (e.g., WIRENETWORK-UGC-1).
        strategy: Force a specific strategy (api, playwright, ai_agent).
        force: Bypass daily quota checks.

    Returns:
        SlotLockResult with success/failure details.
    """
    client = ArcadiaClient(router)
    result = await client.lock_campaign(campaign_id, strategy=strategy, force=force)
    return result


@router.post("/lock", response_model=SlotLockResult)
async def lock_slot_body(
    request: LockRequest,
    router: StrategyRouter = Depends(get_strategy_router),
):
    """Lock a slot with request body (for complex requests)."""
    client = ArcadiaClient(router)
    result = await client.lock_campaign(
        request.campaign_id,
        strategy=request.strategy,
        force=request.force,
    )
    return result


@router.post("/lock-retry/{campaign_id}", response_model=SlotLockResult)
async def lock_with_retry(
    campaign_id: str,
    max_retries: int = 3,
    strategy: Optional[str] = None,
    router: StrategyRouter = Depends(get_strategy_router),
):
    """Lock a slot with automatic retry on conflict.

    Useful when competing for slots that just opened up.
    """
    client = ArcadiaClient(router)
    locker = SlotLocker(client)
    result = await locker.lock_with_retry(campaign_id, max_retries=max_retries, strategy=strategy)
    return result


@router.post("/auto-lock")
async def auto_lock_all(
    router: StrategyRouter = Depends(get_strategy_router),
):
    """Automatically lock all available campaigns matching filters.

    Requires AUTO_LOCK_ENABLED=true in config.
    """
    client = ArcadiaClient(router)
    results = await client.auto_lock_available()

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    return {
        "total_attempted": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "results": results,
    }