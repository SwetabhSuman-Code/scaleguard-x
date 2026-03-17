"""
ScaleGuard X — Predictive Load Forecasting Engine
Fetches the last 60 minutes of RPS data from Postgres,
fits a simple ARIMA model, and stores a 10-minute-ahead prediction.
Falls back to exponential moving average if statsmodels ARIMA fails.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import numpy as np
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
HORIZON_MINUTES = int(os.getenv("PREDICTION_HORIZON_MINUTES", 10))
HISTORY_MINUTES = int(os.getenv("PREDICTION_HISTORY_MINUTES", 60))
RUN_INTERVAL    = int(os.getenv("PREDICTION_RUN_INTERVAL", 30))  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PREDICT] %(levelname)s %(message)s",
)
log = logging.getLogger("prediction_engine")


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


# ── Fetch historical RPS ─────────────────────────────────────────
async def fetch_rps_series(pool: asyncpg.Pool) -> list[float]:
    since = datetime.now(timezone.utc) - timedelta(minutes=HISTORY_MINUTES)
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


# ── ARIMA Prediction ─────────────────────────────────────────────
def arima_predict(series: list[float], steps: int) -> tuple[float, float]:
    """Return (predicted_rps, confidence)."""
    try:
        from statsmodels.tsa.arima.model import ARIMA
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model  = ARIMA(series, order=(2, 1, 2))
            result = model.fit()
            forecast = result.forecast(steps=steps)
            predicted = max(0.0, float(np.mean(forecast)))
            conf_int  = result.get_forecast(steps=steps).conf_int(alpha=0.2)
            width     = float(np.mean(conf_int[:, 1] - conf_int[:, 0]))
            confidence = max(0.0, min(1.0, 1.0 - width / (predicted + 1e-9) * 0.1))
        return predicted, round(confidence, 3)
    except Exception as e:
        log.warning(f"ARIMA failed ({e}), falling back to EMA")
        return ema_predict(series, steps)


# ── EMA Fallback ─────────────────────────────────────────────────
def ema_predict(series: list[float], steps: int) -> tuple[float, float]:
    """Exponential Moving Average simple forecast."""
    alpha = 0.3
    ema   = series[0]
    for val in series[1:]:
        ema = alpha * val + (1 - alpha) * ema
    # Trend: difference between last EMA and mean of first half
    trend = (ema - np.mean(series[:len(series)//2])) / max(1, len(series)//2)
    predicted = max(0.0, ema + trend * steps)
    return round(predicted, 2), 0.6


# ── Store Prediction ─────────────────────────────────────────────
INSERT_SQL = """
    INSERT INTO predictions (predicted_at, horizon_minutes, predicted_rps,
                             predicted_cpu, confidence)
    VALUES ($1, $2, $3, $4, $5)
"""

async def store_prediction(pool: asyncpg.Pool, rps: float, conf: float):
    async with pool.acquire() as con:
        await con.execute(
            INSERT_SQL,
            datetime.now(timezone.utc),
            HORIZON_MINUTES,
            rps,
            None,   # cpu forecast could be added later
            conf,
        )
    log.info(f"Stored prediction: predicted_rps={rps:.2f} conf={conf:.3f}")


# ── Main loop ────────────────────────────────────────────────────
async def main():
    log.info(f"Prediction Engine starting  interval={RUN_INTERVAL}s")
    pool = await create_pool()

    while True:
        try:
            series = await fetch_rps_series(pool)
            if len(series) < 5:
                log.info(f"Not enough data yet ({len(series)} points) — waiting")
            else:
                rps, conf = arima_predict(series, HORIZON_MINUTES)
                log.info(f"Forecasted RPS ({HORIZON_MINUTES}m ahead): {rps:.2f} [conf={conf}]")
                await store_prediction(pool, rps, conf)
        except Exception as e:
            log.error(f"Prediction cycle error: {e}", exc_info=True)
        await asyncio.sleep(RUN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
