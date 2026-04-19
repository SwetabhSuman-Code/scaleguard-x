"""
Locust load testing script for FastAPI /api/metrics endpoint.

Run with:
    locust -f benchmarks/locustfile.py -u 100 -r 10 -t 5m --host http://localhost:8000
    
Where:
    -u: number of users (100-500)
    -r: spawn rate (users per second)
    -t: test duration
    --host: target API base URL
"""

import random
import string
from locust import HttpUser, task, between


class MetricsUser(HttpUser):
    """Simulate users posting metrics to the /api/metrics endpoint."""
    
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    @task
    def post_metrics(self):
        """Post a metric payload to /api/metrics endpoint."""
        payload = {
            "node_id": self._generate_node_id(),
            "cpu": round(random.uniform(0, 100), 2),
            "memory": round(random.uniform(0, 100), 2),
            "latency": round(random.uniform(10, 5000), 2),  # milliseconds
            "rps": random.randint(10, 10000),  # requests per second
            "disk": round(random.uniform(0, 100), 2),
        }
        
        self.client.post(
            "/api/metrics",
            json=payload,
            headers={"Content-Type": "application/json"},
            name="/api/metrics"
        )
    
    @staticmethod
    def _generate_node_id() -> str:
        """Generate a random node ID (e.g., 'worker-abc123')."""
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"worker-{random_suffix}"


class MetricsUserWithAuth(HttpUser):
    """Simulate users posting metrics with JWT authentication."""
    
    wait_time = between(1, 3)
    token = None
    
    def on_start(self):
        """Get JWT token before starting tasks."""
        try:
            response = self.client.post(
                "/auth/token",
                json={"username": "user", "password": "password"}
            )
            if response.status_code == 200:
                self.token = response.json().get("access_token")
        except Exception as e:
            print(f"Failed to obtain token: {e}")
    
    @task
    def post_metrics(self):
        """Post a metric payload with authentication."""
        if not self.token:
            return
        
        payload = {
            "node_id": self._generate_node_id(),
            "cpu": round(random.uniform(0, 100), 2),
            "memory": round(random.uniform(0, 100), 2),
            "latency": round(random.uniform(10, 5000), 2),
            "rps": random.randint(10, 10000),
            "disk": round(random.uniform(0, 100), 2),
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}"
        }
        
        self.client.post(
            "/api/metrics",
            json=payload,
            headers=headers,
            name="/api/metrics"
        )
    
    @staticmethod
    def _generate_node_id() -> str:
        """Generate a random node ID."""
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"worker-{random_suffix}"
