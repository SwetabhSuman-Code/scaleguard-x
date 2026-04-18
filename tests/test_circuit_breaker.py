"""
ScaleGuard X — Unit Tests: Circuit Breaker
"""
from __future__ import annotations

import asyncio
import time

import pytest

from lib.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
    make_postgres_breaker,
    make_redis_breaker,
)


# ── Sync circuit breaker tests ────────────────────────────────────

class TestCircuitBreakerSync:
    def test_initial_state_is_closed(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed

    def test_allows_calls_when_closed(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        with cb:
            pass  # should not raise

    def test_counts_failures(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("boom")
            except ValueError:
                pass
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 2

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            try:
                with cb:
                    raise ValueError("boom")
            except ValueError:
                pass
        assert cb.state == CircuitState.OPEN

    def test_open_raises_circuit_error(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)
        try:
            with cb:
                raise ValueError("trip")
        except ValueError:
            pass
        with pytest.raises(CircuitBreakerError):
            with cb:
                pass

    def test_transitions_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        try:
            with cb:
                raise ValueError("trip")
        except ValueError:
            pass
        time.sleep(0.1)
        # After recovery_timeout, should allow ONE probe through
        with cb:
            pass  # success → resets to CLOSED
        assert cb.state == CircuitState.CLOSED

    def test_resets_on_success_in_half_open(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        try:
            with cb:
                raise ValueError("trip")
        except ValueError:
            pass
        time.sleep(0.1)
        with cb:
            pass
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_repr(self) -> None:
        cb = CircuitBreaker("my_cb", failure_threshold=5, recovery_timeout=30)
        r  = repr(cb)
        assert "my_cb" in r
        assert "CLOSED" in r


# ── Async circuit breaker tests ───────────────────────────────────

@pytest.mark.unit
class TestCircuitBreakerAsync:
    @pytest.mark.asyncio
    async def test_async_allows_calls(self) -> None:
        cb = CircuitBreaker("async_test", failure_threshold=3, recovery_timeout=60)
        async with cb:
            pass

    @pytest.mark.asyncio
    async def test_async_opens_on_failures(self) -> None:
        cb = CircuitBreaker("async_test", failure_threshold=2, recovery_timeout=60)
        for _ in range(2):
            try:
                async with cb:
                    raise RuntimeError("fail")
            except RuntimeError:
                pass
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_async_raises_circuit_error_when_open(self) -> None:
        cb = CircuitBreaker("async_test", failure_threshold=1, recovery_timeout=60)
        try:
            async with cb:
                raise RuntimeError("trip")
        except RuntimeError:
            pass
        with pytest.raises(CircuitBreakerError) as exc_info:
            async with cb:
                pass
        assert "OPEN" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_recovers_after_timeout(self) -> None:
        cb = CircuitBreaker("async_test", failure_threshold=1, recovery_timeout=0.05)
        try:
            async with cb:
                raise RuntimeError("trip")
        except RuntimeError:
            pass
        await asyncio.sleep(0.1)
        async with cb:
            pass
        assert cb.state == CircuitState.CLOSED


# ── Factory functions ─────────────────────────────────────────────

class TestFactoryFunctions:
    def test_postgres_breaker(self) -> None:
        cb = make_postgres_breaker("my_service")
        assert cb.name == "my_service.postgres"
        assert cb.failure_threshold == 5

    def test_redis_breaker(self) -> None:
        cb = make_redis_breaker("my_service")
        assert cb.name == "my_service.redis"
        assert cb.recovery_timeout == 30.0
