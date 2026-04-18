"""
ScaleGuard X — Autoscaler
Periodically checks:
  • latest prediction from predictions table
  • average CPU load across nodes (last 2 min)
  • current worker count from workers table
Decides to scale up or down using Docker SDK.

Fix #3: get_docker_client() detects platform and picks the right socket.
Fix #4: Circuit breaker on all DB calls; exponential back-off on connect.
Fix #5: Structured JSON logging via lib.logging_config.
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import asyncpg
import docker
from dotenv import load_dotenv

# ── Shared lib (add repo root to path so Docker containers can find it) ──
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.circuit_breaker import (
    CircuitBreakerError,
    make_docker_breaker,
    make_postgres_breaker,
)
from lib.logging_config import get_logger, setup_json_logging
from lib.prometheus_metrics import setup_metrics, setup_metrics_server

load_dotenv()

setup_json_logging("autoscaler")
setup_metrics("autoscaler")
setup_metrics_server(port=9094)
log = get_logger("autoscaler")

# ── Config ───────────────────────────────────────────────────────
PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD', 'scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}"
    f":{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'scaleguard')}"
)

MIN_WORKERS   = int(os.getenv("AUTOSCALER_MIN_WORKERS", 1))
MAX_WORKERS   = int(os.getenv("AUTOSCALER_MAX_WORKERS", 8))
UP_THRESH     = float(os.getenv("AUTOSCALER_SCALE_UP_THRESHOLD", 0.75))
DOWN_THRESH   = float(os.getenv("AUTOSCALER_SCALE_DOWN_THRESHOLD", 0.35))
RUN_INTERVAL  = int(os.getenv("AUTOSCALER_RUN_INTERVAL", 15))  # seconds

WORKER_SERVICE_NAME = os.getenv("WORKER_SERVICE_NAME", "scaleguard-x-worker_cluster")

# ── Circuit breakers ─────────────────────────────────────────────
_pg_cb     = make_postgres_breaker("autoscaler")
_docker_cb = make_docker_breaker("autoscaler")


# ── Issue #3 — Cross-platform Docker client ──────────────────────
def get_docker_client() -> Optional[docker.DockerClient]:
    """
    Return a Docker client appropriate for the current platform.
    - Windows   → named pipe (npipe)
    - macOS/Linux → unix socket via docker.from_env()
    Returns None (and logs a warning) if the socket is unavailable.
    """
    system = platform.system()
    try:
        if system == "Windows":
            client = docker.DockerClient(base_url="npipe:////./pipe/docker_engine")
        else:
            client = docker.from_env()

        client.ping()
        log.info("docker_client_connected", extra={"platform": system})
        return client
    except Exception as exc:
        log.warning(
            "docker_socket_unavailable",
            extra={"platform": system, "error": str(exc)},
        )
        log.warning("Running in DRY-RUN mode — scaling decisions will be logged only")
        return None


# ── DB Pool — exponential back-off ───────────────────────────────
async def create_pool() -> asyncpg.Pool:
    """Connect to Postgres with exponential back-off (up to ~4 min total)."""
    for attempt in range(15):
        delay = min(2 ** attempt, 30)  # 1, 2, 4, 8, 16, 30, 30 ...
        try:
            pool = await asyncpg.create_pool(
                PG_DSN,
                min_size=int(os.getenv("PG_POOL_MIN", 2)),
                max_size=int(os.getenv("PG_POOL_MAX", 4)),
            )
            log.info("postgres_connected")
            return pool
        except Exception as exc:
            log.warning(
                "postgres_not_ready",
                extra={"attempt": attempt + 1, "retry_in_s": delay, "error": str(exc)},
            )
            await asyncio.sleep(delay)
    raise RuntimeError("Cannot connect to Postgres after 15 attempts")


# ── Fetch metrics (circuit-breaker protected) ─────────────────────
async def get_average_cpu(pool: asyncpg.Pool) -> float:
    """Average CPU across all nodes for the last 2 minutes."""
    since = datetime.now(timezone.utc) - timedelta(minutes=2)
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                val = await con.fetchval(
                    "SELECT AVG(cpu_usage) FROM metrics WHERE timestamp >= $1", since
                )
        return float(val or 0.0)
    except CircuitBreakerError as exc:
        log.warning("circuit_open_cpu_fetch", extra={"error": str(exc)})
        return 0.0


async def get_latest_predicted_rps(pool: asyncpg.Pool) -> float:
    """Most recent RPS prediction from the predictions table."""
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                val = await con.fetchval(
                    "SELECT predicted_rps FROM predictions ORDER BY predicted_at DESC LIMIT 1"
                )
        return float(val or 0.0)
    except CircuitBreakerError as exc:
        log.warning("circuit_open_rps_fetch", extra={"error": str(exc)})
        return 0.0


async def get_active_worker_count(pool: asyncpg.Pool) -> int:
    """Worker count from DB registry."""
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                val = await con.fetchval(
                    "SELECT COUNT(*) FROM workers WHERE status='active'"
                )
        return int(val or 0)
    except CircuitBreakerError as exc:
        log.warning("circuit_open_worker_count", extra={"error": str(exc)})
        return MIN_WORKERS


# ── Record scaling event ─────────────────────────────────────────
async def record_scaling_event(
    pool: asyncpg.Pool,
    action: str,
    prev: int,
    new: int,
    reason: str,
) -> None:
    """Persist autoscaling decision to scaling_events table."""
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                await con.execute(
                    """INSERT INTO scaling_events
                           (triggered_at, action, prev_replicas, new_replicas, reason)
                       VALUES ($1, $2, $3, $4, $5)""",
                    datetime.now(timezone.utc), action, prev, new, reason,
                )
    except (CircuitBreakerError, Exception) as exc:
        log.error("scaling_event_record_failed", extra={"error": str(exc)})


# ── Get current running worker containers ────────────────────────
def get_worker_containers(docker_client: docker.DockerClient) -> list:
    """Return all running containers with the worker_cluster service label."""
    try:
        with _docker_cb:
            containers = docker_client.containers.list(
                filters={"label": "com.docker.compose.service=worker_cluster"}
            )
        return containers
    except CircuitBreakerError as exc:
        log.warning("circuit_open_docker_list", extra={"error": str(exc)})
        return []
    except Exception as exc:
        log.warning("docker_list_failed", extra={"error": str(exc)})
        return []


# ── Scale up: start a new worker container ───────────────────────
def spawn_worker(
    docker_client: docker.DockerClient,
    worker_index: int,
    env_vars: dict,
) -> Optional[str]:
    """Launch a new worker_cluster container and return its short ID."""
    try:
        with _docker_cb:
            image_name = "scaleguard-x-worker_cluster"
            env_list   = [f"{k}={v}" for k, v in env_vars.items()]
            container  = docker_client.containers.run(
                image_name,
                detach=True,
                network="scaleguard-x_default",
                environment=env_list + [f"NODE_ID=worker-dynamic-{worker_index}"],
                labels={
                    "com.docker.compose.service":  "worker_cluster",
                    "com.docker.compose.project":  "scaleguard-x",
                    "scaleguard.dynamic":           "true",
                    "scaleguard.role":              "worker",
                },
                name=f"scaleguard-x-worker-dyn-{worker_index}",
            )
        log.info(
            "worker_spawned",
            extra={
                "container_id": container.short_id,
                "worker_index": worker_index,
            },
        )
        return container.short_id
    except CircuitBreakerError as exc:
        log.error("circuit_open_spawn", extra={"error": str(exc)})
        return None
    except Exception as exc:
        log.error("spawn_worker_failed", extra={"error": str(exc)})
        return None


# ── Scale down: stop the most recently added dynamic container ───
def terminate_worker(docker_client: docker.DockerClient) -> bool:
    """Stop and remove one dynamic worker container."""
    try:
        with _docker_cb:
            containers = docker_client.containers.list(
                filters={"label": "scaleguard.dynamic=true"}
            )
            if not containers:
                return False
            target = containers[-1]
            target.stop(timeout=10)
            target.remove()
        log.info("worker_terminated", extra={"container_id": target.short_id})
        return True
    except CircuitBreakerError as exc:
        log.error("circuit_open_terminate", extra={"error": str(exc)})
        return False
    except Exception as exc:
        log.error("terminate_worker_failed", extra={"error": str(exc)})
        return False


# ── Sync worker registry from running containers ─────────────────
async def sync_worker_registry(
    pool: asyncpg.Pool,
    docker_client: Optional[docker.DockerClient],
) -> None:
    """Update the workers table based on currently running containers."""
    if docker_client is None:
        return
    try:
        containers = get_worker_containers(docker_client)
        async with _pg_cb:
            async with pool.acquire() as con:
                await con.execute("UPDATE workers SET status='terminated' WHERE status='active'")
                for c in containers:
                    node_id = (
                        c.labels.get("NODE_ID")
                        or c.name.replace("scaleguard-x-", "").replace("_", "-")
                    )
                    await con.execute(
                        """INSERT INTO workers (worker_id, container_id, status, last_heartbeat)
                           VALUES ($1, $2, 'active', NOW())
                           ON CONFLICT (worker_id) DO UPDATE
                               SET status='active', last_heartbeat=NOW(),
                                   container_id=EXCLUDED.container_id""",
                        node_id, c.short_id,
                    )
    except (CircuitBreakerError, Exception) as exc:
        log.warning("registry_sync_failed", extra={"error": str(exc)})


# ── Scaling logic ────────────────────────────────────────────────
async def autoscale_cycle(
    pool: asyncpg.Pool,
    docker_client: Optional[docker.DockerClient],
) -> None:
    """Single autoscaling evaluation cycle."""
    avg_cpu       = await get_average_cpu(pool)
    predicted_rps = await get_latest_predicted_rps(pool)

    if docker_client:
        containers    = get_worker_containers(docker_client)
        current_count = len(containers) if containers else MIN_WORKERS
    else:
        current_count = MIN_WORKERS

    # Utilization score: 60% CPU + 40% RPS fraction
    rps_fraction = min(1.0, predicted_rps / 300.0)
    cpu_fraction = min(1.0, avg_cpu / 100.0)
    utilization  = 0.6 * cpu_fraction + 0.4 * rps_fraction

    log.info(
        "autoscale_cycle",
        extra={
            "avg_cpu": round(avg_cpu, 1),
            "predicted_rps": round(predicted_rps, 1),
            "utilization": round(utilization, 3),
            "workers": current_count,
        },
    )

    action    = "no_change"
    new_count = current_count
    reason: str

    if utilization >= UP_THRESH and current_count < MAX_WORKERS:
        new_count = min(current_count + 1, MAX_WORKERS)
        action    = "scale_up"
        reason    = (
            f"utilization={utilization:.2f} >= {UP_THRESH} "
            f"(cpu={avg_cpu:.1f}%, rps={predicted_rps:.1f})"
        )
        log.info("scaling_up", extra={"from": current_count, "to": new_count, "reason": reason})
        if docker_client:
            spawn_worker(docker_client, new_count, {
                "REDIS_HOST":         os.getenv("REDIS_HOST", "redis_queue"),
                "REDIS_PORT":         os.getenv("REDIS_PORT", "6379"),
                "METRICS_STREAM_KEY": os.getenv("METRICS_STREAM_KEY", "metrics_stream"),
                "AGENT_INTERVAL":     "5",
                "LOG_LEVEL":          os.getenv("LOG_LEVEL", "INFO"),
            })

    elif utilization <= DOWN_THRESH and current_count > MIN_WORKERS:
        new_count = max(current_count - 1, MIN_WORKERS)
        action    = "scale_down"
        reason    = (
            f"utilization={utilization:.2f} <= {DOWN_THRESH} "
            f"(cpu={avg_cpu:.1f}%, rps={predicted_rps:.1f})"
        )
        log.info("scaling_down", extra={"from": current_count, "to": new_count, "reason": reason})
        if docker_client:
            terminate_worker(docker_client)

    else:
        reason = f"utilization={utilization:.2f} within bounds — no change"
        log.info("no_scaling_needed", extra={"utilization": round(utilization, 3)})

    await record_scaling_event(pool, action, current_count, new_count, reason)
    await sync_worker_registry(pool, docker_client)


# ── Main loop ────────────────────────────────────────────────────
async def main() -> None:
    log.info(
        "autoscaler_starting",
        extra={
            "interval_s": RUN_INTERVAL,
            "min_workers": MIN_WORKERS,
            "max_workers": MAX_WORKERS,
        },
    )
    pool          = await create_pool()
    docker_client = get_docker_client()
    if docker_client is None:
        log.warning("dry_run_mode_active")

    while True:
        try:
            await autoscale_cycle(pool, docker_client)
        except Exception as exc:
            log.error("autoscale_cycle_error", extra={"error": str(exc)}, exc_info=True)
        await asyncio.sleep(RUN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
