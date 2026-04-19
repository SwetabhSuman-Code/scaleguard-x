"""
ScaleGuard X - Autoscaler

Uses the phase 3 predictive scaler to combine:
  - current CPU utilization
  - stored forecast ranges from the prediction engine
  - stored spike probability for emergency handling

The runtime still degrades gracefully to dry-run mode when Docker access is
not available.
"""

from __future__ import annotations

import asyncio
import math
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
import docker
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autoscaler.models.predictive_scaler import PredictiveScaler, PredictiveScalerConfig
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

PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD', 'scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}"
    f":{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'scaleguard')}"
)

MIN_WORKERS = int(os.getenv("AUTOSCALER_MIN_WORKERS", 1))
MAX_WORKERS = int(os.getenv("AUTOSCALER_MAX_WORKERS", 8))
RUN_INTERVAL = int(os.getenv("AUTOSCALER_RUN_INTERVAL", 15))
RPS_PER_WORKER = float(os.getenv("AUTOSCALER_RPS_PER_WORKER", "300"))

_pg_cb = make_postgres_breaker("autoscaler")
_docker_cb = make_docker_breaker("autoscaler")


@dataclass
class PredictionSnapshot:
    predicted_rps: float = 0.0
    upper_bound: float = 0.0
    spike_probability: float = 0.0
    confidence: float = 0.0
    model_name: str = "none"


class StoredPredictionAdapter:
    """Expose the latest stored upper bound through the Prophet interface."""

    def predict_next_10_minutes(self, recent_data: dict) -> dict:
        return {"upper_bound": recent_data.get("predicted_utilization_upper", 0.0)}


class StoredSpikeAdapter:
    """Expose the latest stored spike probability through the LSTM interface."""

    def predict_spike_probability(self, recent_data: dict) -> tuple[float, float]:
        spike_probability = float(recent_data.get("spike_probability", 0.0))
        return spike_probability, max(0.0, 1.0 - spike_probability)


_predictive_scaler = PredictiveScaler(
    PredictiveScalerConfig(
        min_scaling_action=-3.0,
        max_scaling_action=3.0,
        min_decision_interval=max(float(RUN_INTERVAL), 15.0),
        min_scaling_magnitude=0.5,
    ),
    prophet_module=StoredPredictionAdapter(),
    lstm_module=StoredSpikeAdapter(),
)


def get_docker_client() -> Optional[docker.DockerClient]:
    """Return a Docker client appropriate for the current platform."""
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
        log.warning("running_in_dry_run_mode")
        return None


async def create_pool() -> asyncpg.Pool:
    for attempt in range(15):
        delay = min(2**attempt, 30)
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


async def get_average_cpu(pool: asyncpg.Pool) -> float:
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                value = await con.fetchval(
                    """SELECT AVG(cpu_usage)
                       FROM metrics
                       WHERE timestamp >= NOW() - INTERVAL '2 minutes'"""
                )
        return float(value or 0.0)
    except CircuitBreakerError as exc:
        log.warning("circuit_open_cpu_fetch", extra={"error": str(exc)})
        return 0.0


async def get_latest_prediction(pool: asyncpg.Pool) -> PredictionSnapshot:
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                row = await con.fetchrow(
                    """SELECT predicted_rps, upper_bound, spike_probability, confidence, model_name
                       FROM predictions
                       ORDER BY predicted_at DESC
                       LIMIT 1"""
                )
        if row is None:
            return PredictionSnapshot()
        return PredictionSnapshot(
            predicted_rps=float(row["predicted_rps"] or 0.0),
            upper_bound=float(row["upper_bound"] or row["predicted_rps"] or 0.0),
            spike_probability=float(row["spike_probability"] or 0.0),
            confidence=float(row["confidence"] or 0.0),
            model_name=str(row["model_name"] or "unknown"),
        )
    except CircuitBreakerError as exc:
        log.warning("circuit_open_prediction_fetch", extra={"error": str(exc)})
        return PredictionSnapshot()


def get_worker_containers(docker_client: docker.DockerClient) -> list:
    try:
        with _docker_cb:
            return docker_client.containers.list(
                filters={"label": "com.docker.compose.service=worker_cluster"}
            )
    except CircuitBreakerError as exc:
        log.warning("circuit_open_docker_list", extra={"error": str(exc)})
        return []
    except Exception as exc:
        log.warning("docker_list_failed", extra={"error": str(exc)})
        return []


def spawn_worker(
    docker_client: docker.DockerClient,
    worker_index: int,
    env_vars: dict,
) -> Optional[str]:
    try:
        with _docker_cb:
            container = docker_client.containers.run(
                "scaleguard-x-worker_cluster",
                detach=True,
                network="scaleguard-x_default",
                environment=[f"{k}={v}" for k, v in env_vars.items()]
                + [f"NODE_ID=worker-dynamic-{worker_index}"],
                labels={
                    "com.docker.compose.service": "worker_cluster",
                    "com.docker.compose.project": "scaleguard-x",
                    "scaleguard.dynamic": "true",
                    "scaleguard.role": "worker",
                },
                name=f"scaleguard-x-worker-dyn-{worker_index}",
            )
        log.info("worker_spawned", extra={"container_id": container.short_id})
        return container.short_id
    except CircuitBreakerError as exc:
        log.error("circuit_open_spawn", extra={"error": str(exc)})
        return None
    except Exception as exc:
        log.error("spawn_worker_failed", extra={"error": str(exc)})
        return None


