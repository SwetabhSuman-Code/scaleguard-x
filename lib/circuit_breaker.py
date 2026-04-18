"""
ScaleGuard X — Circuit Breaker
Implements the Circuit Breaker pattern to prevent cascading failures.

States:
  CLOSED    — Normal operation; failures are counted.
  OPEN      — Requests are short-circuited; fast-fail for recovery_timeout seconds.
  HALF_OPEN — One test request allowed; if it succeeds, close the circuit.

Usage:
    cb = CircuitBreaker("postgres", failure_threshold=5, recovery_timeout=60)

    async with cb:
        result = await some_db_call()

    # Or for sync code:
    with cb:
        result = some_call()
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from enum import Enum
from typing import Any, Callable, Optional, Type

log = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""

    def __init__(self, name: str, reset_at: float) -> None:
        self.name = name
        self.reset_at = reset_at
        remaining = max(0.0, reset_at - time.monotonic())
        super().__init__(
            f"Circuit '{name}' is OPEN — retry in {remaining:.1f}s"
        )


class CircuitBreaker:
    """
    Thread-safe (asyncio-compatible) circuit breaker.

    Parameters
    ----------
    name:               Friendly name used in logs and errors.
    failure_threshold:  Number of consecutive failures before opening the circuit.
    recovery_timeout:   Seconds to wait in OPEN state before trying HALF_OPEN.
    expected_exception: Which exception type(s) count as failures.
                        Defaults to ``Exception`` (everything).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: Type[BaseException] | tuple[Type[BaseException], ...] = Exception,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    # ── State properties ─────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    # ── State transitions ─────────────────────────────────────────

    def _trip(self) -> None:
        """Transition CLOSED/HALF_OPEN → OPEN."""
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        log.warning(
            "circuit_breaker state=OPEN name=%s failures=%d recovery_in=%.0fs",
            self.name, self._failure_count, self.recovery_timeout,
        )

    def _reset(self) -> None:
        """Transition any state → CLOSED."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None
        log.info("circuit_breaker state=CLOSED name=%s (recovered)", self.name)

    def _allow_request(self) -> bool:
        """Return True if the call should be allowed through."""
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            assert self._opened_at is not None
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                log.info(
                    "circuit_breaker state=HALF_OPEN name=%s (probing)", self.name
                )
                return True
            return False

        # HALF_OPEN: only one probe allowed at a time (lock handled externally)
        return True

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._reset()
        else:
            self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        if self._state == CircuitState.HALF_OPEN or (
            self._failure_count >= self.failure_threshold
        ):
            self._trip()

    # ── Async context manager ─────────────────────────────────────

    async def __aenter__(self) -> "CircuitBreaker":
        async with self._lock:
            if not self._allow_request():
                assert self._opened_at is not None
                raise CircuitBreakerError(
                    self.name, self._opened_at + self.recovery_timeout
                )
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Any,
    ) -> bool:
        async with self._lock:
            if exc_type is None:
                self._on_success()
            elif issubclass(exc_type, self.expected_exception):
                self._on_failure()
                # Re-raise the original exception (not CircuitBreakerError)
        return False  # never suppress

    # ── Sync context manager ──────────────────────────────────────

    def __enter__(self) -> "CircuitBreaker":
        if not self._allow_request():
            assert self._opened_at is not None
            raise CircuitBreakerError(
                self.name, self._opened_at + self.recovery_timeout
            )
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Any,
    ) -> bool:
        if exc_type is None:
            self._on_success()
        elif issubclass(exc_type, self.expected_exception):
            self._on_failure()
        return False

    # ── Decorator ─────────────────────────────────────────────────

    def __call__(self, func: Callable) -> Callable:
        """Use as a decorator: @circuit_breaker"""
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                async with self:
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with self:
                    return func(*args, **kwargs)
            return sync_wrapper

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(name={self.name!r}, state={self._state.value}, "
            f"failures={self._failure_count}/{self.failure_threshold})"
        )


# ── Pre-built breakers for shared services ────────────────────────
# Each service imports these directly rather than creating their own.

def make_postgres_breaker(service_name: str) -> CircuitBreaker:
    """Standard circuit breaker for PostgreSQL connections."""
    return CircuitBreaker(
        name=f"{service_name}.postgres",
        failure_threshold=5,
        recovery_timeout=60.0,
        expected_exception=Exception,
    )


def make_redis_breaker(service_name: str) -> CircuitBreaker:
    """Standard circuit breaker for Redis connections."""
    return CircuitBreaker(
        name=f"{service_name}.redis",
        failure_threshold=5,
        recovery_timeout=30.0,
        expected_exception=Exception,
    )


def make_docker_breaker(service_name: str) -> CircuitBreaker:
    """Standard circuit breaker for Docker API calls."""
    return CircuitBreaker(
        name=f"{service_name}.docker",
        failure_threshold=3,
        recovery_timeout=30.0,
        expected_exception=Exception,
    )


def make_http_breaker(service_name: str) -> CircuitBreaker:
    """Standard circuit breaker for outbound HTTP calls."""
    return CircuitBreaker(
        name=f"{service_name}.http",
        failure_threshold=5,
        recovery_timeout=45.0,
        expected_exception=Exception,
    )
