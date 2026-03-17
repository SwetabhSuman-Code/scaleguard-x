"""
ScaleGuard X — Metrics Ingestion Service
Reads batches from the Redis Stream and writes them to Postgres.
Pipeline:  Redis Stream  →  asyncio batch consumer  →  Postgres (batch INSERT)
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
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
REDIS_URL    = f"redis://{os.getenv('REDIS_HOST','localhost')}:{os.getenv('REDIS_PORT','6379')}"
STREAM_KEY   = os.getenv("METRICS_STREAM_KEY", "metrics_stream")
BATCH_SIZE   = int(os.getenv("INGESTION_BATCH_SIZE", 100))
POLL_WAIT_MS = int(os.getenv("INGESTION_INTERVAL", 2)) * 1000  # Redis XREAD block timeout

CONSUMER_GROUP = "ingestion_group"
CONSUMER_NAME  = "ingestion_service_1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [INGESTION] %(levelname)s %(message)s",
)
log = logging.getLogger("ingestion_service")

# ── DB Pool ──────────────────────────────────────────────────────
async def create_db_pool() -> asyncpg.Pool:
    for attempt in range(15):
        try:
            pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=8)
            log.info("Connected to Postgres")
            return pool
        except Exception as e:
            log.warning(f"Postgres not ready (attempt {attempt+1}): {e}")
            await asyncio.sleep(4)
    raise RuntimeError("Failed to connect to Postgres")

# ── Redis ────────────────────────────────────────────────────────
async def create_redis(url: str) -> aioredis.Redis:
    for attempt in range(15):
        try:
            r = aioredis.from_url(url, decode_responses=True)
            await r.ping()
            log.info("Connected to Redis")
            return r
        except Exception as e:
            log.warning(f"Redis not ready (attempt {attempt+1}): {e}")
            await asyncio.sleep(4)
    raise RuntimeError("Failed to connect to Redis")

# ── Ensure consumer group exists ─────────────────────────────────
async def ensure_consumer_group(r: aioredis.Redis):
    try:
        await r.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        log.info(f"Created consumer group '{CONSUMER_GROUP}'")
    except Exception as e:
        if "BUSYGROUP" in str(e):
            log.info("Consumer group already exists")
        else:
            log.warning(f"Consumer group creation: {e}")

# ── Parse a raw Redis stream entry into metric dict ──────────────
def parse_entry(entry_data: dict) -> dict | None:
    try:
        return {
            "node_id":          entry_data["node_id"],
            "timestamp":        datetime.fromtimestamp(
                                    float(entry_data["timestamp"]), tz=timezone.utc
                                ),
            "cpu_usage":        float(entry_data["cpu_usage"]),
            "memory_usage":     float(entry_data["memory_usage"]),
            "latency_ms":       float(entry_data["latency_ms"]),
            "requests_per_sec": float(entry_data["requests_per_sec"]),
            "disk_usage":       float(entry_data["disk_usage"]),
        }
    except (KeyError, ValueError) as e:
        log.warning(f"Invalid entry skipped: {e} — data={entry_data}")
        return None

# ── Batch write to Postgres ──────────────────────────────────────
INSERT_SQL = """
    INSERT INTO metrics (node_id, timestamp, cpu_usage, memory_usage,
                         latency_ms, requests_per_sec, disk_usage)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT DO NOTHING
"""

async def write_batch(pool: asyncpg.Pool, records: list[dict]):
    rows = [
        (r["node_id"], r["timestamp"], r["cpu_usage"], r["memory_usage"],
         r["latency_ms"], r["requests_per_sec"], r["disk_usage"])
        for r in records
    ]
    async with pool.acquire() as con:
        await con.executemany(INSERT_SQL, rows)
    log.info(f"Wrote {len(rows)} metric records to Postgres")

# ── Main consumer loop ────────────────────────────────────────────
async def consume(pool: asyncpg.Pool, r: aioredis.Redis):
    await ensure_consumer_group(r)
    log.info(f"Consuming from stream '{STREAM_KEY}' (batch={BATCH_SIZE})")

    while True:
        try:
            # Read up to BATCH_SIZE messages from the stream
            results = await r.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=BATCH_SIZE,
                block=POLL_WAIT_MS,
            )

            if not results:
                continue  # nothing new — loop

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
                # Acknowledge processed messages
                await r.xack(STREAM_KEY, CONSUMER_GROUP, *msg_ids)

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Ingestion error: {e}", exc_info=True)
            await asyncio.sleep(2)

# ── Entry ────────────────────────────────────────────────────────
async def main():
    pool = await create_db_pool()
    r    = await create_redis(REDIS_URL)
    await consume(pool, r)

if __name__ == "__main__":
    asyncio.run(main())
