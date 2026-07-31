"""Dashboard and stats endpoints."""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Request, HTTPException
from app.config import BotConfig, settings
from app.dependencies import get_config

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_is_paused = False


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
        "is_paused": _is_paused,
        "notifications": {
            "telegram": bool(config.telegram_bot_token),
            "discord": bool(config.discord_webhook_url),
        },
        "accounts_count": len(config.accounts),
    }


@router.get("/accounts")
async def get_accounts_status(request: Request):
    """Get status and details for all configured accounts."""
    monitors = getattr(request.app.state, "monitors", [])
    account_list = []

    for idx, monitor in enumerate(monitors):
        st = monitor.get_status()
        daily_count = getattr(monitor.client, "_slots_locked_today", 0)
        max_quota = getattr(monitor.account, "max_slots_per_day", settings.campaign_filter_max_slots_per_day)
        tracked_campaigns = len(getattr(monitor, "_known_campaigns", set()))

        account_list.append({
            "index": idx,
            "name": monitor.account.name,
            "label": monitor.account_label,
            "is_valid": monitor.session.is_valid,
            "has_token": bool(monitor.session.get_session_token()),
            "daily_count": daily_count,
            "max_slots_per_day": max_quota,
            "last_check": st.get("last_check"),
            "tracked_campaigns": tracked_campaigns,
        })
    return {"accounts": account_list}


@router.post("/accounts/{index}/refresh")
async def refresh_account_session(index: int, request: Request):
    """Trigger session refresh for a specific account."""
    monitors = getattr(request.app.state, "monitors", [])
    if index < 0 or index >= len(monitors):
        raise HTTPException(status_code=404, detail="Account index out of bounds")

    monitor = monitors[index]
    success = await monitor.session.refresh()
    return {
        "account": monitor.account.name,
        "success": success,
        "is_valid": monitor.session.is_valid,
    }


@router.get("/stats")
async def get_bot_stats(request: Request):
    """Get aggregated runtime statistics across accounts."""
    monitors = getattr(request.app.state, "monitors", [])

    total_locked_today = sum(getattr(m.client, "_slots_locked_today", 0) for m in monitors)
    active_accounts = sum(1 for m in monitors if m.session.is_valid)

    return {
        "total_accounts": len(monitors),
        "active_accounts": active_accounts,
        "slots_locked_today": total_locked_today,
        "is_paused": _is_paused,
        "auto_lock_enabled": settings.auto_lock_enabled,
        "poll_interval": settings.poll_interval_seconds,
    }


@router.post("/pause")
async def pause_bot(request: Request):
    """Pause all automated operations."""
    global _is_paused
    _is_paused = True
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.pause()
    return {"status": "paused", "is_paused": True}


@router.post("/resume")
async def resume_bot(request: Request):
    """Resume automated operations."""
    global _is_paused
    _is_paused = False
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler:
        scheduler.resume()
    return {"status": "resumed", "is_paused": False}