"""Campaign listing and discovery endpoints."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from app.models import Campaign, CampaignFilter
from app.services.arcadia_client import ArcadiaClient
from app.services.campaign_monitor import CampaignMonitor
from app.dependencies import get_strategy_router, get_campaign_monitor
from app.strategies.strategy_router import StrategyRouter

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.get("", response_model=List[Campaign])
async def list_campaigns(
    min_payout: Optional[float] = Query(None, description="Minimum payout filter"),
    status: Optional[str] = Query("open", description="Campaign status filter"),
    router: StrategyRouter = Depends(get_strategy_router),
):
    """List available campaigns with optional filters.

    This fetches live data from Arcadia using the best available strategy.
    """
    client = ArcadiaClient(router)

    filters = CampaignFilter(
        min_payout=min_payout,
        auto_lock=False,
    )

    campaigns = await client.get_available_campaigns(filters)

    if status:
        target_status = "active" if status == "open" else status
        campaigns = [c for c in campaigns if c.status == target_status]

    return campaigns


@router.get("/monitor")
async def get_monitor_status(
    monitor: CampaignMonitor = Depends(get_campaign_monitor),
):
    """Get the campaign monitor's current state."""
    return monitor.get_status()


@router.post("/monitor/refresh")
async def force_monitor_check(
    monitor: CampaignMonitor = Depends(get_campaign_monitor),
):
    """Force an immediate campaign check."""
    await monitor.check_and_lock()
    return {"status": "check_triggered"}