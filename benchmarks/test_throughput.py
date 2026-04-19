"""
Throughput benchmarks: How many metrics/second can the system handle?

Tests:
- Sustained throughput at various RPS (1K, 5K, 10K)
- Error rates and timeouts
- Latency percentiles under load
- Spike handling (5x traffic increase)
"""

import asyncio
import json
import time
from typing import Dict, List
import pytest
import httpx
import numpy as np
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ThroughputBenchmark:
    """Measures sustained metrics throughput under load"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.metrics_sent = 0
        self.metrics_failed = 0
        self.start_time = None
        self.end_time = None
        self.latencies: List[float] = []
        self.errors: List[str] = []

    async def run_throughput_test(
        self,
        target_rps: int = 5_000,
        duration_seconds: int = 60,
        concurrent_requests: int = 20,
    ) -> Dict:
        """
        Run sustained throughput test

        Args:
            target_rps: Target metrics per second
            duration_seconds: Test duration
            concurrent_requests: Parallel connections

        Returns:
            {
                "target_rps": 5000,
                "achieved_rps": 4850,
                "total_sent": 290000,
                "total_failed": 150,
                "error_rate": 0.0052,
                "p50_latency_ms": 120,
                "p99_latency_ms": 450,
                "success": true
            }
        """
        self.start_time = time.time()
        self.metrics_sent = 0
        self.metrics_failed = 0
        self.latencies = []
        self.errors = []

        # Calculate metrics per batch
        metrics_per_batch = max(1, target_rps // 10)  # 10 batches per second
        batch_interval = 1.0 / 10  # 100ms between batches

        end_time = self.start_time + duration_seconds
        batch_num = 0

        async with httpx.AsyncClient(
            base_url=self.base_url,
            limits=httpx.Limits(max_connections=concurrent_requests),
            timeout=10.0,
        ) as client:
            while time.time() < end_time:
                # Create batch of metrics
                tasks = []
                for i in range(metrics_per_batch):
                    metric = {
                        "node_id": f"node-{batch_num % 10}",
                        "cpu": 45.2 + (batch_num % 50),
                        "memory": 68.1 + (batch_num % 30),
                        "latency_ms": 120 + (batch_num % 100),
                        "rps": 350 + (batch_num % 200),
                        "timestamp": datetime.utcnow().isoformat(),
                    }

                    task = self._send_metric(client, metric)
                    tasks.append(task)

                # Wait for batch to complete
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                batch_num += 1

                # Maintain timing
                batch_time = time.time() - self.start_time
                scheduled_time = batch_num * batch_interval
                if batch_time < scheduled_time:
                    await asyncio.sleep(scheduled_time - batch_time)

        self.end_time = time.time()
        duration = self.end_time - self.start_time

        return self._calculate_stats(duration, target_rps)

    async def _send_metric(self, client: httpx.AsyncClient, metric: Dict):
        """Send single metric and track timing"""
        start = time.perf_counter()
        try:
            response = await client.post("/api/metrics", json=metric, timeout=10)
            latency = (time.perf_counter() - start) * 1000  # ms

            if 200 <= response.status_code < 300:
                self.metrics_sent += 1
                self.latencies.append(latency)
            else:
                self.metrics_failed += 1
                self.errors.append(f"HTTP {response.status_code}")
        except asyncio.TimeoutError:
            self.metrics_failed += 1
            self.errors.append("timeout")
        except Exception as e:
            self.metrics_failed += 1
            self.errors.append(str(type(e).__name__))

    def _calculate_stats(self, duration: float, target_rps: int) -> Dict:
        """Calculate performance statistics"""
        if not self.latencies:
            return {
                "target_rps": target_rps,
                "achieved_rps": 0,
                "total_sent": self.metrics_sent,
                "total_failed": self.metrics_failed,
                "error_rate": 1.0,
                "error": "No successful metrics",
                "success": False,
            }

        latencies = sorted(self.latencies)

        # Count error types
        error_counts = {}
        for error in self.errors:
            error_counts[error] = error_counts.get(error, 0) + 1

        total_attempts = self.metrics_sent + self.metrics_failed
        error_rate = self.metrics_failed / total_attempts if total_attempts > 0 else 1.0

        return {
            "target_rps": target_rps,
            "achieved_rps": int(self.metrics_sent / duration),
            "duration_seconds": round(duration, 2),
            "total_sent": self.metrics_sent,
            "total_failed": self.metrics_failed,
            "total_attempts": total_attempts,
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
            "success": error_rate < 0.05,  # Less than 5% errors
        }


# ==============================================================================
# TESTS
# ==============================================================================


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_1k_metrics_per_sec(save_benchmark_result, logger):
    """Benchmark: Sustained 1K metrics/sec for 60 seconds"""
    logger.info("Starting 1K metrics/sec throughput test")

    benchmark = ThroughputBenchmark()
    results = await benchmark.run_throughput_test(
        target_rps=1_000, duration_seconds=60, concurrent_requests=10
    )

    # Save results
    save_benchmark_result("throughput_1k_metrics_per_sec", results)

    logger.info(
        f"Results: {results['achieved_rps']} RPS, "
        f"P99={results['p99_latency_ms']}ms, "
        f"Error Rate={results['error_rate']:.2%}"
    )

    # Assertions
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
    """Benchmark: Sustained 5K metrics/sec for 60 seconds"""
    logger.info("Starting 5K metrics/sec throughput test")

    benchmark = ThroughputBenchmark()
    results = await benchmark.run_throughput_test(
        target_rps=5_000, duration_seconds=60, concurrent_requests=30
    )

    save_benchmark_result("throughput_5k_metrics_per_sec", results)

    logger.info(f"Results: {results['achieved_rps']} RPS, " f"P99={results['p99_latency_ms']}ms")

    assert (
        results["achieved_rps"] > 4500
    ), f"Only achieved {results['achieved_rps']}/sec (target 5000)"
    assert results["error_rate"] < 0.05
    assert results["p99_latency_ms"] < 700


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_10k_metrics_per_sec(save_benchmark_result, logger):
    """Benchmark: Sustained 10K metrics/sec for 60 seconds"""
    logger.info("Starting 10K metrics/sec throughput test")

    benchmark = ThroughputBenchmark()
    results = await benchmark.run_throughput_test(
        target_rps=10_000, duration_seconds=60, concurrent_requests=50
    )

    save_benchmark_result("throughput_10k_metrics_per_sec", results)

    logger.info(f"Results: {results['achieved_rps']} RPS, " f"P99={results['p99_latency_ms']}ms")

    assert (
        results["achieved_rps"] > 9000
    ), f"Only achieved {results['achieved_rps']}/sec (target 10000)"
    assert results["error_rate"] < 0.05
    assert results["p99_latency_ms"] < 1000


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_spike_handling(save_benchmark_result, logger):
    """Benchmark: Handles sudden 5x traffic increase gracefully"""
    logger.info("Starting spike handling test")

    benchmark = ThroughputBenchmark()

    # Phase 1: Normal load (1K RPS for 30 sec)
    logger.info("Phase 1: Normal load (1K RPS)")
    normal_results = await benchmark.run_throughput_test(
        target_rps=1_000, duration_seconds=30, concurrent_requests=10
    )

    # Phase 2: Spike load (5K RPS for 30 sec)
    logger.info("Phase 2: Spike load (5K RPS)")
    spike_results = await benchmark.run_throughput_test(
        target_rps=5_000, duration_seconds=30, concurrent_requests=30
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

    # Spike should not cause total collapse
    assert combined["spike_phase"]["error_rate"] < 0.10, "Too many errors during spike"
    assert (
        combined["spike_recovery"]["recovered"] or spike_results["p99_latency_ms"] < 1000
    ), "Latency increased too much during spike"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_throughput_sustained_30_minutes(save_benchmark_result, logger):
    """Stress test: Sustained load for 30 minutes at 5K RPS"""
    logger.info("Starting 30-minute sustained load test")

    benchmark = ThroughputBenchmark()
    results = await benchmark.run_throughput_test(
        target_rps=5_000, duration_seconds=1800, concurrent_requests=30  # 30 minutes
    )

    save_benchmark_result("throughput_sustained_30_minutes", results)

    logger.info(
        f"30-min results: {results['achieved_rps']} avg RPS, "
        f"Error Rate={results['error_rate']:.2%}"
    )

    # Should maintain performance over long duration
    assert results["error_rate"] < 0.05, "Too many errors during sustained load"
    assert results["achieved_rps"] > 4500, "Performance degraded over 30 minutes"
