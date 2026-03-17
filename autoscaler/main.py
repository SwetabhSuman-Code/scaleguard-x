"""
ScaleGuard X — Autoscaler
Periodically checks:
  • latest prediction from predictions table
  • average CPU load across nodes (last 2 min)
  • current worker count from workers table
Decides to scale up or down using Docker SDK (via mounted /var/run/docker.sock).
Records every action in scaling_events table.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import docker
from dotenv import load_dotenv

load_dotenv()

# ── Config ───────────────────────────────────────────────────────
PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER','scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD','scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST','localhost')}"
    f":{os.getenv('POSTGRES_PORT','5432')}"
    f"/{os.getenv('POSTGRES_DB','scaleguard')}"
)

MIN_WORKERS   = int(os.getenv("AUTOSCALER_MIN_WORKERS", 1))
MAX_WORKERS   = int(os.getenv("AUTOSCALER_MAX_WORKERS", 8))
UP_THRESH     = float(os.getenv("AUTOSCALER_SCALE_UP_THRESHOLD", 0.75))   # fraction
DOWN_THRESH   = float(os.getenv("AUTOSCALER_SCALE_DOWN_THRESHOLD", 0.35))
RUN_INTERVAL  = int(os.getenv("AUTOSCALER_RUN_INTERVAL", 15))  # seconds

# The docker-compose service name of the worker (used to filter containers)
WORKER_IMAGE_LABEL = os.getenv("WORKER_SERVICE_NAME", "scaleguard-x-worker_cluster")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AUTOSCALER] %(levelname)s %(message)s",
)
log = logging.getLogger("autoscaler")

# ── Docker client ────────────────────────────────────────────────
def get_docker_client():
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        log.warning(f"Docker socket unavailable: {e} — scaling disabled")
        return None

# ── DB Pool ──────────────────────────────────────────────────────
async def create_pool() -> asyncpg.Pool:
    for attempt in range(15):
        try:
            pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=4)
            log.info("Connected to Postgres")
            return pool
        except Exception as e:
            log.warning(f"Postgres not ready (attempt {attempt+1}): {e}")
            await asyncio.sleep(4)
    raise RuntimeError("Cannot connect to Postgres")


# ── Fetch metrics ────────────────────────────────────────────────
async def get_average_cpu(pool: asyncpg.Pool) -> float:
    since = datetime.now(timezone.utc) - timedelta(minutes=2)
    async with pool.acquire() as con:
        val = await con.fetchval(
            "SELECT AVG(cpu_usage) FROM metrics WHERE timestamp >= $1", since
        )
    return float(val or 0.0)


async def get_latest_predicted_rps(pool: asyncpg.Pool) -> float:
    async with pool.acquire() as con:
        val = await con.fetchval(
            "SELECT predicted_rps FROM predictions ORDER BY predicted_at DESC LIMIT 1"
        )
    return float(val or 0.0)


async def get_active_worker_count(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as con:
        val = await con.fetchval(
            "SELECT COUNT(*) FROM workers WHERE status='active'"
        )
    return int(val or 0)


# ── Record scaling event ─────────────────────────────────────────
async def record_scaling_event(pool, action: str, prev: int, new: int, reason: str):
    async with pool.acquire() as con:
        await con.execute(
            """INSERT INTO scaling_events (triggered_at, action, prev_replicas, new_replicas, reason)
               VALUES ($1, $2, $3, $4, $5)""",
            datetime.now(timezone.utc), action, prev, new, reason,
        )


# ── Get current running worker containers ────────────────────────
def get_worker_containers(docker_client):
    """Return all running containers whose name or image matches the worker service."""
    try:
        containers = docker_client.containers.list(
            filters={"label": f"com.docker.compose.service=worker_cluster"}
        )
        return containers
    except Exception as e:
        log.warning(f"Could not list containers: {e}")
        return []


# ── Scale up: start a new worker container ───────────────────────
def spawn_worker(docker_client, worker_index: int, env_vars: dict) -> str | None:
    """Launch a new worker_cluster container and return its short ID."""
    try:
        image_name = "scaleguard-x-worker_cluster"
        env_list = [f"{k}={v}" for k, v in env_vars.items()]
        container = docker_client.containers.run(
            image_name,
            detach=True,
            network="scaleguard-x_default",
            environment=env_list + [f"NODE_ID=worker-dynamic-{worker_index}"],
            labels={
                "com.docker.compose.service": "worker_cluster",
                "com.docker.compose.project": "scaleguard-x",
                "scaleguard.dynamic": "true",
            },
            name=f"scaleguard-x-worker-dyn-{worker_index}",
        )
        log.info(f"Spawned container {container.short_id} (worker-dynamic-{worker_index})")
        return container.short_id
    except Exception as e:
        log.error(f"Failed to spawn worker: {e}")
        return None


# ── Scale down: stop the most recently added dynamic container ───
def terminate_worker(docker_client) -> bool:
    """Stop and remove one dynamic worker container."""
    try:
        containers = docker_client.containers.list(
            filters={"label": "scaleguard.dynamic=true"}
        )
        if not containers:
            return False
        target = containers[-1]
        target.stop(timeout=5)
        target.remove()
        log.info(f"Terminated dynamic container {target.short_id}")
        return True
    except Exception as e:
        log.error(f"Failed to terminate worker: {e}")
        return False


# ── Sync worker registry from running containers ─────────────────
async def sync_worker_registry(pool: asyncpg.Pool, docker_client):
    """Update the workers table based on currently running containers."""
    if docker_client is None:
        return
    try:
        containers = docker_client.containers.list(
            filters={"label": "com.docker.compose.service=worker_cluster"}
        )
        async with pool.acquire() as con:
            # Mark all existing workers as terminated first
            await con.execute("UPDATE workers SET status='terminated' WHERE status='active'")
            # Re-register active ones
            for c in containers:
                node_id = (c.labels.get("NODE_ID") or
                           c.name.replace("scaleguard-x-", "").replace("_", "-"))
                await con.execute(
                    """INSERT INTO workers (worker_id, container_id, status, last_heartbeat)
                       VALUES ($1, $2, 'active', NOW())
                       ON CONFLICT (worker_id) DO UPDATE
                           SET status='active', last_heartbeat=NOW(),
                               container_id=EXCLUDED.container_id""",
                    node_id, c.short_id,
                )
    except Exception as e:
        log.warning(f"Worker registry sync error: {e}")


# ── Scaling logic ────────────────────────────────────────────────
async def autoscale_cycle(pool: asyncpg.Pool, docker_client):
    avg_cpu       = await get_average_cpu(pool)
    predicted_rps = await get_latest_predicted_rps(pool)
    current_count = len(get_worker_containers(docker_client)) if docker_client else 1

    # A simplified utilization score: blend CPU fraction + RPS projection
    # RPS > 300 is considered high load for this simulation
    rps_fraction  = min(1.0, predicted_rps / 300.0)
    cpu_fraction  = min(1.0, avg_cpu / 100.0)
    utilization   = 0.6 * cpu_fraction + 0.4 * rps_fraction

    log.info(
        f"Cycle: cpu_avg={avg_cpu:.1f}% pred_rps={predicted_rps:.1f} "
        f"utilization={utilization:.2f} workers={current_count}"
    )

    action    = "no_change"
    new_count = current_count

    if utilization >= UP_THRESH and current_count < MAX_WORKERS:
        new_count = min(current_count + 1, MAX_WORKERS)
        action    = "scale_up"
        reason    = (
            f"utilization={utilization:.2f} >= {UP_THRESH} "
            f"(cpu={avg_cpu:.1f}%, rps={predicted_rps:.1f})"
        )
        log.info(f"Scaling UP: {current_count} → {new_count}  [{reason}]")
        if docker_client:
            spawn_worker(docker_client, new_count, {
                "REDIS_HOST":        os.getenv("REDIS_HOST", "redis_queue"),
                "REDIS_PORT":        os.getenv("REDIS_PORT", "6379"),
                "METRICS_STREAM_KEY": os.getenv("METRICS_STREAM_KEY", "metrics_stream"),
                "AGENT_INTERVAL":    "5",
            })

    elif utilization <= DOWN_THRESH and current_count > MIN_WORKERS:
        new_count = max(current_count - 1, MIN_WORKERS)
        action    = "scale_down"
        reason    = (
            f"utilization={utilization:.2f} <= {DOWN_THRESH} "
            f"(cpu={avg_cpu:.1f}%, rps={predicted_rps:.1f})"
        )
        log.info(f"Scaling DOWN: {current_count} → {new_count}  [{reason}]")
        if docker_client:
            terminate_worker(docker_client)

    else:
        reason = f"utilization={utilization:.2f} within bounds — no change"
        log.info(reason)

    await record_scaling_event(pool, action, current_count, new_count, reason)
    await sync_worker_registry(pool, docker_client)


# ── Main loop ────────────────────────────────────────────────────
async def main():
    log.info(f"Autoscaler starting  interval={RUN_INTERVAL}s  min={MIN_WORKERS}  max={MAX_WORKERS}")
    pool          = await create_pool()
    docker_client = get_docker_client()
    if docker_client is None:
        log.warning("Running in DRY-RUN mode — no Docker socket available")

    while True:
        try:
            await autoscale_cycle(pool, docker_client)
        except Exception as e:
            log.error(f"Autoscaler cycle error: {e}", exc_info=True)
        await asyncio.sleep(RUN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
