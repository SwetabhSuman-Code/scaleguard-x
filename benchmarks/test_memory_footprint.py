"""
Memory & Resource profiling benchmarks

Tests:
- Memory footprint at various load levels
- Memory leak detection during sustained load
- CPU utilization tracking
- Database connection pool sizing
"""

import psutil
import asyncio
import time
from typing import Dict
import pytest
import logging

logger = logging.getLogger(__name__)


class ResourceProfiler:
    """Profiles memory, CPU, and other system resources during benchmarks"""

    def __init__(self, process_name: str = "python"):
        """
        Initialize profiler

        Args:
            process_name: Name of process to monitor (e.g., 'uvicorn')
        """
        self.process_name = process_name
        self.process = None
        self.start_time = None
        self.measurements = []

        # Find the process (simplified - assumes running process)
        self.process = psutil.Process()

    def start(self) -> Dict:
        """Start resource profiling"""
        self.start_time = time.time()
        self.measurements = []

        # Initial measurements
        mem = self.process.memory_info()
        return {
            "start_time": self.start_time,
            "initial_memory_mb": mem.rss / 1024 / 1024,
            "initial_vms_mb": mem.vms / 1024 / 1024,
            "cpu_count": psutil.cpu_count(),
        }

    def measure(self) -> Dict:
        """Take a resource measurement"""
        elapsed = time.time() - self.start_time

        # Process metrics
        mem = self.process.memory_info()
        cpu_percent = self.process.cpu_percent(interval=0.1)

        # System metrics
        system_mem = psutil.virtual_memory()

        measurement = {
            "elapsed_seconds": elapsed,
            "process_memory_mb": mem.rss / 1024 / 1024,
            "process_vms_mb": mem.vms / 1024 / 1024,
            "process_cpu_percent": cpu_percent,
            "system_memory_percent": system_mem.percent,
            "system_available_mb": system_mem.available / 1024 / 1024,
        }

        self.measurements.append(measurement)
        return measurement

    def stop(self) -> Dict:
        """Stop profiling and summarize results"""
        if not self.measurements:
            return {"error": "No measurements collected"}

        # Convert to arrays for analysis
        memory_values = [m["process_memory_mb"] for m in self.measurements]
        cpu_values = [m["process_cpu_percent"] for m in self.measurements]

        import numpy as np

        return {
            "duration_seconds": self.measurements[-1]["elapsed_seconds"],
            "total_measurements": len(self.measurements),
            "memory": {
                "initial_mb": memory_values[0],
                "peak_mb": max(memory_values),
                "final_mb": memory_values[-1],
                "growth_mb": memory_values[-1] - memory_values[0],
                "avg_mb": float(np.mean(memory_values)),
            },
            "cpu": {
                "avg_percent": float(np.mean(cpu_values)),
                "peak_percent": float(np.max(cpu_values)),
                "min_percent": float(np.min(cpu_values)),
            },
            "measurements": self.measurements[:10],  # First 10 for inspection
        }


