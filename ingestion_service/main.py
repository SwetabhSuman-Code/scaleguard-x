"""
ScaleGuard X — Metrics Ingestion Service

Reads batches from the Redis Stream and writes them to Postgres.
Pipeline:  Redis Stream → asyncio batch consumer → Postgres (batch INSERT)

Phase 1 upgrades:
  Fix #4 — Circuit breakers on DB and Redis connections
  Fix #5 — Structured JSON logging
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
import redis.asyncio as aioredis
from dotenv import load_dotenv

# ── Shared lib ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.circuit_breaker import CircuitBreakerError, make_postgres_breaker, make_redis_breaker
from lib.logging_config import get_logger, setup_json_logging
from lib.prometheus_metrics import setup_metrics, setup_metrics_server

load_dotenv()
setup_json_logging("ingestion_service")
setup_metrics("ingestion_service")
setup_metrics_server(port=9091)
log = get_logger("ingestion_service")

# ── Config ────────────────────────────────────────────────────────
PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD', 'scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}"
    f":{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'scaleguard')}"
)
REDIS_URL = f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}"
STREAM_KEY = os.getenv("METRICS_STREAM_KEY", "metrics_stream")
BATCH_SIZE = int(os.getenv("INGESTION_BATCH_SIZE", 100))
POLL_WAIT_MS = int(os.getenv("INGESTION_INTERVAL", 2)) * 1000

CONSUMER_GROUP = "ingestion_group"
CONSUMER_NAME = "ingestion_service_1"

# ── Circuit breakers ──────────────────────────────────────────────
_pg_cb = make_postgres_breaker("ingestion_service")
_redis_cb = make_redis_breaker("ingestion_service")


# ── DB Pool — exponential back-off ───────────────────────────────
async def create_db_pool() -> asyncpg.Pool:
    for attempt in range(15):
        delay = min(2**attempt, 30)
        try:
            pool = await asyncpg.create_pool(
                PG_DSN,
                min_size=int(os.getenv("PG_POOL_MIN", 2)),
                max_size=int(os.getenv("PG_POOL_MAX", 10)),
            )
            log.info("postgres_connected")
            return pool
        except Exception as exc:
            log.warning(
                "postgres_not_ready",
                extra={"attempt": attempt + 1, "retry_in_s": delay, "error": str(exc)},
            )
            await asyncio.sleep(delay)
    raise RuntimeError("Failed to connect to Postgres after 15 attempts")


# ── Redis — exponential back-off ─────────────────────────────────
async def create_redis(url: str) -> aioredis.Redis:
    for attempt in range(15):
        delay = min(2**attempt, 30)
        try:
            r = aioredis.from_url(url, decode_responses=True)
            await r.ping()
            log.info("redis_connected")
            return r
        except Exception as exc:
            log.warning(
                "redis_not_ready",
                extra={"attempt": attempt + 1, "retry_in_s": delay, "error": str(exc)},
            )
            await asyncio.sleep(delay)
    raise RuntimeError("Failed to connect to Redis after 15 attempts")


# ── Ensure consumer group exists ─────────────────────────────────
async def ensure_consumer_group(r: aioredis.Redis) -> None:
    try:
        async with _redis_cb:
            await r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        log.info("consumer_group_created", extra={"group": CONSUMER_GROUP})
    except CircuitBreakerError as exc:
        log.warning("circuit_open_group_create", extra={"error": str(exc)})
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            log.info("consumer_group_exists", extra={"group": CONSUMER_GROUP})
        else:
            log.warning("consumer_group_create_warning", extra={"error": str(exc)})


# ── Parse a raw Redis stream entry ───────────────────────────────
def parse_entry(entry_data: dict) -> Optional[dict]:
    """Return a cleaned metric dict or None if the entry is malformed."""
    try:
        return {
            "node_id": entry_data["node_id"],
            "timestamp": datetime.fromtimestamp(float(entry_data["timestamp"]), tz=timezone.utc),
            "cpu_usage": float(entry_data["cpu_usage"]),
            "memory_usage": float(entry_data["memory_usage"]),
            "latency_ms": float(entry_data["latency_ms"]),
            "requests_per_sec": float(entry_data["requests_per_sec"]),
            "disk_usage": float(entry_data["disk_usage"]),
        }
    except (KeyError, ValueError) as exc:
        log.warning("invalid_entry_skipped", extra={"error": str(exc)})
        return None


# ── Batch write to Postgres ───────────────────────────────────────
INSERT_SQL = """
    INSERT INTO metrics (node_id, timestamp, cpu_usage, memory_usage,
                         latency_ms, requests_per_sec, disk_usage)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT DO NOTHING
"""


async def write_batch(pool: asyncpg.Pool, records: list[dict]) -> None:
    """Write a batch of metric records to Postgres."""
    rows = [
        (
            r["node_id"],
            r["timestamp"],
            r["cpu_usage"],
            r["memory_usage"],
            r["latency_ms"],
            r["requests_per_sec"],
            r["disk_usage"],
        )
        for r in records
    ]
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                await con.executemany(INSERT_SQL, rows)
        log.info("batch_written", extra={"count": len(rows)})
    except CircuitBreakerError as exc:
        log.warning("circuit_open_batch_write", extra={"error": str(exc)})
    except Exception as exc:
        log.error("batch_write_failed", extra={"error": str(exc), "count": len(rows)})


# ── Main consumer loop ────────────────────────────────────────────
async def consume(pool: asyncpg.Pool, r: aioredis.Redis) -> None:
    await ensure_consumer_group(r)
    log.info(
        "consumer_started",
        extra={"stream": STREAM_KEY, "batch_size": BATCH_SIZE},
    )

    while True:
        try:
            async with _redis_cb:
                results = await r.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams={STREAM_KEY: ">"},
                    count=BATCH_SIZE,
                    block=POLL_WAIT_MS,
                )

            if not results:
                continue

            batch: list[dict] = []
            msg_ids: list[str] = []

            for _stream, messages in results:
                for msg_id, data in messages:
                    parsed = parse_entry(data)
                    if parsed:
                        batch.append(parsed)
                        msg_ids.append(msg_id)

            if batch:
                await write_batch(pool, batch)
                async with _redis_cb:
                    await r.xack(STREAM_KEY, CONSUMER_GROUP, *msg_ids)

        except CircuitBreakerError as exc:
            log.warning("circuit_open_consume", extra={"error": str(exc)})
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("ingestion_error", extra={"error": str(exc)}, exc_info=True)
            await asyncio.sleep(2)


# ── Entry ─────────────────────────────────────────────────────────
async def main() -> None:
    log.info("ingestion_service_starting")
    pool = await create_db_pool()
    r = await create_redis(REDIS_URL)
    await consume(pool, r)


if __name__ == "__main__":
    asyncio.run(main())
