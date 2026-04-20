"""
Throughput benchmarks: how many metrics/second can the system handle?

These tests use the bulk ingestion endpoint when the batch size is greater than
one so we can measure metrics/sec instead of request/sec.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Dict, List

import httpx
import numpy as np
import pytest


logger = logging.getLogger(__name__)


def _benchmark_duration(default: int) -> int:
    return int(os.getenv("BENCHMARK_DURATION_SECONDS", str(default)))


def _benchmark_concurrency(default: int) -> int:
    return int(os.getenv("THROUGHPUT_CONCURRENCY", str(default)))


def _benchmark_batch_size(default: int = 20) -> int:
    return max(1, int(os.getenv("THROUGHPUT_BATCH_SIZE", str(default))))


class ThroughputBenchmark:
    """Measures sustained metrics throughput under load."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or os.getenv("BENCHMARK_TARGET_URL", "http://localhost:8000")
        self.metrics_sent = 0
        self.metrics_failed = 0
        self.requests_sent = 0
        self.requests_failed = 0
        self.start_time: float | None = None
        self.end_time: float | None = None
        self.latencies: List[float] = []
        self.errors: List[str] = []

    async def run_throughput_test(
        self,
        target_rps: int = 5_000,
        duration_seconds: int = 60,
        concurrent_requests: int = 20,
        metric_batch_size: int | None = None,
    ) -> Dict:
        """
        Run sustained throughput test.

        Args:
            target_rps: Target metrics per second
            duration_seconds: Test duration
            concurrent_requests: Max in-flight HTTP requests
            metric_batch_size: Metrics per request. Uses /api/metrics/bulk when > 1.
        """
        self.start_time = time.time()
        self.metrics_sent = 0
        self.metrics_failed = 0
        self.requests_sent = 0
        self.requests_failed = 0
        self.latencies = []
        self.errors = []

        batch_size = metric_batch_size or _benchmark_batch_size()
        total_target_metrics = target_rps * duration_seconds
        total_requests = math.ceil(total_target_metrics / batch_size)
        request_rps = max(1, math.ceil(target_rps / batch_size))
        request_interval = 1.0 / request_rps

        async with httpx.AsyncClient(
            base_url=self.base_url,
            limits=httpx.Limits(
                max_connections=concurrent_requests,
                max_keepalive_connections=concurrent_requests,
            ),
            timeout=10.0,
        ) as client:
            pending: set[asyncio.Task[None]] = set()

            for request_num in range(total_requests):
                scheduled_time = self.start_time + (request_num * request_interval)
                sleep_for = scheduled_time - time.time()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)

                remaining_metrics = total_target_metrics - (request_num * batch_size)
                current_batch_size = min(batch_size, remaining_metrics)
                if current_batch_size <= 0:
                    break

                metrics = [
                    {
                        "node_id": f"node-{(request_num + metric_num) % 10}",
                        "cpu": 45.2 + ((request_num + metric_num) % 50),
                        "memory": 68.1 + ((request_num + metric_num) % 30),
                        "latency_ms": 120 + ((request_num + metric_num) % 100),
                        "rps": 350 + ((request_num + metric_num) % 200),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    for metric_num in range(current_batch_size)
                ]

                pending.add(asyncio.create_task(self._send_metric_batch(client, metrics)))
                if len(pending) >= concurrent_requests:
                    done, pending = await asyncio.wait(
                        pending,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in done:
                        await task

            if pending:
                done, _ = await asyncio.wait(pending)
                for task in done:
                    await task

        self.end_time = time.time()
        duration = self.end_time - self.start_time
        return self._calculate_stats(duration, target_rps, batch_size)

    async def _send_metric_batch(self, client: httpx.AsyncClient, metrics: List[Dict]) -> None:
        """Send one batch of metrics and track request + metric outcomes."""
        start = time.perf_counter()
        try:
            endpoint = "/api/metrics" if len(metrics) == 1 else "/api/metrics/bulk"
            body: Dict = metrics[0] if len(metrics) == 1 else {"metrics": metrics}
            response = await client.post(endpoint, json=body, timeout=10)
            latency = (time.perf_counter() - start) * 1000

            if 200 <= response.status_code < 300:
                self.requests_sent += 1
                self.metrics_sent += len(metrics)
                self.latencies.append(latency)
            else:
                self.requests_failed += 1
                self.metrics_failed += len(metrics)
                self.errors.append(f"HTTP {response.status_code}")
        except asyncio.TimeoutError:
            self.requests_failed += 1
            self.metrics_failed += len(metrics)
            self.errors.append("timeout")
        except Exception as exc:  # pragma: no cover - network/runtime dependent
            self.requests_failed += 1
            self.metrics_failed += len(metrics)
            self.errors.append(type(exc).__name__)

    def _calculate_stats(self, duration: float, target_rps: int, batch_size: int) -> Dict:
        """Calculate performance statistics."""
        if not self.latencies:
            return {
                "target_rps": target_rps,
                "batch_size": batch_size,
                "achieved_rps": 0,
                "total_sent": self.metrics_sent,
                "total_failed": self.metrics_failed,
                "successful_requests": self.requests_sent,
                "failed_requests": self.requests_failed,
                "error_rate": 1.0,
                "error": "No successful metrics",
                "success": False,
            }

        latencies = sorted(self.latencies)
        total_attempts = self.metrics_sent + self.metrics_failed
        error_counts: Dict[str, int] = {}
        for error in self.errors:
            error_counts[error] = error_counts.get(error, 0) + 1

        error_rate = self.metrics_failed / total_attempts if total_attempts > 0 else 1.0
        return {
            "target_rps": target_rps,
            "batch_size": batch_size,
            "achieved_rps": int(self.metrics_sent / duration),
            "duration_seconds": round(duration, 2),
            "total_sent": self.metrics_sent,
            "total_failed": self.metrics_failed,
            "total_attempts": total_attempts,
            "successful_requests": self.requests_sent,
            "failed_requests": self.requests_failed,
            "request_rps": round(self.requests_sent / duration, 2),
            "error_rate": round(error_rate, 4),
            "error_breakdown": error_counts,
            "throughput_per_sec": round(self.metrics_sent / duration, 0),
            "p50_latency_ms": round(float(np.percentile(latencies, 50)), 2),
            "p95_latency_ms": round(float(np.percentile(latencies, 95)), 2),
            "p99_latency_ms": round(float(np.percentile(latencies, 99)), 2),
            "p99_9_latency_ms": round(float(np.percentile(latencies, 99.9)), 2),
            "avg_latency_ms": round(float(np.mean(latencies)), 2),
            "max_latency_ms": round(float(np.max(latencies)), 2),
            "min_latency_ms": round(float(np.min(latencies)), 2),
            "stddev_ms": round(float(np.std(latencies)), 2),
            "success": error_rate < 0.05,
        }


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_1k_metrics_per_sec(save_benchmark_result, logger):
    """Benchmark: sustained 1K metrics/sec."""
    benchmark = ThroughputBenchmark()
    results = await benchmark.run_throughput_test(
        target_rps=1_000,
        duration_seconds=_benchmark_duration(60),
        concurrent_requests=_benchmark_concurrency(20),
    )
    save_benchmark_result("throughput_1k_metrics_per_sec", results)

    logger.info(
        "Results: %s metrics/sec, request_rps=%s, p99=%sms, error_rate=%.2f%%",
        results["achieved_rps"],
        results.get("request_rps"),
        results["p99_latency_ms"],
        results["error_rate"] * 100,
    )

    assert (
        results["achieved_rps"] > 900
    ), f"Only achieved {results['achieved_rps']}/sec (target 1000)"
    assert results["error_rate"] < 0.05, f"Error rate too high: {results['error_rate']:.2%}"
    assert (
        results["p99_latency_ms"] < 500
    ), f"P99 latency too high: {results['p99_latency_ms']:.0f}ms"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_5k_metrics_per_sec(save_benchmark_result, logger):
    """Benchmark: sustained 5K metrics/sec."""
    benchmark = ThroughputBenchmark()
    results = await benchmark.run_throughput_test(
        target_rps=5_000,
        duration_seconds=_benchmark_duration(60),
        concurrent_requests=_benchmark_concurrency(40),
    )
    save_benchmark_result("throughput_5k_metrics_per_sec", results)

    assert (
        results["achieved_rps"] > 4500
    ), f"Only achieved {results['achieved_rps']}/sec (target 5000)"
    assert results["error_rate"] < 0.05
    assert results["p99_latency_ms"] < 700


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_10k_metrics_per_sec(save_benchmark_result, logger):
    """Benchmark: sustained 10K metrics/sec."""
    benchmark = ThroughputBenchmark()
    results = await benchmark.run_throughput_test(
        target_rps=10_000,
        duration_seconds=_benchmark_duration(60),
        concurrent_requests=_benchmark_concurrency(60),
    )
    save_benchmark_result("throughput_10k_metrics_per_sec", results)

    assert (
        results["achieved_rps"] > 9000
    ), f"Only achieved {results['achieved_rps']}/sec (target 10000)"
    assert results["error_rate"] < 0.05
    assert results["p99_latency_ms"] < 1000


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_spike_handling(save_benchmark_result, logger):
    """Benchmark: handles sudden 5x traffic increase gracefully."""
    benchmark = ThroughputBenchmark()

    normal_results = await benchmark.run_throughput_test(
        target_rps=1_000,
        duration_seconds=_benchmark_duration(30),
        concurrent_requests=_benchmark_concurrency(20),
    )
    spike_results = await benchmark.run_throughput_test(
        target_rps=5_000,
        duration_seconds=_benchmark_duration(30),
        concurrent_requests=_benchmark_concurrency(40),
    )

    combined = {
        "normal_phase": normal_results,
        "spike_phase": spike_results,
        "spike_recovery": {
            "latency_increase_ms": spike_results["p99_latency_ms"]
            - normal_results["p99_latency_ms"],
            "recovered": spike_results["p99_latency_ms"] < (normal_results["p99_latency_ms"] * 2),
        },
    }
    save_benchmark_result("throughput_spike_handling", combined)

    assert combined["spike_phase"]["error_rate"] < 0.10, "Too many errors during spike"
    assert (
        combined["spike_recovery"]["recovered"] or spike_results["p99_latency_ms"] < 1000
    ), "Latency increased too much during spike"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_sustained_30_minutes(save_benchmark_result, logger):
    """Stress test: sustained load for 30 minutes at 5K metrics/sec."""
    benchmark = ThroughputBenchmark()
    results = await benchmark.run_throughput_test(
        target_rps=5_000,
        duration_seconds=_benchmark_duration(1800),
        concurrent_requests=_benchmark_concurrency(40),
    )
    save_benchmark_result("throughput_sustained_30_minutes", results)

    assert results["error_rate"] < 0.05, "Too many errors during sustained load"
    assert results["achieved_rps"] > 4500, "Performance degraded over 30 minutes"
