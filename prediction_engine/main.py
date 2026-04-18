"""
ScaleGuard X — Predictive Load Forecasting Engine

Fetches the last 60 min of RPS data from Postgres, fits ARIMA,
stores a 10-minute-ahead prediction. Falls back to EMA if ARIMA fails.

Phase 1 upgrades:
  Fix #4 — Circuit breaker on DB connections
  Fix #5 — Structured JSON logging
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import numpy as np
from dotenv import load_dotenv

# ── Shared lib ────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.circuit_breaker import CircuitBreakerError, make_postgres_breaker
from lib.logging_config import get_logger, setup_json_logging
from lib.prometheus_metrics import setup_metrics, setup_metrics_server

load_dotenv()
setup_json_logging("prediction_engine")
setup_metrics("prediction_engine")
setup_metrics_server(port=9093)
log = get_logger("prediction_engine")

# ── Config ────────────────────────────────────────────────────────
PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD', 'scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}"
    f":{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'scaleguard')}"
)
HORIZON_MINUTES = int(os.getenv("PREDICTION_HORIZON_MINUTES", 10))
HISTORY_MINUTES = int(os.getenv("PREDICTION_HISTORY_MINUTES", 60))
RUN_INTERVAL    = int(os.getenv("PREDICTION_RUN_INTERVAL", 30))   # seconds

# ── Circuit breaker ───────────────────────────────────────────────
_pg_cb = make_postgres_breaker("prediction_engine")


# ── DB Pool — exponential back-off ───────────────────────────────
async def create_pool() -> asyncpg.Pool:
    for attempt in range(15):
        delay = min(2 ** attempt, 30)
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


# ── Fetch historical RPS ──────────────────────────────────────────
async def fetch_rps_series(pool: asyncpg.Pool) -> list[float]:
    """Return per-minute average RPS for the last HISTORY_MINUTES minutes."""
    since = datetime.now(timezone.utc) - timedelta(minutes=HISTORY_MINUTES)
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                rows = await con.fetch(
                    """SELECT AVG(requests_per_sec) AS rps
                       FROM metrics
                       WHERE timestamp >= $1
                       GROUP BY date_trunc('minute', timestamp)
                       ORDER BY date_trunc('minute', timestamp)""",
                    since,
                )
        return [float(r["rps"]) for r in rows if r["rps"] is not None]
    except CircuitBreakerError as exc:
        log.warning("circuit_open_rps_fetch", extra={"error": str(exc)})
        return []


# ── ARIMA Prediction ──────────────────────────────────────────────
def arima_predict(series: list[float], steps: int) -> tuple[float, float]:
    """
    Fit ARIMA(2,1,2) on *series* and return (predicted_rps, confidence).
    Falls back to EMA if statsmodels is unavailable or fitting fails.
    """
    try:
        import warnings

        from statsmodels.tsa.arima.model import ARIMA

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model    = ARIMA(series, order=(2, 1, 2))
            result   = model.fit()
            forecast = result.forecast(steps=steps)
            predicted = max(0.0, float(np.mean(forecast)))
            conf_int  = result.get_forecast(steps=steps).conf_int(alpha=0.2)
            width     = float(np.mean(conf_int[:, 1] - conf_int[:, 0]))
            confidence = max(0.0, min(1.0, 1.0 - width / (predicted + 1e-9) * 0.1))
        return round(predicted, 2), round(confidence, 3)
    except Exception as exc:
        log.warning("arima_failed_ema_fallback", extra={"error": str(exc)})
        return ema_predict(series, steps)


# ── EMA Fallback ──────────────────────────────────────────────────
def ema_predict(series: list[float], steps: int) -> tuple[float, float]:
    """Exponential Moving Average simple forecast."""
    alpha = 0.3
    ema   = series[0]
    for val in series[1:]:
        ema = alpha * val + (1 - alpha) * ema
    trend     = (ema - np.mean(series[: len(series) // 2])) / max(1, len(series) // 2)
    predicted = max(0.0, ema + trend * steps)
    return round(predicted, 2), 0.6


# ── Store Prediction ──────────────────────────────────────────────
INSERT_SQL = """
    INSERT INTO predictions (predicted_at, horizon_minutes, predicted_rps,
                             predicted_cpu, confidence)
    VALUES ($1, $2, $3, $4, $5)
"""


async def store_prediction(pool: asyncpg.Pool, rps: float, conf: float) -> None:
    """Persist a prediction row to Postgres."""
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                await con.execute(
                    INSERT_SQL,
                    datetime.now(timezone.utc),
                    HORIZON_MINUTES,
                    rps,
                    None,   # predicted_cpu — future enhancement
                    conf,
                )
        log.info(
            "prediction_stored",
            extra={
                "predicted_rps":      rps,
                "confidence":         conf,
                "horizon_minutes":    HORIZON_MINUTES,
            },
        )
    except CircuitBreakerError as exc:
        log.warning("circuit_open_store", extra={"error": str(exc)})
    except Exception as exc:
        log.error("prediction_store_failed", extra={"error": str(exc)})


# ── Main loop ─────────────────────────────────────────────────────
async def main() -> None:
    log.info("prediction_engine_starting", extra={"interval_s": RUN_INTERVAL})
    pool = await create_pool()

    while True:
        try:
            series = await fetch_rps_series(pool)
            if len(series) < 5:
                log.info(
                    "insufficient_data",
                    extra={"data_points": len(series), "minimum_required": 5},
                )
            else:
                rps, conf = arima_predict(series, HORIZON_MINUTES)
                log.info(
                    "forecast_produced",
                    extra={
                        "horizon_minutes":  HORIZON_MINUTES,
                        "predicted_rps":    rps,
                        "confidence":       conf,
                        "data_points_used": len(series),
                    },
                )
                await store_prediction(pool, rps, conf)
        except Exception as exc:
            log.error("prediction_cycle_error", extra={"error": str(exc)}, exc_info=True)
        await asyncio.sleep(RUN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
