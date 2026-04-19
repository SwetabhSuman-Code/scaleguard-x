"""
Unit tests for rate limiting and distributed tracing.

Tests cover:
1. Token bucket rate limiting
2. Sliding window rate limiting
3. Fixed window rate limiting
4. Role-based rate limits
5. Distributed trace creation and propagation
6. Span lifecycle and attributes
7. Context propagation across services
"""

import pytest
import time
from unittest.mock import Mock, patch

from api_gateway.middleware.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RateLimitStrategy,
    TokenBucket,
    SlidingWindowCounter,
    FixedWindowCounter,
)
from api_gateway.tracing.tracer import Tracer, TracingConfig, Span, RequestTracer


class TestTokenBucket:
    """Test token bucket algorithm."""

    def test_token_bucket_initialization(self):
        """Token bucket starts with full capacity."""
        bucket = TokenBucket(capacity=10, refill_rate=1)
        assert bucket.tokens == 10
        assert bucket.capacity == 10

    def test_basic_request_allowed(self):
        """Request allowed when tokens available."""
        bucket = TokenBucket(capacity=10, refill_rate=1)
        assert bucket.allow_request(1) is True

    def test_request_denied_when_empty(self):
        """Request denied when out of tokens."""
        bucket = TokenBucket(capacity=1, refill_rate=1)
        bucket.tokens = 0

        assert bucket.allow_request(1) is False

    def test_token_refill(self):
        """Tokens refill over time."""
        bucket = TokenBucket(capacity=10, refill_rate=10)  # 10 tokens/sec
        bucket.tokens = 0

        time.sleep(0.2)  # Wait 0.2 seconds

        # Should have ~2 tokens after refill
        assert bucket.allow_request(1) is True

    def test_capacity_limit(self):
        """Tokens capped at capacity."""
        bucket = TokenBucket(capacity=5, refill_rate=10)
        bucket.tokens = 0

        time.sleep(1)  # Wait for refill

        # Should not exceed capacity
        assert bucket.tokens <= 5

    def test_multi_token_request(self):
        """Request multiple tokens at once."""
        bucket = TokenBucket(capacity=10, refill_rate=1)
        assert bucket.allow_request(5) is True
        assert bucket.tokens == 5

    def test_reset_after_time(self):
        """Get time until next token available."""
        bucket = TokenBucket(capacity=1, refill_rate=1)
        bucket.tokens = 0

        reset_time = bucket.get_reset_after()
        assert 0.9 < reset_time < 1.1  # Should be ~1 second


class TestSlidingWindow:
    """Test sliding window counter."""

    def test_sliding_window_initialization(self):
        """Window initializes empty."""
        window = SlidingWindowCounter(window_size=60)
        assert len(window.requests) == 0

    def test_request_allowed_within_limit(self):
        """Request allowed while under limit."""
        window = SlidingWindowCounter(window_size=60)
        assert window.allow_request(limit=5) is True
        assert len(window.requests) == 1

    def test_request_denied_exceeding_limit(self):
        """Request denied when exceeding limit."""
        window = SlidingWindowCounter(window_size=60)

        for _ in range(5):
            window.allow_request(limit=5)

        assert window.allow_request(limit=5) is False

    def test_old_requests_removed(self):
        """Requests outside window removed."""
        window = SlidingWindowCounter(window_size=0.1)  # 100ms window

        window.allow_request(limit=100)
        time.sleep(0.15)

        # Old request should be removed, new one allowed
        assert len(window.requests) == 1
        assert window.allow_request(limit=1) is True


class TestFixedWindow:
    """Test fixed window counter."""

    def test_fixed_window_initialization(self):
        """Window initializes with zero count."""
        window = FixedWindowCounter(window_seconds=60)
        assert window.count == 0

    def test_request_allowed_within_limit(self):
        """Request allowed while under limit."""
        window = FixedWindowCounter(window_seconds=60)
        assert window.allow_request(limit=5) is True

    def test_request_denied_exceeding_limit(self):
        """Request denied when exceeding limit."""
        window = FixedWindowCounter(window_seconds=60)

        for _ in range(5):
            window.allow_request(limit=5)

        assert window.allow_request(limit=5) is False

    def test_window_reset(self):
        """Counter resets on new window."""
        window = FixedWindowCounter(window_seconds=1)

        window.allow_request(limit=5)
        assert window.count == 1

        # Simulate window change
        window.window_start = int(time.time() / 1) * 1 - 1

        result = window.allow_request(limit=5)
        assert result is True
        assert window.count == 1  # Reset


class TestRateLimiterInitialization:
    """Test rate limiter setup."""

    def test_default_initialization(self):
        """Initializes with sensible defaults."""
        limiter = RateLimiter()
        assert limiter.strategy == RateLimitStrategy.TOKEN_BUCKET.value

    def test_custom_configuration(self):
        """Accepts custom configuration."""
        config = RateLimitConfig(strategy=RateLimitStrategy.SLIDING_WINDOW.value, global_rps=500.0)
        limiter = RateLimiter(config)
        assert limiter.strategy == RateLimitStrategy.SLIDING_WINDOW.value

    def test_default_role_limits(self):
        """Default config has role-based limits."""
        limiter = RateLimiter()
        assert limiter.config.user_rps["admin"] > limiter.config.user_rps["guest"]


