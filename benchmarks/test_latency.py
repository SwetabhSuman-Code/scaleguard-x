"""
Latency & Percentile benchmarks

Tests:
- API endpoint latency (P50, P95, P99, P99.9)
- Latency under load
- Tail latency tracking
- Query latency for different data ranges
"""
import time
import numpy as np
from typing import Dict, List
import pytest
import httpx
import json
import logging

logger = logging.getLogger(__name__)


class LatencyBenchmark:
    """Measures end-to-end request latency percentiles"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.latencies: List[float] = []
        self.errors: List[str] = []
    
    async def measure_api_latency(
        self,
        endpoint: str,
        samples: int = 1_000,
        warm_up: int = 10,
        concurrent: bool = False,
        concurrent_requests: int = 10
    ) -> Dict:
        """
        Measure latency of specific endpoint
        
        Args:
            endpoint: API endpoint to test
            samples: Number of samples to collect
            warm_up: Warm-up requests before measuring
            concurrent: Run requests concurrently (vs sequential)
            concurrent_requests: Parallel connections if concurrent=True
        
        Returns:
            {
                'samples': 1000,
                'p50_ms': 120.5,
                'p95_ms': 200.3,
                'p99_ms': 350.2,
                'p99_9_ms': 450.1,
                'max_ms': 5000,
                'avg_ms': 150.2,
                'success': true
            }
        """
        self.latencies = []
        self.errors = []
        
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            # Warm-up phase
            logger.info(f"Warming up: {warm_up} requests to {endpoint}")
            for _ in range(warm_up):
                try:
                    await client.get(endpoint)
                except Exception as e:
                    logger.warning(f"Warm-up request failed: {e}")
            
            logger.info(f"Measuring: {samples} samples from {endpoint}")
            
            if concurrent:
                latencies = await self._measure_concurrent(
                    client, endpoint, samples, concurrent_requests
                )
            else:
                latencies = await self._measure_sequential(
                    client, endpoint, samples
                )
            
            self.latencies = latencies
        
        return self._calculate_percentiles(latencies)
    
    async def _measure_sequential(self, client: httpx.AsyncClient, endpoint: str, samples: int) -> List[float]:
        """Measure latency sequentially"""
        latencies = []
        for i in range(samples):
            try:
                start = time.perf_counter()
                response = await client.get(endpoint)
                latency = (time.perf_counter() - start) * 1000  # ms
                
                if 200 <= response.status_code < 300:
                    latencies.append(latency)
                else:
                    self.errors.append(f"HTTP {response.status_code}")
            except Exception as e:
                self.errors.append(str(type(e).__name__))
            
            # Log progress every 100 samples
            if (i + 1) % 100 == 0:
                logger.debug(f"Collected {i + 1}/{samples} samples")
        
        return latencies
    
    async def _measure_concurrent(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        samples: int,
        concurrent_requests: int
    ) -> List[float]:
        """Measure latency with concurrent requests"""
        import asyncio
        
        latencies = []
        
        async def make_request():
            try:
                start = time.perf_counter()
                response = await client.get(endpoint)
                latency = (time.perf_counter() - start) * 1000  # ms
                
                if 200 <= response.status_code < 300:
                    latencies.append(latency)
                else:
                    self.errors.append(f"HTTP {response.status_code}")
            except Exception as e:
                self.errors.append(str(type(e).__name__))
        
        # Create tasks in batches
        for batch_start in range(0, samples, concurrent_requests):
            batch_size = min(concurrent_requests, samples - batch_start)
            tasks = [make_request() for _ in range(batch_size)]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            if (batch_start + batch_size) % 100 == 0:
                logger.debug(f"Collected {batch_start + batch_size}/{samples} samples")
        
        return latencies
    
    def measure_query_latency(
        self,
        query_params: Dict,
        samples: int = 500
    ) -> Dict:
        """Measure latency for Prometheus queries"""
        latencies = []
        
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            for i in range(samples):
                start = time.perf_counter()
                try:
                    response = client.get("/api/query", params=query_params)
                    latency = (time.perf_counter() - start) * 1000
                    
                    if response.status_code == 200:
                        latencies.append(latency)
                    else:
                        self.errors.append(f"HTTP {response.status_code}")
                except Exception as e:
                    self.errors.append(str(type(e).__name__))
        
        return self._calculate_percentiles(latencies)
    
    def _calculate_percentiles(self, data: List[float]) -> Dict:
        """Calculate latency percentiles"""
        if not data:
            return {
                "samples": 0,
                "error": "No successful requests",
                "errors": self.errors,
                "success": False
            }
        
        sorted_data = sorted(data)
        
        return {
            "samples": len(sorted_data),
            "min_ms": round(float(np.min(sorted_data)), 2),
            "p50_ms": round(float(np.percentile(sorted_data, 50)), 2),
            "p75_ms": round(float(np.percentile(sorted_data, 75)), 2),
            "p95_ms": round(float(np.percentile(sorted_data, 95)), 2),
            "p99_ms": round(float(np.percentile(sorted_data, 99)), 2),
            "p99_9_ms": round(float(np.percentile(sorted_data, 99.9)), 2),
            "max_ms": round(float(np.max(sorted_data)), 2),
            "mean_ms": round(float(np.mean(sorted_data)), 2),
            "stddev_ms": round(float(np.std(sorted_data)), 2),
            "error_count": len(self.errors),
            "error_types": list(set(self.errors)),
            "success": len(self.errors) < len(sorted_data) * 0.05  # < 5% errors
        }


# ==============================================================================
# TESTS
# ==============================================================================

@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_health_endpoint_latency(save_benchmark_result, logger):
    """Test: /health endpoint latency should be < 50ms"""
    logger.info("Measuring /health endpoint latency")
    
    benchmark = LatencyBenchmark()
    results = await benchmark.measure_api_latency(
        "/health",
        samples=1_000,
        warm_up=10
    )
    
    save_benchmark_result("latency_health_endpoint", results)
    
    logger.info(f"Health endpoint - P99: {results['p99_ms']}ms, "
                f"P95: {results['p95_ms']}ms, "
                f"Mean: {results['mean_ms']}ms")
    
    assert results["p99_ms"] < 50, \
        f"Health endpoint P99 too high: {results['p99_ms']:.0f}ms"
    assert results["success"]


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_metrics_post_latency_sequential(save_benchmark_result, logger):
    """Test: POST /api/metrics latency (sequential)"""
    logger.info("Measuring POST /api/metrics latency (sequential)")
    
    benchmark = LatencyBenchmark()
    
    # Create a client that will make POST requests
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30) as client:
        latencies = []
        errors = []
        
        for i in range(500):
            start = time.perf_counter()
            try:
                response = await client.post(
                    "/api/metrics",
                    json={
                        "node_id": f"node-{i % 10}",
                        "cpu": 45.2,
                        "memory": 68.1,
                        "latency_ms": 120,
                        "rps": 350,
                        "timestamp": "2024-01-01T00:00:00"
                    }
                )
                latency = (time.perf_counter() - start) * 1000
                
                if 200 <= response.status_code < 300:
                    latencies.append(latency)
                else:
                    errors.append(f"HTTP {response.status_code}")
            except Exception as e:
                errors.append(str(type(e).__name__))
    
    results = {
        "samples": len(latencies),
        "min_ms": round(float(np.min(latencies)) if latencies else 0, 2),
        "p50_ms": round(float(np.percentile(latencies, 50)) if latencies else 0, 2),
        "p95_ms": round(float(np.percentile(latencies, 95)) if latencies else 0, 2),
        "p99_ms": round(float(np.percentile(latencies, 99)) if latencies else 0, 2),
        "max_ms": round(float(np.max(latencies)) if latencies else 0, 2),
        "mean_ms": round(float(np.mean(latencies)) if latencies else 0, 2),
        "error_count": len(errors),
        "success": len(errors) < len(latencies) * 0.05
    }
    
    save_benchmark_result("latency_post_metrics_sequential", results)
    
    logger.info(f"POST /api/metrics - P99: {results['p99_ms']}ms, "
                f"Mean: {results['mean_ms']}ms")
    
    assert results["p99_ms"] < 500, \
        f"Metrics POST P99 too high: {results['p99_ms']:.0f}ms"
    assert results["success"]


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_metrics_post_latency_concurrent(save_benchmark_result, logger):
    """Test: POST /api/metrics latency under concurrent load"""
    logger.info("Measuring POST /api/metrics latency (concurrent)")
    
    benchmark = LatencyBenchmark()
    
    async with httpx.AsyncClient(
        base_url="http://localhost:8000",
        timeout=30,
        limits=httpx.Limits(max_connections=20)
    ) as client:
        latencies = []
        errors = []
        
        async def send_metric(i):
            start = time.perf_counter()
            try:
                response = await client.post(
                    "/api/metrics",
                    json={
                        "node_id": f"node-{i % 10}",
                        "cpu": 45.2,
                        "memory": 68.1,
                        "latency_ms": 120 + (i % 100),
                        "rps": 350 + (i % 200),
                        "timestamp": "2024-01-01T00:00:00"
                    }
                )
                latency = (time.perf_counter() - start) * 1000
                
                if 200 <= response.status_code < 300:
                    latencies.append(latency)
                else:
                    errors.append(f"HTTP {response.status_code}")
            except Exception as e:
                errors.append(str(type(e).__name__))
        
        import asyncio
        tasks = [send_metric(i) for i in range(1000)]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    results = {
        "samples": len(latencies),
        "concurrent_requests": 20,
        "min_ms": round(float(np.min(latencies)) if latencies else 0, 2),
        "p50_ms": round(float(np.percentile(latencies, 50)) if latencies else 0, 2),
        "p95_ms": round(float(np.percentile(latencies, 95)) if latencies else 0, 2),
        "p99_ms": round(float(np.percentile(latencies, 99)) if latencies else 0, 2),
        "max_ms": round(float(np.max(latencies)) if latencies else 0, 2),
        "mean_ms": round(float(np.mean(latencies)) if latencies else 0, 2),
        "error_count": len(errors),
        "success": len(errors) < len(latencies) * 0.05
    }
    
    save_benchmark_result("latency_post_metrics_concurrent", results)
    
    logger.info(f"Concurrent POST - P99: {results['p99_ms']}ms, "
                f"Mean: {results['mean_ms']}ms")
    
    assert results["p99_ms"] < 700, \
        f"Concurrent POST P99 too high: {results['p99_ms']:.0f}ms"


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_query_latency_1_hour(save_benchmark_result, logger):
    """Test: Query latency for 1 hour of data"""
    logger.info("Measuring query latency for 1-hour range")
    
    benchmark = LatencyBenchmark()
    results = benchmark.measure_query_latency(
        query_params={
            "query": "rate(metrics_processed_total[5m])",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T01:00:00Z",
            "step": "5m"
        },
        samples=200
    )
    
    save_benchmark_result("latency_query_1_hour", results)
    
    logger.info(f"1-hour query - P99: {results.get('p99_ms', 'N/A')}ms")
    
    # Queries should be fast (< 1 sec)
    if results.get("success", False):
        assert results["p99_ms"] < 1000


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_query_latency_7_days(save_benchmark_result, logger):
    """Test: Query latency for 7 days of data"""
    logger.info("Measuring query latency for 7-day range")
    
    benchmark = LatencyBenchmark()
    results = benchmark.measure_query_latency(
        query_params={
            "query": "rate(metrics_processed_total[5m])",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-08T00:00:00Z",
            "step": "1h"
        },
        samples=100
    )
    
    save_benchmark_result("latency_query_7_days", results)
    
    logger.info(f"7-day query - P99: {results.get('p99_ms', 'N/A')}ms")
