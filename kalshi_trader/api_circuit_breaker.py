"""
Circuit Breaker Pattern Implementation

Prevents cascading failures by temporarily blocking requests to
failing services. Transitions through states:
- CLOSED: Normal operation, requests flow through
- OPEN: Service appears down, requests fail fast
- HALF_OPEN: Testing if service recovered

Based on the pattern from Michael Nygard's "Release It!"
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""
    failure_threshold: int = 5          # Failures before opening
    success_threshold: int = 2          # Successes to close from half-open
    timeout_seconds: float = 30.0       # Time in open state before testing
    half_open_max_calls: int = 3        # Max concurrent calls in half-open


@dataclass
class CircuitBreakerStats:
    """Statistics for monitoring circuit breaker behavior."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None


class CircuitBreaker:
    """
    Circuit breaker for protecting against cascading failures.

    Example:
        >>> breaker = CircuitBreaker(name="kalshi_api")
        >>>
        >>> async def make_api_call():
        ...     async with breaker:
        ...         return await api.get_markets()
        >>>
        >>> # Or using the call method:
        >>> result = await breaker.call(api.get_markets)
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Identifier for this breaker (used in logging)
            config: Configuration options
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0

        self._stats = CircuitBreakerStats()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is allowing normal operation."""
        return self._state == CircuitState.CLOSED

    @property
    def stats(self) -> CircuitBreakerStats:
        """Get current statistics."""
        return self._stats

    async def _check_state_transition(self) -> None:
        """Check if state should transition based on current conditions."""
        if self._state == CircuitState.OPEN:
            # Check if timeout has elapsed
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.config.timeout_seconds:
                    await self._transition_to(CircuitState.HALF_OPEN)

    async def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._stats.state_changes += 1

        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0

        logger.info(
            f"Circuit breaker '{self.name}' transitioned: "
            f"{old_state.value} -> {new_state.value}"
        )

    async def _record_success(self) -> None:
        """Record a successful call."""
        self._stats.successful_calls += 1
        self._stats.last_success_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                await self._transition_to(CircuitState.CLOSED)
                self._failure_count = 0

        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            self._failure_count = 0

    async def _record_failure(self, error: Exception) -> None:
        """Record a failed call."""
        self._stats.failed_calls += 1
        self._stats.last_failure_time = time.time()
        self._last_failure_time = time.time()
        self._failure_count += 1

        logger.warning(
            f"Circuit breaker '{self.name}' recorded failure "
            f"({self._failure_count}/{self.config.failure_threshold}): {error}"
        )

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open triggers immediate open
            await self._transition_to(CircuitState.OPEN)

        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                await self._transition_to(CircuitState.OPEN)

    async def _can_execute(self) -> bool:
        """Check if a call can be executed."""
        await self._check_state_transition()

        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            return False

        if self._state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.config.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

        return False

    async def call(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a function through the circuit breaker.

        Args:
            func: Async function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result of func

        Raises:
            CircuitOpenError: If circuit is open
            Exception: Any exception from func
        """
        async with self._lock:
            self._stats.total_calls += 1

            if not await self._can_execute():
                self._stats.rejected_calls += 1
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is open"
                )

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                await self._record_success()
            return result

        except Exception as e:
            async with self._lock:
                await self._record_failure(e)
            raise

    async def check_can_execute(self) -> None:
        """Gate a request WITHOUT recording an outcome.

        Use this (not `async with breaker: pass`) to ask "may I proceed?".
        The context-manager form records a success on clean exit, so an
        empty probe body counted as a real API success and closed the
        breaker after `success_threshold` no-ops — without any actual
        request having been made. Callers must report the real outcome
        afterwards via record_success()/record_failure().

        Raises:
            CircuitOpenError: If the circuit is open.
        """
        async with self._lock:
            self._stats.total_calls += 1
            if not await self._can_execute():
                self._stats.rejected_calls += 1
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is open"
                )

    async def record_success(self) -> None:
        """Record a real request success (lock-guarded public API)."""
        async with self._lock:
            await self._record_success()

    async def record_failure(self, error: Exception) -> None:
        """Record a real request failure (lock-guarded public API)."""
        async with self._lock:
            await self._record_failure(error)

    async def __aenter__(self) -> 'CircuitBreaker':
        """Context manager entry."""
        async with self._lock:
            self._stats.total_calls += 1

            if not await self._can_execute():
                self._stats.rejected_calls += 1
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is open"
                )
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[Exception],
        exc_tb: Any,
    ) -> bool:
        """Context manager exit."""
        async with self._lock:
            if exc_val is None:
                await self._record_success()
            else:
                await self._record_failure(exc_val)
        return False  # Don't suppress exceptions

    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._half_open_calls = 0
        logger.info(f"Circuit breaker '{self.name}' reset to CLOSED")


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and rejecting calls."""
    pass
