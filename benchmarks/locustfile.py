"""
Locust load testing script for ScaleGuard X — POST /api/metrics endpoint

=== QUICK START ===

1. Gradual load test (50→300 users over 10 mins):
   locust -f benchmarks/locustfile.py -u 300 -r 10 -t 10m --host http://localhost:8000 --web

2. Spike test (instant 300 users):
   locust -f benchmarks/locustfile.py -u 300 -r 100 -t 5m --host http://localhost:8000 --web

3. Sustained load (constant 100 users for 15 mins):
   locust -f benchmarks/locustfile.py -u 100 -r 5 -t 15m --host http://localhost:8000 --web

4. Headless mode (no web UI, CSV output):
   locust -f benchmarks/locustfile.py -u 300 -r 10 -t 10m --host http://localhost:8000 \
     --headless --csv=benchmarks/results/load_test

=== PARAMETERS ===
  -u, --users: Number of concurrent users (50-300)
  -r, --spawn-rate: Users spawned per second (2-100)
  -t, --run-time: Test duration (5m, 10m, 15m, etc)
  --host: Target URL (http://localhost:8000)
  --web: Start web UI (localhost:8089)
  --headless: Run without web UI
  --csv: Export results to CSV

=== WEB UI ===
Open http://localhost:8089 in browser to monitor in real-time
"""

import random
import string
import logging
from locust import HttpUser, TaskSet, task, between, constant
from locust.contrib.fasthttp import FastHttpUser

logger = logging.getLogger(__name__)


class MetricsPayloadGenerator:
    """Generate realistic metric payloads with controlled variance."""
    
    # Baseline values
    BASELINE_CPU = 40
    BASELINE_MEMORY = 30
    BASELINE_LATENCY = 100
    BASELINE_RPS = 500
    BASELINE_DISK = 25
    
    # Variance (±%)
    VARIANCE_CPU = 30
    VARIANCE_MEMORY = 25
    VARIANCE_LATENCY = 50
    VARIANCE_RPS = 40
    VARIANCE_DISK = 20
    
    @staticmethod
    def generate_node_id(base_id: int = None) -> str:
        """Generate realistic node ID (e.g., 'worker-01', 'node-12')."""
        if base_id is not None:
            return f"worker-{base_id:02d}"
        return f"worker-{random.randint(1, 50):02d}"
    
    @staticmethod
    def generate_payload(node_id: str = None) -> dict:
        """Generate metric payload with realistic variance."""
        if not node_id:
            node_id = MetricsPayloadGenerator.generate_node_id()
        
        # Normal distribution around baseline
        cpu = max(0, min(100, 
            MetricsPayloadGenerator.BASELINE_CPU + 
            random.gauss(0, MetricsPayloadGenerator.VARIANCE_CPU)
        ))
        
        memory = max(0, min(100,
            MetricsPayloadGenerator.BASELINE_MEMORY +
            random.gauss(0, MetricsPayloadGenerator.VARIANCE_MEMORY)
        ))
        
        latency = max(1, 
            MetricsPayloadGenerator.BASELINE_LATENCY +
            random.gauss(0, MetricsPayloadGenerator.VARIANCE_LATENCY)
        )
        
        rps = max(1, 
            MetricsPayloadGenerator.BASELINE_RPS +
            random.gauss(0, MetricsPayloadGenerator.VARIANCE_RPS)
        )
        
        disk = max(0, min(100,
            MetricsPayloadGenerator.BASELINE_DISK +
            random.gauss(0, MetricsPayloadGenerator.VARIANCE_DISK)
        ))
        
        return {
            "node_id": node_id,
            "cpu": round(cpu, 2),
            "memory": round(memory, 2),
            "latency": round(latency, 2),
            "rps": int(rps),
            "disk": round(disk, 2),
        }


class MetricsTaskSet(TaskSet):
    """Task definitions for metrics posting."""
    
    @task(3)
    def post_single_metric(self):
        """Post a single metric (weight: 3)."""
        payload = MetricsPayloadGenerator.generate_payload()
        
        with self.client.post(
            "/api/metrics",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code in [200, 201, 202]:
                response.success()
                logger.debug(f"✓ Metrics posted: {payload['node_id']}")
            else:
                response.failure(f"Unexpected status {response.status_code}")
                logger.error(f"✗ Failed: {response.status_code}")
    
    @task(1)
    def post_batch_metrics(self):
        """Post multiple metrics in sequence (weight: 1)."""
        for i in range(random.randint(3, 8)):
            payload = MetricsPayloadGenerator.generate_payload(
                node_id=f"worker-batch-{i:02d}"
            )
            
            with self.client.post(
                "/api/metrics",
                json=payload,
                catch_response=True
            ) as response:
                if response.status_code in [200, 201, 202]:
                    response.success()
                else:
                    response.failure(f"Batch post failed: {response.status_code}")
                    break
    
    @task(1)
    def health_check(self):
        """Occasional health check (weight: 1)."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")


class MetricsUser(HttpUser):
    """Normal load - users send metrics at regular intervals."""
    tasks = [MetricsTaskSet]
    wait_time = between(1, 3)  # 1-3 second wait between task cycles
    
    def on_start(self):
        """Initialize user."""
        user_id = f"user-{id(self) % 10000}"
        logger.info(f"User {user_id} started")
    
    def on_stop(self):
        """Cleanup."""
        user_id = f"user-{id(self) % 10000}"
        logger.info(f"User {user_id} stopped")


class FastMetricsUser(FastHttpUser):
    """High-throughput user (uses FastHTTP) - simulates aggressive monitoring."""
    tasks = [MetricsTaskSet]
    wait_time = between(0.5, 1.5)  # Faster requests
    
    def on_start(self):
        user_id = f"fast-user-{id(self) % 10000}"
        logger.info(f"{user_id} started (high-throughput)")


class SpikeMetricsUser(HttpUser):
    """Spike test user - sudden metric floods from alerting scenarios."""
    wait_time = constant(0.1)  # Very fast requests
    
    @task
    def rapid_fire_metrics(self):
        """Send metrics rapidly to simulate alert spike."""
        for _ in range(random.randint(5, 15)):
            payload = MetricsPayloadGenerator.generate_payload()
            self.client.post(
                "/api/metrics",
                json=payload,
                timeout=5
            )
