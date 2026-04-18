"""
ScaleGuard X — Worker Cluster Node

Simulates a backend worker that:
  1. Registers itself via API Gateway health probe
  2. Emits its own metrics to Redis Stream every N seconds
  3. Simulates varying CPU / request load (sinusoidal + spikes)

Phase 1 upgrades:
  Fix #5 — Structured JSON logging
"""

from __future__ import annotations

import asyncio
import os
import random
import socket
import sys
import time
import uuid
from pathlib import Path

import httpx
import redis
from dotenv import load_dotenv

# ── Shared lib ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.logging_config import get_logger, setup_json_logging

load_dotenv()

# ── Config ────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "redis_queue")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
STREAM_KEY = os.getenv("METRICS_STREAM_KEY", "metrics_stream")
INTERVAL   = int(os.getenv("AGENT_INTERVAL", 5))
API_URL    = (
    f"http://{os.getenv('API_GATEWAY_HOST', 'api_gateway')}"
    f":{os.getenv('API_GATEWAY_PORT', '8000')}"
)
NODE_ID = (
    os.getenv("NODE_ID")
    or f"worker-{socket.gethostname()}-{str(uuid.uuid4())[:6]}"
)

setup_json_logging("worker_cluster")
log = get_logger("worker_cluster")


# ── Redis — retry loop ────────────────────────────────────────────
def get_redis() -> redis.Redis:
    for attempt in range(20):
        delay = min(2 ** attempt, 30)
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            r.ping()
            log.info("redis_connected", extra={"host": REDIS_HOST, "port": REDIS_PORT})
            return r
        except redis.ConnectionError as exc:
            log.warning(
                "redis_not_ready",
                extra={"attempt": attempt + 1, "retry_in_s": delay, "error": str(exc)},
            )
            time.sleep(delay)
    raise RuntimeError("Cannot connect to Redis after 20 attempts")


# ── Simulate load pattern ─────────────────────────────────────────
class LoadSimulator:
    """Generates realistic sinusoidal + noisy metrics."""

    def __init__(self) -> None:
        self.t         = 0
        self.phase     = random.uniform(0, 6.28)
        self.base_cpu  = random.uniform(20, 45)

    def tick(self) -> dict:
        self.t += 1

        # CPU: base + sinusoidal wave + spikes
        cpu = self.base_cpu + 20 * abs(
            0.5 * (1 + (self.t % 120) / 60)
        ) + random.gauss(0, 4)
        # Occasional artificial stress (simulates a load spike)
        if self.t % 180 == 0:
            cpu += random.uniform(30, 50)
        cpu = min(99.9, max(2.0, cpu))

        mem     = 35 + 25 * abs((self.t % 90) / 90) + random.gauss(0, 3)
        mem     = min(99.0, max(10.0, mem))
        latency = max(5.0, 15 + cpu * 0.8 + random.gauss(0, 8))
        rps     = max(1.0, 50 + cpu * 2.5 + random.gauss(0, 15))
        disk    = min(99.0, max(0.0, 40.0 + random.gauss(0, 1)))

        return {
            "node_id":          NODE_ID,
            "timestamp":        time.time(),
            "cpu_usage":        round(cpu, 2),
            "memory_usage":     round(mem, 2),
            "latency_ms":       round(latency, 2),
            "requests_per_sec": round(rps, 2),
            "disk_usage":       round(disk, 2),
        }


# ── Register worker with API (best-effort) ────────────────────────
async def register_worker() -> None:
    """Probe API Gateway — confirms network connectivity on startup."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{API_URL}/health")
            if resp.status_code == 200:
                log.info("api_gateway_reachable", extra={"node_id": NODE_ID})
    except Exception as exc:
        log.warning("api_gateway_unreachable", extra={"error": str(exc)})


# ── Main loop ─────────────────────────────────────────────────────
def main() -> None:
    log.info("worker_starting", extra={"node_id": NODE_ID, "interval_s": INTERVAL})
    r   = get_redis()
    sim = LoadSimulator()

    # Best-effort API registration probe
    try:
        asyncio.run(register_worker())
    except Exception:
        pass

    while True:
        try:
            metrics = sim.tick()
            r.xadd(STREAM_KEY, {k: str(v) for k, v in metrics.items()})
            log.info(
                "metrics_emitted",
                extra={
                    "node_id":    NODE_ID,
                    "cpu":        metrics["cpu_usage"],
                    "mem":        metrics["memory_usage"],
                    "latency_ms": metrics["latency_ms"],
                    "rps":        metrics["requests_per_sec"],
                },
            )
        except Exception as exc:
            log.error("worker_emit_error", extra={"error": str(exc)})
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
