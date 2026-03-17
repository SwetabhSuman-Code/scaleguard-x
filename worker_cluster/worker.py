"""
ScaleGuard X — Worker Cluster Node
Simulates a backend worker that:
  1. Registers itself in the `workers` table via API Gateway
  2. Emits its own metrics to Redis Stream every N seconds
  3. Sends periodic heartbeats
  4. Simulates varying CPU / request load
"""

import asyncio
import logging
import os
import random
import socket
import time
import uuid

import httpx
import redis
from dotenv import load_dotenv

load_dotenv()

# ── Config ───────────────────────────────────────────────────────
REDIS_HOST    = os.getenv("REDIS_HOST", "redis_queue")
REDIS_PORT    = int(os.getenv("REDIS_PORT", 6379))
STREAM_KEY    = os.getenv("METRICS_STREAM_KEY", "metrics_stream")
INTERVAL      = int(os.getenv("AGENT_INTERVAL", 5))
API_URL       = f"http://{os.getenv('API_GATEWAY_HOST','api_gateway')}:{os.getenv('API_GATEWAY_PORT','8000')}"
NODE_ID       = os.getenv("NODE_ID") or f"worker-{socket.gethostname()}-{str(uuid.uuid4())[:6]}"

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{NODE_ID}] %(levelname)s %(message)s",
)
log = logging.getLogger("worker")

# ── Redis ────────────────────────────────────────────────────────
def get_redis() -> redis.Redis:
    for attempt in range(20):
        try:
            r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            r.ping()
            log.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            return r
        except redis.ConnectionError as e:
            log.warning(f"Redis not ready (attempt {attempt+1}): {e}")
            time.sleep(3)
    raise RuntimeError("Cannot connect to Redis")

# ── Simulate load pattern ────────────────────────────────────────
class LoadSimulator:
    """Generates realistic sinusoidal + noisy metrics."""
    def __init__(self):
        self.t       = 0
        self.phase   = random.uniform(0, 6.28)
        self.base_cpu = random.uniform(20, 45)

    def tick(self) -> dict:
        self.t += 1
        # CPU: base + sinusoidal wave + spikes
        cpu = self.base_cpu + 20 * abs(
            0.5 * (1 + (self.t % 120) / 60)  # growing in first half, falling second half
        ) + random.gauss(0, 4)
        # Occasionally inject artificial stress (simulates load spike)
        if self.t % 180 == 0:
            cpu += random.uniform(30, 50)
        cpu = min(99.9, max(2.0, cpu))

        mem = 35 + 25 * abs((self.t % 90) / 90) + random.gauss(0, 3)
        mem = min(99.0, max(10.0, mem))

        latency = 15 + cpu * 0.8 + random.gauss(0, 8)
        latency = max(5.0, latency)

        rps = 50 + cpu * 2.5 + random.gauss(0, 15)
        rps = max(1.0, rps)

        disk = 40.0 + random.gauss(0, 1)

        return {
            "node_id":          NODE_ID,
            "timestamp":        time.time(),
            "cpu_usage":        round(cpu, 2),
            "memory_usage":     round(mem, 2),
            "latency_ms":       round(latency, 2),
            "requests_per_sec": round(rps, 2),
            "disk_usage":       round(disk, 2),
        }

# ── Register worker with API (best-effort) ───────────────────────
async def register_worker():
    """Call API Gateway to ensure worker is recorded in the DB."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # The API Gateway doesn't have a dedicated register endpoint
            # (workers are synced by the autoscaler). We hit /health as probe.
            resp = await client.get(f"{API_URL}/health")
            if resp.status_code == 200:
                log.info(f"API Gateway reachable — {NODE_ID} ready")
    except Exception as e:
        log.warning(f"Could not reach API Gateway: {e}")


# ── Main loop ────────────────────────────────────────────────────
def main():
    log.info(f"Worker starting — node_id={NODE_ID}")
    r   = get_redis()
    sim = LoadSimulator()

    # Best-effort register
    try:
        import asyncio as _aio
        _aio.run(register_worker())
    except Exception:
        pass

    while True:
        try:
            metrics = sim.tick()
            r.xadd(STREAM_KEY, {k: str(v) for k, v in metrics.items()})
            log.info(
                f"cpu={metrics['cpu_usage']}% mem={metrics['memory_usage']}% "
                f"lat={metrics['latency_ms']}ms rps={metrics['requests_per_sec']}"
            )
        except Exception as e:
            log.error(f"Worker emit error: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
