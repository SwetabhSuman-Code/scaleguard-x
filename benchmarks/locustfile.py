"""Locust load testing profile for ScaleGuard X."""

from __future__ import annotations

import os
import random
from typing import Any, Dict, List

from locust import between, task
from locust.contrib.fasthttp import FastHttpUser


CPU_BASELINE = float(os.getenv("LOCUST_CPU_BASELINE", "72"))
MEMORY_BASELINE = float(os.getenv("LOCUST_MEMORY_BASELINE", "64"))
LATENCY_BASELINE = float(os.getenv("LOCUST_LATENCY_BASELINE", "140"))
RPS_BASELINE = float(os.getenv("LOCUST_RPS_BASELINE", "320"))
DISK_BASELINE = float(os.getenv("LOCUST_DISK_BASELINE", "45"))
NODE_COUNT = int(os.getenv("LOCUST_NODE_COUNT", "50"))
BATCH_SIZE = max(1, int(os.getenv("LOCUST_BATCH_SIZE", "1")))
AUTH_ROLE = os.getenv("LOCUST_AUTH_ROLE", "service")
USE_AUTH = os.getenv("LOCUST_USE_AUTH", "0") == "1"


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _metric_payload(node_id: str | None = None) -> Dict[str, Any]:
    return {
        "node_id": node_id or f"load-node-{random.randint(1, NODE_COUNT):02d}",
        "cpu_usage": round(_clamp(random.gauss(CPU_BASELINE, 9), 5, 99), 2),
        "memory_usage": round(_clamp(random.gauss(MEMORY_BASELINE, 7), 10, 99), 2),
        "latency_ms": round(_clamp(random.gauss(LATENCY_BASELINE, 30), 5, 1500), 2),
        "requests_per_sec": round(_clamp(random.gauss(RPS_BASELINE, 60), 1, 5000), 2),
        "disk_usage": round(_clamp(random.gauss(DISK_BASELINE, 4), 1, 99), 2),
    }


def _batch_payload() -> Dict[str, List[Dict[str, Any]]]:
    return {"metrics": [_metric_payload() for _ in range(BATCH_SIZE)]}


class ScaleGuardUser(FastHttpUser):
    """Mixed workload used for the week-2 ramp and spike tests."""

    wait_time = between(0.1, 0.5)
    insecure = True

    def on_start(self) -> None:
        self.headers = {}
        if not USE_AUTH:
            return

        response = self.client.post(
            "/api/auth/token",
            json={"username": f"locust-{random.randint(1000, 9999)}", "role": AUTH_ROLE},
            name="/api/auth/token",
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            if token:
                self.headers = {"Authorization": f"Bearer {token}"}

    @task(3)
    def post_metric(self) -> None:
        if BATCH_SIZE > 1:
            self.client.post(
                "/api/metrics/bulk",
                json=_batch_payload(),
                headers=self.headers,
                name="/api/metrics/bulk",
            )
            return

        self.client.post(
            "/api/metrics",
            json=_metric_payload(),
            headers=self.headers,
            name="/api/metrics",
        )

    @task(1)
    def get_metrics(self) -> None:
        self.client.get("/api/metrics?limit=100", headers=self.headers, name="/api/metrics")

    @task(1)
    def get_status(self) -> None:
        self.client.get("/api/status", headers=self.headers, name="/api/status")
