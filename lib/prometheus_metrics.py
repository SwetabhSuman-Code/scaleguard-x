"""
ScaleGuard X — Prometheus Metrics
Provides metrics collection and export for all services.

Define metrics once, use everywhere:
    from lib.prometheus_metrics import metrics
    
    metrics.ingestion_count.inc()
    metrics.db_query_duration.observe(0.123)
    metrics.autoscaler_workers.set(5)

Call at startup:
    from lib.prometheus_metrics import setup_metrics_server
    setup_metrics_server(port=9090)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)
from prometheus_client.core import REGISTRY

log = logging.getLogger(__name__)


class MetricsRegistry:
    """
    Central registry of all ScaleGuard X metrics.
    Designed for multi-service use; service-specific metrics are labeled.
    """

    def __init__(self, service_name: str | None = None):
        self.service_name = service_name or "unknown"

        # ── Ingestion Metrics ────────────────────────────────────
        self.metrics_received_total = Counter(
            "scaleguard_metrics_received_total",
            "Total metrics received from agents",
            ["source_node"],
        )

        self.metrics_ingested_total = Counter(
            "scaleguard_metrics_ingested_total",
            "Total metrics written to database",
            ["service"],
        )

        self.ingestion_latency_seconds = Histogram(
            "scaleguard_ingestion_latency_seconds",
            "Time to ingest metrics batch to database",
            ["service"],
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
        )

        # ── Database Metrics ─────────────────────────────────────
        self.db_query_duration_seconds = Histogram(
            "scaleguard_db_query_duration_seconds",
            "Database query latency",
            ["service"],
            buckets=(0.001, 0.01, 0.05, 0.1, 0.5, 1.0),
        )

        self.db_pool_connections = Gauge(
            "scaleguard_db_pool_connections",
            "Current database pool connections",
            ["service"],
        )

        self.db_pool_size = Gauge(
            "scaleguard_db_pool_size",
            "Configured database pool size",
            ["service"],
        )

        # ── Anomaly Detection ────────────────────────────────────
        self.anomalies_detected_total = Counter(
            "scaleguard_anomalies_detected_total",
            "Total anomalies detected",
            [
                "anomaly_type",
                "metric_name",
            ],  # "rule_based"/"ml_based", "cpu"/"memory"/etc
        )

        self.anomaly_detection_duration_seconds = Histogram(
            "scaleguard_anomaly_detection_duration_seconds",
            "Time to run anomaly detection cycle",
            ["anomaly_type"],
            buckets=(0.1, 0.5, 1.0, 2.0, 5.0),
        )

        # ── Prediction Engine ────────────────────────────────────
        self.predictions_generated_total = Counter(
            "scaleguard_predictions_generated_total",
            "Total predictions generated",
            ["horizon_minutes"],
        )

        self.prediction_error_mape = Gauge(
            "scaleguard_prediction_error_mape",
            "Mean Absolute Percentage Error (MAPE) of last prediction",
            ["horizon_minutes"],
        )

        # ── Autoscaling ──────────────────────────────────────────
        self.scaling_decisions_total = Counter(
            "scaleguard_scaling_decisions_total",
            "Total scaling decisions made",
            ["action"],  # "scale_up", "scale_down", "no_change"
        )

        self.worker_count = Gauge(
            "scaleguard_worker_count",
            "Current number of active workers",
        )

        self.worker_count_target = Gauge(
            "scaleguard_worker_count_target",
            "Target number of workers (from scaling decision)",
        )

        self.scaling_decision_duration_seconds = Histogram(
            "scaleguard_scaling_decision_duration_seconds",
            "Time to make scaling decision",
            buckets=(0.01, 0.1, 0.5, 1.0, 2.0),
        )

        # ── API Gateway ──────────────────────────────────────────
        self.http_requests_total = Counter(
            "scaleguard_http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status"],
        )

        self.http_request_duration_seconds = Histogram(
            "scaleguard_http_request_duration_seconds",
            "HTTP request latency",
            ["method", "endpoint"],
            buckets=(0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
        )

        # ── Redis ────────────────────────────────────────────────
        self.redis_operations_total = Counter(
            "scaleguard_redis_operations_total",
            "Total Redis operations",
            ["operation", "status"],  # "xadd", "xread", "get", etc
        )

        self.redis_operation_duration_seconds = Histogram(
            "scaleguard_redis_operation_duration_seconds",
            "Redis operation latency",
            ["operation"],
            buckets=(0.001, 0.01, 0.05, 0.1),
        )

        # ── Circuit Breaker ──────────────────────────────────────
        self.circuit_breaker_state = Gauge(
            "scaleguard_circuit_breaker_state",
            "Circuit breaker state (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
            ["name"],
        )

        self.circuit_breaker_failures_total = Counter(
            "scaleguard_circuit_breaker_failures_total",
            "Total failures tracked by circuit breaker",
            ["name"],
        )

        # ── Errors & Exceptions ──────────────────────────────────
        self.exceptions_total = Counter(
            "scaleguard_exceptions_total",
            "Total unhandled exceptions",
            ["exception_type", "service"],
        )

        self.service_health = Gauge(
            "scaleguard_service_health",
            "Service health status (1=healthy, 0=degraded)",
            ["service"],
        )


# Global metrics instance
_metrics: Optional[MetricsRegistry] = None


def get_metrics() -> MetricsRegistry:
    """Retrieve the global metrics registry."""
    global _metrics
    if _metrics is None:
        raise RuntimeError("Metrics not initialized. Call setup_metrics() first.")
    return _metrics


def setup_metrics(service_name: str) -> MetricsRegistry:
    """Initialize the global metrics registry."""
    global _metrics
    _metrics = MetricsRegistry(service_name)
    log.info(f"Metrics initialized for service: {service_name}")
    return _metrics


def setup_metrics_server(port: int = 9090) -> None:
    """
    Start Prometheus metrics HTTP server on the specified port.
    Call once per service at startup.
    """
    try:
        start_http_server(port)
        log.info(f"Prometheus metrics server started on port {port}")
    except OSError as e:
        log.error(f"Failed to start metrics server on port {port}: {e}")
        log.warning("Metrics disabled; continuing without Prometheus export")


@asynccontextmanager
async def metrics_timer(metric_histogram, service_name: str | None = None):
    """
    Async context manager to time a block of code and record to a histogram.

    Usage:
        async with metrics_timer(metrics.db_query_duration_seconds, "api_gateway"):
            await db.fetch(...)
    """
    import time

    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        try:
            labels = {"service": service_name} if service_name else {}
            if labels:
                metric_histogram.labels(**labels).observe(elapsed)
            else:
                metric_histogram.observe(elapsed)
        except Exception as e:
            log.error(f"Failed to record metric: {e}")


# Helper: sync version for non-async code
def record_metric(metric, value: float, labels: dict | None = None) -> None:
    """Record a metric value with optional labels."""
    try:
        if labels:
            (
                metric.labels(**labels).set(value)
                if hasattr(metric, "set")
                else metric.labels(**labels).observe(value)
            )
        else:
            metric.set(value) if hasattr(metric, "set") else metric.observe(value)
    except Exception as e:
        log.error(f"Failed to record metric: {e}")
