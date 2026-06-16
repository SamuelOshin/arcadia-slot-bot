"""FastAPI dependency injection."""
from typing import AsyncGenerator
from fastapi import Request, Depends
from app.config import settings, BotConfig
from app.core.session_manager import SessionManager
from app.core.notifier import Notifier
from app.core.circuit_breaker import CircuitBreaker
from app.strategies.strategy_router import StrategyRouter


async def get_config() -> BotConfig:
    return settings


async def get_session_manager() -> SessionManager:
    return SessionManager()


async def get_notifier() -> Notifier:
    return Notifier()


async def get_circuit_breaker() -> CircuitBreaker:
    return CircuitBreaker()


async def get_strategy_router(
    session_manager: SessionManager = Depends(get_session_manager),
    notifier: Notifier = Depends(get_notifier),
    circuit_breaker: CircuitBreaker = Depends(get_circuit_breaker),
) -> StrategyRouter:
    return StrategyRouter(
        session_manager=session_manager,
        notifier=notifier,
        circuit_breaker=circuit_breaker,
    )


async def get_campaign_monitor(request: Request):
    from app.services.campaign_monitor import CampaignMonitor
    return request.app.state.monitor