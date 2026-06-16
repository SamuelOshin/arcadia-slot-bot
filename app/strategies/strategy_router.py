"""Strategy Router with circuit breaker and failover logic.

Routes operations through strategies in priority order,
falling back on failure. Integrates with circuit breaker
to avoid hammering failing strategies.
"""
import time
from typing import List, Type, Optional
import structlog
from app.config import settings
from app.models import Campaign, SlotLockResult
from app.core.session_manager import SessionManager
from app.core.circuit_breaker import CircuitBreaker
from app.core.notifier import Notifier
from app.strategies.base import BaseStrategy
from app.strategies.api_strategy import APIStrategy
from app.strategies.playwright_strategy import PlaywrightStrategy
from app.strategies.ai_agent_strategy import AIAgentStrategy

logger = structlog.get_logger()


class StrategyRouter:
    """Orchestrates multi-strategy execution with failover.

    Usage:
        router = StrategyRouter(session_manager, notifier, circuit_breaker)
        campaigns = await router.list_campaigns()
        result = await router.lock_slot(campaign_id)
    """

    STRATEGY_MAP = {
        "api": APIStrategy,
        "playwright": PlaywrightStrategy,
        "ai_agent": AIAgentStrategy,
    }

    def __init__(
        self,
        session_manager: SessionManager,
        notifier: Notifier,
        circuit_breaker: CircuitBreaker,
    ):
        self.session = session_manager
        self.notifier = notifier
        self.circuit_breaker = circuit_breaker
        self._strategies: dict[str, BaseStrategy] = {}
        self._priority = settings.strategy_priority
        self.logger = logger.bind(component="strategy_router")

    def _get_strategy(self, name: str) -> BaseStrategy:
        """Lazy-init a strategy by name."""
        if name not in self._strategies:
            strategy_class = self.STRATEGY_MAP.get(name)
            if not strategy_class:
                raise ValueError(f"Unknown strategy: {name}")
            self._strategies[name] = strategy_class(self.session)
        return self._strategies[name]

    async def list_campaigns(self) -> List[Campaign]:
        """Get campaigns using the first available strategy."""
        for name in self._priority:
            if not await self.circuit_breaker.can_execute(name):
                self.logger.debug("strategy.skipped_circuit_open", strategy=name)
                continue

            strategy = self._get_strategy(name)

            if not await strategy.preflight():
                continue

            try:
                campaigns = await strategy.list_campaigns()
                await self.circuit_breaker.record_success(name)
                self.logger.info("strategy.list_success", strategy=name, count=len(campaigns))
                return campaigns

            except Exception as e:
                self.logger.warning("strategy.list_failed", strategy=name, error=str(e))
                await self.circuit_breaker.record_failure(name)

        self.logger.error("all_strategies_failed", operation="list_campaigns")
        return []

    async def lock_slot(
        self,
        campaign_id: str,
        preferred_strategy: Optional[str] = None,
    ) -> SlotLockResult:
        """Lock a slot, trying strategies in priority order.

        Args:
            campaign_id: Campaign to lock.
            preferred_strategy: Force a specific strategy (for manual overrides).

        Returns:
            SlotLockResult from the first successful strategy,
            or the last failure if all fail.
        """
        strategies_to_try = self._priority.copy()

        # If user specified a strategy, try it first
        if preferred_strategy and preferred_strategy in strategies_to_try:
            strategies_to_try.remove(preferred_strategy)
            strategies_to_try.insert(0, preferred_strategy)

        last_result = None

        for name in strategies_to_try:
            if not await self.circuit_breaker.can_execute(name):
                self.logger.debug("strategy.skipped_circuit_open", strategy=name)
                continue

            strategy = self._get_strategy(name)

            if not await strategy.preflight():
                continue

            start = time.time()

            try:
                result = await strategy.lock_slot(campaign_id)

                if result.success:
                    await self.circuit_breaker.record_success(name)
                    self.logger.info(
                        "strategy.lock_success",
                        strategy=name,
                        campaign=campaign_id,
                        response_ms=result.response_time_ms,
                    )
                    await self.notifier.notify_slot_locked(result)
                    return result
                else:
                    # Non-success but no exception — maybe slot taken
                    last_result = result
                    await self.circuit_breaker.record_failure(name)
                    if getattr(result, "definitive", False):
                        self.logger.info("strategy.definitive_failure_stop", strategy=name, message=result.message)
                        return result

            except Exception as e:
                self.logger.error("strategy.lock_exception", strategy=name, error=str(e))
                await self.circuit_breaker.record_failure(name)
                last_result = SlotLockResult(
                    success=False,
                    campaign_id=campaign_id,
                    campaign_title=campaign_id,
                    message=f"Exception in {name}: {str(e)}",
                    strategy_used=name,
                    response_time_ms=(time.time() - start) * 1000,
                )

        # All strategies failed
        self.logger.error("all_strategies_failed", operation="lock_slot", campaign=campaign_id)

        if last_result:
            await self.notifier.notify_slot_locked(last_result)
            return last_result

        return SlotLockResult(
            success=False,
            campaign_id=campaign_id,
            campaign_title=campaign_id,
            message="All strategies failed to execute",
            strategy_used="none",
            response_time_ms=0,
        )

    async def health_check(self) -> dict:
        """Check health of all strategies."""
        results = {}
        for name in self._priority:
            try:
                strategy = self._get_strategy(name)
                healthy = await strategy.health_check()
                circuit_state = await self.circuit_breaker.get_state(name)
                results[name] = {
                    "healthy": healthy,
                    "circuit_state": circuit_state.value,
                    "session_valid": strategy.session.is_valid,
                }
            except Exception as e:
                results[name] = {
                    "healthy": False,
                    "error": str(e),
                }
        return results

    async def fast_lock(self, campaign_id: str) -> SlotLockResult:
        """Attempt to lock a slot quickly using the API strategy directly."""
        try:
            strategy = self._get_strategy("api")
            return await strategy.fast_lock(campaign_id)
        except Exception as e:
            self.logger.error("strategy.fast_lock_exception", campaign_id=campaign_id, error=str(e))
            return SlotLockResult(
                success=False,
                campaign_id=campaign_id,
                campaign_title=campaign_id,
                message=f"Fast lock exception: {str(e)}",
                strategy_used="api-fast",
                response_time_ms=0,
            )

    async def close_all(self):
        """Clean up all strategy resources."""
        for name, strategy in self._strategies.items():
            try:
                if hasattr(strategy, 'close'):
                    await strategy.close()
            except Exception as e:
                self.logger.warning("strategy.close_failed", strategy=name, error=str(e))