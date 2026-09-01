"""Strategy pattern for multi-layer slot locking.

Priority order (fastest → slowest):
1. API Strategy — Direct HTTP calls (~50ms)
2. AI Agent Strategy — Vision-language model (~10-30s)
"""
from app.strategies.base import BaseStrategy
from app.strategies.api_strategy import APIStrategy
from app.strategies.ai_agent_strategy import AIAgentStrategy
from app.strategies.strategy_router import StrategyRouter

__all__ = [
    "BaseStrategy",
    "APIStrategy",
    "AIAgentStrategy",
    "StrategyRouter",
]