class TestRateLimiterTokenBucket:
    """Test rate limiting with token bucket strategy."""

    def test_check_limit_allowed(self):
        """Request allowed within limit."""
        limiter = RateLimiter(RateLimitConfig(strategy=RateLimitStrategy.TOKEN_BUCKET.value))

        allowed, metadata = limiter.check_limit("user1", role="operator")
        assert allowed is True
        assert metadata["remaining"] >= 0

    def test_check_limit_denied(self):
        """Request denied when tokens exhausted."""
        limiter = RateLimiter(
            RateLimitConfig(
                strategy=RateLimitStrategy.TOKEN_BUCKET.value,
                bucket_capacity=1.0,
                refill_rate=0.1,  # Very slow refill
            )
        )

        # Exhaust tokens
        for _ in range(10):
            limiter.check_limit("attacker", role="guest")

        # Next request should be denied
        allowed, _ = limiter.check_limit("attacker", role="guest")
        assert not allowed

    def test_role_based_limits(self):
        """Different roles get different limits."""
        limiter = RateLimiter()

        # Admin has high limit
        admin_result = limiter.check_limit("user1", role="admin")
        # Guest has low limit
        guest_result = limiter.check_limit("user2", role="guest")

        assert admin_result[1]["limit"] > guest_result[1]["limit"]

    def test_reset_after_time(self):
        """Metadata includes reset time."""
        limiter = RateLimiter()

        allowed, metadata = limiter.check_limit("user1")
        assert "reset_after" in metadata
        assert metadata["reset_after"] >= 0


class TestRateLimiterSlidingWindow:
    """Test rate limiting with sliding window."""

    def test_sliding_window_strategy(self):
        """Sliding window counts requests correctly."""
        limiter = RateLimiter(
            RateLimitConfig(strategy=RateLimitStrategy.SLIDING_WINDOW.value, window_size_seconds=1)
        )

        # Make requests within limit
        for i in range(5):
            allowed, _ = limiter.check_limit(f"user", role="operator")
            assert allowed

    def test_window_expiration(self):
        """Requests outside window don't count."""
        config = RateLimitConfig(
            strategy=RateLimitStrategy.SLIDING_WINDOW.value, window_size_seconds=0.1
        )
        limiter = RateLimiter(config)

        # Make request
        limiter.check_limit("user", role="operator")

        # Wait for window to age
        time.sleep(0.15)

        # New request should be allowed (old one aged out)
        allowed, metadata = limiter.check_limit("user", role="operator")
        assert allowed


class TestRateLimiterFixedWindow:
    """Test rate limiting with fixed window."""

    def test_fixed_window_strategy(self):
        """Fixed window counts requests."""
        limiter = RateLimiter(RateLimitConfig(strategy=RateLimitStrategy.FIXED_WINDOW.value))

        allowed, _ = limiter.check_limit("user", role="operator")
        assert allowed

    def test_fixed_window_reset(self):
        """Requests reset on window boundary."""
        limiter = RateLimiter(
            RateLimitConfig(strategy=RateLimitStrategy.FIXED_WINDOW.value, window_size_seconds=1)
        )

        allowed1, _ = limiter.check_limit("user")
        time.sleep(1.1)
        allowed2, _ = limiter.check_limit("user")

        assert allowed1 and allowed2


class TestRateLimiterReset:
    """Test rate limit reset functionality."""

    def test_reset_identifier(self):
        """Reset clears rate limit for identifier."""
        limiter = RateLimiter()

        # Make some requests
        for _ in range(5):
            limiter.check_limit("user1")

        # Reset
        limiter.reset_identifier("user1")

        # Should be fresh
        allowed, metadata = limiter.check_limit("user1")
        assert allowed


class TestRateLimiterStats:
    """Test rate limiter statistics."""

    def test_get_stats(self):
        """Get rate limiter stats."""
        limiter = RateLimiter()

        # Make some requests to track identifiers
        for i in range(3):
            limiter.check_limit(f"user{i}")

        stats = limiter.get_stats()
        assert "strategy" in stats
        assert "tracked_identifiers" in stats


class TestSpanCreation:
    """Test distributed span creation."""

    def test_span_initialization(self):
        """Span initializes with metadata."""
        span = Span(
            name="test_op",
            trace_id="trace123",
            span_id="span456",
            start_time=time.time(),
        )

        assert span.name == "test_op"
        assert span.trace_id == "trace123"
        assert span.status == "OK"

    def test_span_duration(self):
        """Span calculates duration."""
        start = time.time()
        span = Span(name="test_op", trace_id="trace123", span_id="span456", start_time=start)

        time.sleep(0.1)
        span.end()

        assert 90 < span.duration_ms < 110  # ~100ms

    def test_span_attributes(self):
        """Span stores attributes."""
        span = Span(
            name="test_op",
            trace_id="trace123",
            span_id="span456",
            start_time=time.time(),
        )

        span.set_attribute("user_id", "user123")
        span.set_attribute("status", "success")

        assert span.attributes["user_id"] == "user123"
        assert span.attributes["status"] == "success"

    def test_span_events(self):
        """Span records events."""
        span = Span(
            name="test_op",
            trace_id="trace123",
            span_id="span456",
            start_time=time.time(),
        )

        span.add_event("checkpoint_1", {"progress": 50})
        span.add_event("checkpoint_2", {"progress": 100})

        assert len(span.events) == 2
        assert span.events[0]["name"] == "checkpoint_1"


