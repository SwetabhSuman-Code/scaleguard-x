"""
Production validation tests.

These tests are opt-in and only run when a real deployment URL is provided.
They are designed for post-deploy smoke checks rather than local development.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

PRODUCTION_URL = os.getenv("SCALEGUARD_PRODUCTION_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not PRODUCTION_URL,
        reason="Set SCALEGUARD_PRODUCTION_URL to run production smoke tests.",
    ),
]


def _base_url() -> str:
    assert PRODUCTION_URL is not None
    return PRODUCTION_URL.rstrip("/")


def test_production_health() -> None:
    """Production deployment should expose a healthy root control plane."""
    response = httpx.get(f"{_base_url()}/health", timeout=10)
    response.raise_for_status()
    health = response.json()

    assert health["status"] == "healthy"
    assert health["database"] in {"connected", "degraded"}
    assert health["redis"] in {"connected", "degraded"}


def test_can_issue_dev_token() -> None:
    """JWT issuance path should be reachable in the deployed environment."""
    response = httpx.post(
        f"{_base_url()}/api/auth/token",
        json={"username": "deployment-check", "role": "viewer"},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()

    assert "access_token" in payload
    assert payload["role"] == "viewer"


def test_metrics_ingestion_endpoint_accepts_payload() -> None:
    """The deployed ingestion edge should accept the benchmark payload shape."""
    response = httpx.post(
        f"{_base_url()}/api/metrics",
        json={"cpu": 42.0, "memory": 58.0, "latency": 120.0, "rps": 250.0},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()

    assert payload["status"] in {"queued", "stored"}
    assert "trace_id" in payload


def test_manual_scaling_requires_permission() -> None:
    """Manual scale endpoint should reject anonymous callers."""
    response = httpx.post(
        f"{_base_url()}/api/scaling/manual",
        params={"target": 3},
        timeout=10,
    )

    assert response.status_code in {401, 403}


def test_trace_headers_are_returned() -> None:
    """Every production request should return correlation headers."""
    response = httpx.get(f"{_base_url()}/health", timeout=10)
    response.raise_for_status()

    assert response.headers.get("X-Trace-ID")
    assert response.headers.get("X-Request-ID")


def test_repeated_metrics_calls_do_not_degrade_immediately() -> None:
    """Short burst traffic should succeed without immediate endpoint collapse."""
    failures = 0
    for _ in range(50):
        response = httpx.post(
            f"{_base_url()}/api/metrics",
            json={"cpu": 50.0, "memory": 70.0, "latency_ms": 100.0, "rps": 300.0},
            timeout=5,
        )
        if response.status_code >= 500:
            failures += 1
        time.sleep(0.05)

    assert failures == 0
