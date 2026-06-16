"""Dashboard and stats endpoints."""
from fastapi import APIRouter, Depends
from app.config import BotConfig
from app.dependencies import get_config

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/config")
async def get_config_values(
    config: BotConfig = Depends(get_config),
):
    """Get current bot configuration (sensitive values masked)."""
    return {
        "environment": config.environment,
        "poll_interval_seconds": config.poll_interval_seconds,
        "auto_lock_enabled": config.auto_lock_enabled,
        "auto_lock_max_concurrent": config.auto_lock_max_concurrent,
        "strategy_priority": config.strategy_priority,
        "campaign_filter_min_payout": config.campaign_filter_min_payout,
        "campaign_filter_max_slots_per_day": config.campaign_filter_max_slots_per_day,
        "notifications": {
            "telegram": bool(config.telegram_bot_token),
            "discord": bool(config.discord_webhook_url),
        },
        "session_valid": bool(config.arcadia_api_token or config.arcadia_session_cookie),
    }


@router.get("/stats")
async def get_bot_stats():
    """Get runtime statistics."""
    # In production, these would come from persistent storage
    return {
        "uptime_seconds": 0,
        "checks_performed": 0,
        "slots_locked_total": 0,
        "slots_locked_today": 0,
        "api_calls_made": 0,
        "errors_total": 0,
        "strategy_usage": {
            "api": 0,
            "playwright": 0,
            "ai_agent": 0,
        },
    }


@router.post("/pause")
async def pause_bot():
    """Pause all automated operations."""
    # Would set a global pause flag
    return {"status": "paused"}


@router.post("/resume")
async def resume_bot():
    """Resume automated operations."""
    return {"status": "resumed"}