class TestTracerInitialization:
    """Test tracer setup."""

    def test_tracer_initialization(self):
        """Tracer initializes with config."""
        config = TracingConfig(service_name="test-service")
        tracer = Tracer(config)

        assert tracer.config.service_name == "test-service"

    def test_disabled_tracing(self):
        """Tracer can be disabled."""
        config = TracingConfig(enabled=False)
        tracer = Tracer(config)

        trace_id = tracer.start_trace()
        assert trace_id == ""


class TestTracerTraces:
    """Test trace lifecycle."""

    def test_start_and_end_trace(self):
        """Start and end traces."""
        tracer = Tracer()

        trace_id = tracer.start_trace()
        assert trace_id != ""

        tracer.end_trace()
        assert tracer.get_current_trace_id() is None

    def test_multiple_spans_in_trace(self):
        """Trace can contain multiple spans."""
        tracer = Tracer()
        tracer.start_trace()

        span1 = tracer.start_span("operation_1")
        span1.end()

        span2 = tracer.start_span("operation_2")
        span2.end()

        tracer.end_trace()

        # Both spans created
        assert span1.name == "operation_1"
        assert span2.name == "operation_2"

    def test_nested_spans(self):
        """Spans can be nested."""
        tracer = Tracer()
        trace_id = tracer.start_trace()

        parent = tracer.start_span("parent")
        child = tracer.start_span("child")
        child.end()
        parent.end()

        tracer.end_trace()

        # Child should have parent ID
        assert child.parent_span_id == parent.span_id

    def test_trace_context_manager(self):
        """Context manager for automatic span lifecycle."""
        tracer = Tracer()
        tracer.start_trace()

        try:
            with tracer.trace_context("operation") as span:
                span.set_attribute("status", "running")
                time.sleep(0.05)

            # Span should be ended
            assert span.end_time is not None
            assert span.status == "OK"
        finally:
            tracer.end_trace()

    def test_trace_context_error_handling(self):
        """Context manager marks errors in spans."""
        tracer = Tracer()
        tracer.start_trace()

        try:
            with tracer.trace_context("operation") as span:
                raise ValueError("Test error")
        except ValueError:
            pass
        finally:
            tracer.end_trace()

        # Span should be marked with error
        assert span.status == "ERROR"
        assert span.error is not None


class TestTracerExport:
    """Test trace export."""

    def test_export_trace(self):
        """Export trace to external format."""
        tracer = Tracer()
        trace_id = tracer.start_trace()

        span = tracer.start_span("operation")
        span.set_attribute("key", "value")
        span.end()

        tracer.end_trace()

        exported = tracer.export_trace(trace_id)

        assert exported["trace_id"] == trace_id
        assert "spans" in exported
        assert len(exported["spans"]) > 0


class TestRequestTracer:
    """Test HTTP request tracing."""

    def test_extract_trace_context(self):
        """Extract trace ID from headers."""
        tracer = Tracer()
        req_tracer = RequestTracer(tracer)

        headers = {"traceparent": "00-abc123xyz-def456-01"}
        trace_id = req_tracer.extract_trace_context(headers)

        assert trace_id != ""

    def test_extract_custom_trace_id(self):
        """Extract custom trace ID header."""
        tracer = Tracer()
        req_tracer = RequestTracer(tracer)

        headers = {"x-trace-id": "custom-123"}
        trace_id = req_tracer.extract_trace_context(headers)

        assert trace_id == "custom-123"

    def test_generate_missing_trace_id(self):
        """Generate new trace ID if not in headers."""
        tracer = Tracer()
        req_tracer = RequestTracer(tracer)

        headers = {}
        trace_id = req_tracer.extract_trace_context(headers)

        assert trace_id != ""
        assert len(trace_id) > 10

    def test_start_request_trace(self):
        """Start trace for HTTP request."""
        tracer = Tracer()
        req_tracer = RequestTracer(tracer)

        trace_id = req_tracer.start_request_trace(method="GET", path="/api/metrics", headers={})

        assert trace_id != ""


class TestTracerStatistics:
    """Test tracer statistics."""

    def test_get_stats(self):
        """Get tracer statistics."""
        tracer = Tracer()

        tracer.start_trace()
        tracer.start_span("op1").end()
        tracer.end_trace()

        stats = tracer.get_stats()

        assert "enabled" in stats
        assert "active_spans" in stats
        assert "service" in stats
