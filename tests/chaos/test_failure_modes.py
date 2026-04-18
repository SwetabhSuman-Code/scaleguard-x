"""
Service-level chaos tests.

These checks focus on graceful degradation rules that can be validated without a
full cloud environment. Real container-kill and network-partition drills should
be run against docker-compose or ECS and recorded separately.
"""

from __future__ import annotations

import pytest

from api_gateway.middleware.rate_limiter import (
    RateLimitConfig,
    RateLimitStrategy,
    RateLimiter,
)
from api_gateway.tracing.tracer import RequestTracer, Tracer, TracingConfig
from autoscaler.models.predictive_scaler import PredictiveScaler


@pytest.mark.integration
def test_rate_limiter_blocks_sustained_guest_flood() -> None:
    limiter = RateLimiter(
        RateLimitConfig(
            strategy=RateLimitStrategy.FIXED_WINDOW.value,
            user_rps={"guest": 2.0},
            window_size_seconds=1,
        )
    )

    decisions = [limiter.check_limit("chaos-guest", role="guest")[0] for _ in range(12)]

    assert decisions.count(False) >= 1


@pytest.mark.integration
def test_request_tracer_exports_trace_after_error_path() -> None:
    tracer = Tracer(TracingConfig(service_name="api_gateway", environment="test"))
    request_tracer = RequestTracer(tracer)

    trace_id = request_tracer.start_request_trace("POST", "/api/metrics", {})
    processing_span = tracer.start_span("ingest_metric", {"status": "error"})
    processing_span.status = "ERROR"
    tracer.end_span(processing_span)
    request_tracer.add_response_span(503, 14.1)
    tracer.end_trace()

    exported = tracer.export_trace(trace_id)

    assert exported["trace_id"] == trace_id
    assert exported["span_count"] >= 2


@pytest.mark.integration
def test_predictive_scaler_avoids_unbounded_action_under_noisy_load() -> None:
    scaler = PredictiveScaler()

    actions = []
    for utilization in [71.0, 68.0, 73.0, 69.5, 70.5, 67.8, 72.2, 69.9]:
        scaler.last_scaling_decision_time = 0
        decision = scaler.decide_scaling(utilization, dt=1.0)
        actions.append(decision.action)

    assert max(abs(action) for action in actions) <= scaler.config.max_scaling_action
