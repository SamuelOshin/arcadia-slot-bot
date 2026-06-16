"""Health check and monitoring endpoints."""
from datetime import datetime
from fastapi import APIRouter, Depends
from app.models import BotHealth
from app.dependencies import get_strategy_router, get_config
from app.strategies.strategy_router import StrategyRouter
from app.config import BotConfig

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=BotHealth)
async def health_check(
    router: StrategyRouter = Depends(get_strategy_router),
    config: BotConfig = Depends(get_config),
):
    """Get comprehensive bot health status."""
    strategy_health = await router.health_check()

    # Determine overall status
    healthy_count = sum(1 for s in strategy_health.values() if s.get("healthy"))
    total = len(strategy_health)

    if healthy_count == total:
        status = "healthy"
    elif healthy_count > 0:
        status = "degraded"
    else:
        status = "unhealthy"

    return BotHealth(
        status=status,
        version="1.0.0",
        strategies=strategy_health,
        campaigns_monitored=0,  # Would be populated from monitor state
        slots_locked_today=0,
        errors_last_hour=0,
    )


@router.get("/ready")
async def readiness_check():
    """Kubernetes-style readiness probe."""
    return {"ready": True}


@router.get("/live")
async def liveness_check():
    """Kubernetes-style liveness probe."""
    return {"alive": True}