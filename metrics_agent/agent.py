"""
ScaleGuard X — Metrics Collection Agent
Runs on each node and collects system metrics every N seconds,
then publishes them to a Redis Stream for the Ingestion Service to consume.
"""

import json
import logging
import os
import socket
import time
import uuid

import psutil
import redis
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AGENT:%(hostname)s] %(levelname)s %(message)s"
)
log = logging.getLogger("metrics_agent")

# ── Config ───────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT  = int(os.getenv("REDIS_PORT", 6379))
STREAM_KEY  = os.getenv("METRICS_STREAM_KEY", "metrics_stream")
INTERVAL    = int(os.getenv("AGENT_INTERVAL", 5))

# Prefer explicit NODE_ID env, fall back to hostname + short uuid
NODE_ID = os.getenv("NODE_ID") or f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"

# ── Redis connection with retry ──────────────────────────────────
def get_redis_client() -> redis.Redis:
    for attempt in range(20):
        try:
            client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            client.ping()
            log.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            return client
        except redis.ConnectionError as e:
            log.warning(f"Redis not ready (attempt {attempt+1}): {e}")
            time.sleep(3)
    raise RuntimeError("Cannot connect to Redis after 20 attempts")

# ── Metric collection ────────────────────────────────────────────
def collect_metrics() -> dict:
    cpu    = psutil.cpu_percent(interval=1)
    mem    = psutil.virtual_memory().percent
    disk   = psutil.disk_usage("/").percent

    # Simulate latency and RPS from process counts / load avg
    load = psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else cpu / 100.0
    # Latency: baseline 20ms + noise proportional to load
    import random
    latency = round(20 + load * 30 + random.gauss(0, 5), 2)
    latency = max(5.0, latency)

    # RPS: simulate between 50–500, driven by load
    rps = round(max(1, 50 + load * 80 + random.gauss(0, 10)), 2)

    return {
        "node_id":          NODE_ID,
        "timestamp":        time.time(),
        "cpu_usage":        round(cpu, 2),
        "memory_usage":     round(mem, 2),
        "latency_ms":       latency,
        "requests_per_sec": rps,
        "disk_usage":       round(disk, 2),
    }


# ── Main loop ────────────────────────────────────────────────────
def main():
    log.info(f"Starting metrics agent  node_id={NODE_ID}  interval={INTERVAL}s")
    r = get_redis_client()

    while True:
        try:
            metrics = collect_metrics()
            # Publish to Redis Stream
            r.xadd(STREAM_KEY, {k: str(v) for k, v in metrics.items()})
            log.info(
                f"node={NODE_ID} cpu={metrics['cpu_usage']}% "
                f"mem={metrics['memory_usage']}% lat={metrics['latency_ms']}ms "
                f"rps={metrics['requests_per_sec']}"
            )
        except Exception as e:
            log.error(f"Error collecting/sending metrics: {e}")

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