def terminate_worker(docker_client: docker.DockerClient) -> bool:
    try:
        with _docker_cb:
            containers = docker_client.containers.list(filters={"label": "scaleguard.dynamic=true"})
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


async def sync_worker_registry(
    pool: asyncpg.Pool,
    docker_client: Optional[docker.DockerClient],
) -> None:
    if docker_client is None:
        return
    try:
        containers = get_worker_containers(docker_client)
        async with _pg_cb:
            async with pool.acquire() as con:
                await con.execute("UPDATE workers SET status='terminated' WHERE status='active'")
                for container in containers:
                    worker_id = container.name.replace("scaleguard-x-", "").replace("_", "-")
                    await con.execute(
                        """INSERT INTO workers (worker_id, container_id, status, last_heartbeat)
                           VALUES ($1, $2, 'active', NOW())
                           ON CONFLICT (worker_id) DO UPDATE
                               SET status='active',
                                   last_heartbeat=NOW(),
                                   container_id=EXCLUDED.container_id""",
                        worker_id,
                        container.short_id,
                    )
    except Exception as exc:
        log.warning("registry_sync_failed", extra={"error": str(exc)})


async def record_scaling_event(
    pool: asyncpg.Pool,
    action: str,
    previous: int,
    new: int,
    reason: str,
) -> None:
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                await con.execute(
                    """INSERT INTO scaling_events
                           (triggered_at, action, prev_replicas, new_replicas, reason)
                       VALUES ($1, $2, $3, $4, $5)""",
                    datetime.now(timezone.utc),
                    action,
                    previous,
                    new,
                    reason,
                )
    except Exception as exc:
        log.error("scaling_event_record_failed", extra={"error": str(exc)})


def scale_delta_to_target(current_count: int, action: float) -> int:
    if action < 0:
        return min(MAX_WORKERS, current_count + math.ceil(abs(action)))
    if action > 0:
        return max(MIN_WORKERS, current_count - math.ceil(action))
    return current_count


async def autoscale_cycle(
    pool: asyncpg.Pool,
    docker_client: Optional[docker.DockerClient],
) -> None:
    avg_cpu = await get_average_cpu(pool)
    prediction = await get_latest_prediction(pool)

    if docker_client is not None:
        containers = get_worker_containers(docker_client)
        current_count = len(containers) if containers else MIN_WORKERS
    else:
        current_count = MIN_WORKERS

    predicted_utilization_upper = 0.0
    if current_count > 0 and RPS_PER_WORKER > 0:
        predicted_utilization_upper = min(
            100.0,
            (prediction.upper_bound / (current_count * RPS_PER_WORKER)) * 100.0,
        )

    decision = _predictive_scaler.decide_scaling(
        current_utilization=avg_cpu,
        recent_data={
            "predicted_utilization_upper": predicted_utilization_upper,
            "spike_probability": prediction.spike_probability,
        },
        dt=float(RUN_INTERVAL),
    )

    target_count = scale_delta_to_target(current_count, decision.action)
    action_name = "no_change"
    if target_count > current_count:
        action_name = "scale_up"
    elif target_count < current_count:
        action_name = "scale_down"

    reason = (
        f"{decision.reason}; cpu={avg_cpu:.1f}; "
        f"predicted_rps={prediction.predicted_rps:.1f}; "
        f"upper_util={predicted_utilization_upper:.1f}; "
        f"spike_probability={prediction.spike_probability:.2f}; "
        f"model={prediction.model_name}"
    )

    log.info(
        "autoscale_cycle",
        extra={
            "avg_cpu": round(avg_cpu, 1),
            "predicted_rps": round(prediction.predicted_rps, 1),
            "predicted_utilization_upper": round(predicted_utilization_upper, 1),
            "spike_probability": round(prediction.spike_probability, 3),
            "workers": current_count,
            "target_workers": target_count,
            "decision_action": round(decision.action, 3),
            "reason": reason,
        },
    )

    if docker_client is not None:
        env_vars = {
            "REDIS_HOST": os.getenv("REDIS_HOST", "redis_queue"),
            "REDIS_PORT": os.getenv("REDIS_PORT", "6379"),
            "METRICS_STREAM_KEY": os.getenv("METRICS_STREAM_KEY", "metrics_stream"),
            "AGENT_INTERVAL": "5",
            "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        }
        while current_count < target_count:
            current_count += 1
            spawn_worker(docker_client, current_count, env_vars)
        while current_count > target_count:
            if terminate_worker(docker_client):
                current_count -= 1
            else:
                break

    await record_scaling_event(pool, action_name, current_count, target_count, reason)
    await sync_worker_registry(pool, docker_client)


async def main() -> None:
    log.info(
        "autoscaler_starting",
        extra={
            "interval_s": RUN_INTERVAL,
            "min_workers": MIN_WORKERS,
            "max_workers": MAX_WORKERS,
        },
    )
    pool = await create_pool()
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
