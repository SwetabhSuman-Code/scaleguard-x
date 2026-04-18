"""
ScaleGuard X — Metrics Collection Agent

Runs on each node; collects system metrics every N seconds
and publishes them to Redis Stream for the Ingestion Service.

Phase 1 upgrades:
  Fix #5 — Structured JSON logging
"""

from __future__ import annotations

import os
import random
import socket
import sys
import time
import uuid
from pathlib import Path

import psutil
import redis
from dotenv import load_dotenv

# ── Shared lib ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.logging_config import get_logger, setup_json_logging
from lib.prometheus_metrics import setup_metrics, setup_metrics_server

load_dotenv()

# ── Config ────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
STREAM_KEY = os.getenv("METRICS_STREAM_KEY", "metrics_stream")
INTERVAL   = int(os.getenv("AGENT_INTERVAL", 5))

# Prefer explicit NODE_ID env; fall back to hostname + short uuid
NODE_ID = os.getenv("NODE_ID") or f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"

setup_json_logging("metrics_agent")
setup_metrics("metrics_agent")
setup_metrics_server(port=9095)
log = get_logger("metrics_agent")


# ── Redis connection — exponential back-off ───────────────────────
def get_redis_client() -> redis.Redis:
    for attempt in range(20):
        delay = min(2 ** attempt, 30)
        try:
            client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            client.ping()
            log.info(
                "redis_connected",
                extra={"host": REDIS_HOST, "port": REDIS_PORT, "node_id": NODE_ID},
            )
            return client
        except redis.ConnectionError as exc:
            log.warning(
                "redis_not_ready",
                extra={"attempt": attempt + 1, "retry_in_s": delay, "error": str(exc)},
            )
            time.sleep(delay)
    raise RuntimeError("Cannot connect to Redis after 20 attempts")


# ── Metric collection ─────────────────────────────────────────────
def collect_metrics() -> dict:
    """Gather CPU, memory, disk, and simulate latency/RPS from load average."""
    cpu  = psutil.cpu_percent(interval=1)
    mem  = psutil.virtual_memory().percent
    disk = psutil.disk_usage(Path("/")).percent

    # On platforms without getloadavg (Windows), fall back to cpu fraction
    load    = psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else cpu / 100.0
    latency = round(max(5.0, 20 + load * 30 + random.gauss(0, 5)), 2)
    rps     = round(max(1.0, 50 + load * 80 + random.gauss(0, 10)), 2)

    return {
        "node_id":          NODE_ID,
        "timestamp":        time.time(),
        "cpu_usage":        round(cpu, 2),
        "memory_usage":     round(mem, 2),
        "latency_ms":       latency,
        "requests_per_sec": rps,
        "disk_usage":       round(disk, 2),
    }


# ── Main loop ─────────────────────────────────────────────────────
def main() -> None:
    log.info(
        "metrics_agent_starting",
        extra={"node_id": NODE_ID, "interval_s": INTERVAL},
    )
    r = get_redis_client()

    while True:
        try:
            metrics = collect_metrics()
            r.xadd(STREAM_KEY, {k: str(v) for k, v in metrics.items()})
            log.info(
                "metrics_published",
                extra={
                    "node_id":    NODE_ID,
                    "cpu":        metrics["cpu_usage"],
                    "mem":        metrics["memory_usage"],
                    "latency_ms": metrics["latency_ms"],
                    "rps":        metrics["requests_per_sec"],
                },
            )
        except Exception as exc:
            log.error("metrics_publish_error", extra={"error": str(exc)})

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