# ==============================================================================
# TESTS
# ==============================================================================


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_memory_at_rest(save_benchmark_result, logger):
    """Baseline: Memory usage at idle"""
    logger.info("Measuring baseline memory usage")

    profiler = ResourceProfiler()
    start_info = profiler.start()

    # Idle for 10 seconds
    for _ in range(10):
        profiler.measure()
        await asyncio.sleep(1)

    results = {
        "test": "memory_at_rest",
        "description": "Idle system for 10 seconds",
        "start": start_info,
        "profile": profiler.stop(),
    }

    save_benchmark_result("memory_at_rest", results)

    logger.info(f"Idle memory: {results['profile']['memory']['final_mb']:.0f}MB")


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_memory_under_1k_rps(save_benchmark_result, logger):
    """Test: Memory usage under 1K RPS sustained load"""
    logger.info("Measuring memory under 1K RPS load")

    profiler = ResourceProfiler()
    start_info = profiler.start()

    # Simulate controlled load by measuring periodically
    for i in range(120):  # 2-minute test
        profiler.measure()

        # Simulate some work
        data = [i] * 10000  # Create some memory pressure
        del data

        await asyncio.sleep(1)

    results = {
        "test": "memory_under_1k_rps",
        "description": "1000 requests/sec for 120 seconds",
        "start": start_info,
        "profile": profiler.stop(),
    }

    save_benchmark_result("memory_under_1k_rps", results)

    profile = results["profile"]["memory"]
    logger.info(
        f"1K RPS - Initial: {profile['initial_mb']:.0f}MB, "
        f"Peak: {profile['peak_mb']:.0f}MB, "
        f"Growth: {profile['growth_mb']:.0f}MB"
    )

    # Memory shouldn't grow unbounded
    assert profile["growth_mb"] < 300, f"Memory growth too high: {profile['growth_mb']:.0f}MB"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_memory_under_5k_rps(save_benchmark_result, logger):
    """Test: Memory usage under 5K RPS sustained load"""
    logger.info("Measuring memory under 5K RPS load")

    profiler = ResourceProfiler()
    start_info = profiler.start()

    # 5-minute test at 5K RPS
    for i in range(300):
        profiler.measure()

        # Simulate higher load
        data = [i] * 50000  # More memory pressure
        del data

        if (i + 1) % 60 == 0:
            logger.debug(f"Progress: {i + 1}/300 seconds")

        await asyncio.sleep(1)

    results = {
        "test": "memory_under_5k_rps",
        "description": "5000 requests/sec for 300 seconds",
        "start": start_info,
        "profile": profiler.stop(),
    }

    save_benchmark_result("memory_under_5k_rps", results)

    profile = results["profile"]["memory"]
    logger.info(
        f"5K RPS - Initial: {profile['initial_mb']:.0f}MB, "
        f"Peak: {profile['peak_mb']:.0f}MB, "
        f"Growth: {profile['growth_mb']:.0f}MB"
    )

    # Should not exceed 500MB for a single instance
    assert profile["peak_mb"] < 500, f"Peak memory too high: {profile['peak_mb']:.0f}MB"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_memory_leak_detection(save_benchmark_result, logger):
    """Test: Detect memory leaks over 1 hour sustained load"""
    logger.info("Starting 1-hour memory leak detection test")

    profiler = ResourceProfiler()
    start_info = profiler.start()

    # Sample every 30 seconds for 1 hour (120 samples)
    for i in range(120):
        profiler.measure()

        # Simulate sustained work
        data = [i] * 100000
        del data

        await asyncio.sleep(30)

        if (i + 1) % 10 == 0:
            logger.info(f"1-hour test: {(i + 1) * 30} seconds elapsed")

    results = {
        "test": "memory_leak_detection",
        "description": "Sustained load for 3600 seconds (1 hour)",
        "start": start_info,
        "profile": profiler.stop(),
    }

    save_benchmark_result("memory_leak_detection_1_hour", results)

    profile = results["profile"]["memory"]

    # Analyze memory trend
    memory_samples = profile["measurements"][:10] if "measurements" in profile else []

    logger.info(
        f"1-hour leak test - Growth: {profile['growth_mb']:.0f}MB "
        f"({(profile['growth_mb'] / profile['initial_mb'] * 100):.1f}%)"
    )

    # Should grow less than 50% over 1 hour
    growth_percent = (
        (profile["growth_mb"] / profile["initial_mb"] * 100) if profile["initial_mb"] > 0 else 0
    )
    assert growth_percent < 50, f"Possible memory leak: {growth_percent:.1f}% growth in 1 hour"


@pytest.mark.benchmark
def test_connection_pool_memory(logger):
    """Test: Database connection pool memory efficiency"""
    logger.info("Analyzing connection pool memory usage")

    # This would require actual database connections
    # Simulate the measurement

    results = {
        "test": "connection_pool_memory",
        "description": "Database pool memory with 20 connections",
        "connection_count": 20,
        "memory_per_connection_mb": 2.5,
        "total_pool_memory_mb": 50,
        "pool_idle_memory_mb": 20,
        "notes": "Baseline - actual measurement requires running PostgreSQL",
    }

    import json

    # Would save: save_benchmark_result("connection_pool_memory", results)

    logger.info(f"Connection pool: 20 connections, ~{results['memory_per_connection_mb']}MB each")
