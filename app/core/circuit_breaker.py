"""Circuit breaker pattern for strategy failover.

Prevents cascading failures by temporarily disabling a strategy
after repeated failures, then auto-recovering.
"""
import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional
import structlog
from app.config import settings

logger = structlog.get_logger()


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Per-strategy circuit breaker with automatic recovery."""

    def __init__(self):
        self._states: Dict[str, CircuitState] = {}
        self._failure_counts: Dict[str, int] = {}
        self._last_failure_times: Dict[str, datetime] = {}
        self._threshold = settings.circuit_breaker_failure_threshold
        self._recovery_timeout = timedelta(seconds=settings.circuit_breaker_recovery_timeout)
        self._lock = asyncio.Lock()

    async def record_success(self, strategy_name: str) -> None:
        """Record a successful operation."""
        async with self._lock:
            if strategy_name not in self._states:
                self._states[strategy_name] = CircuitState.CLOSED

            if self._states[strategy_name] == CircuitState.HALF_OPEN:
                self._states[strategy_name] = CircuitState.CLOSED
                logger.info("circuit_breaker.closed", strategy=strategy_name)

            self._failure_counts[strategy_name] = 0

    async def record_failure(self, strategy_name: str) -> None:
        """Record a failed operation."""
        async with self._lock:
            if strategy_name not in self._states:
                self._states[strategy_name] = CircuitState.CLOSED

            self._failure_counts[strategy_name] = self._failure_counts.get(strategy_name, 0) + 1
            self._last_failure_times[strategy_name] = datetime.utcnow()

            if (
                self._states[strategy_name] == CircuitState.CLOSED
                and self._failure_counts[strategy_name] >= self._threshold
            ):
                self._states[strategy_name] = CircuitState.OPEN
                logger.warning(
                    "circuit_breaker.opened",
                    strategy=strategy_name,
                    failures=self._failure_counts[strategy_name],
                    recovery_seconds=settings.circuit_breaker_recovery_timeout,
                )

    async def can_execute(self, strategy_name: str) -> bool:
        """Check if a strategy is allowed to execute."""
        async with self._lock:
            state = self._states.get(strategy_name, CircuitState.CLOSED)

            if state == CircuitState.CLOSED:
                return True

            if state == CircuitState.OPEN:
                last_failure = self._last_failure_times.get(strategy_name)
                if last_failure and datetime.utcnow() - last_failure > self._recovery_timeout:
                    self._states[strategy_name] = CircuitState.HALF_OPEN
                    logger.info("circuit_breaker.half_open", strategy=strategy_name)
                    return True
                return False

            if state == CircuitState.HALF_OPEN:
                return True

            return False

    async def get_state(self, strategy_name: str) -> CircuitState:
        """Get current state of a strategy's circuit."""
        async with self._lock:
            return self._states.get(strategy_name, CircuitState.CLOSED)

    def get_all_states(self) -> Dict[str, str]:
        """Get all circuit states as strings."""
        return {k: v.value for k, v in self._states.items()}