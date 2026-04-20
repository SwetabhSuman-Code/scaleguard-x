"""
ScaleGuard X - Predictive Load Forecasting Engine

Primary flow:
  1. Train or refresh a Prophet forecaster when enough history exists
  2. Use Prophet for forecast ranges and trend-aware predictions
  3. Use an LSTM spike detector for spike probability
  4. Fall back to ARIMA/EMA when the ML warm-up window is not available
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

try:
    import asyncpg
except ImportError:  # pragma: no cover - optional in pure unit-test environments
    asyncpg = None  # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.circuit_breaker import CircuitBreakerError, make_postgres_breaker
from lib.logging_config import get_logger, setup_json_logging
from lib.prometheus_metrics import setup_metrics, setup_metrics_server

if TYPE_CHECKING:
    import asyncpg as asyncpg_module
    from prediction_engine.models.lstm_spike_detector import SpikeDetectorLSTM
    from prediction_engine.models.prophet_forecaster import ProphetForecaster

load_dotenv()
setup_json_logging("prediction_engine")
setup_metrics("prediction_engine")
setup_metrics_server(port=9093)
log = get_logger("prediction_engine")

PG_DSN = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'scaleguard')}"
    f":{os.getenv('POSTGRES_PASSWORD', 'scaleguard_secret')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}"
    f":{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'scaleguard')}"
)
HORIZON_MINUTES = int(os.getenv("PREDICTION_HORIZON_MINUTES", 10))
RUN_INTERVAL = int(os.getenv("PREDICTION_RUN_INTERVAL", 30))
PROPHET_HISTORY_MINUTES = int(os.getenv("PROPHET_HISTORY_MINUTES", 14 * 24 * 60))
PROPHET_RETRAIN_MINUTES = int(os.getenv("PROPHET_RETRAIN_MINUTES", 360))
LSTM_TRAINING_SAMPLES = int(os.getenv("LSTM_TRAINING_SAMPLES", 300))
LSTM_EPOCHS = int(os.getenv("LSTM_EPOCHS", 4))

_pg_cb = make_postgres_breaker("prediction_engine")


@dataclass
class ModelState:
    """Long-lived model cache for the prediction loop."""

    prophet: Optional["ProphetForecaster"] = None
    prophet_last_trained_at: Optional[datetime] = None
    lstm: Optional["SpikeDetectorLSTM"] = None


async def create_pool() -> "asyncpg_module.Pool":
    if asyncpg is None:
        raise RuntimeError("asyncpg is required to run prediction_engine.main")

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


async def fetch_rps_frame(
    pool: "asyncpg_module.Pool",
    lookback_minutes: int,
) -> pd.DataFrame:
    """Fetch raw RPS history and aggregate it into 5-minute buckets for forecasting."""
    since = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                rows = await con.fetch(
                    """SELECT timestamp, requests_per_sec
                       FROM metrics
                       WHERE timestamp >= $1
                       ORDER BY timestamp""",
                    since,
                )
    except CircuitBreakerError as exc:
        log.warning("circuit_open_rps_fetch", extra={"error": str(exc)})
        return pd.DataFrame(columns=["ds", "y"])

    if not rows:
        return pd.DataFrame(columns=["ds", "y"])

    frame = pd.DataFrame(
        [(row["timestamp"], row["requests_per_sec"]) for row in rows],
        columns=["ds", "y"],
    )
    frame["ds"] = pd.to_datetime(frame["ds"], utc=True)
    frame["y"] = pd.to_numeric(frame["y"], errors="coerce")
    frame = frame.dropna()
    if frame.empty:
        return pd.DataFrame(columns=["ds", "y"])

    frame = frame.set_index("ds").resample("5min").mean().dropna().reset_index()
    return frame


def ema_predict(series: list[float], steps: int) -> tuple[float, float]:
    """Exponential Moving Average simple forecast."""
    alpha = 0.3
    ema = series[0]
    for val in series[1:]:
        ema = alpha * val + (1 - alpha) * ema
    trend = (ema - np.mean(series[: len(series) // 2])) / max(1, len(series) // 2)
    predicted = float(max(0.0, ema + trend * steps))
    return round(predicted, 2), 0.6


def arima_predict(series: list[float], steps: int) -> tuple[float, float]:
    """
    Fit ARIMA on the provided series.
    Falls back to EMA when the series is too short or fitting fails.
    """
    try:
        import warnings

        from statsmodels.tsa.arima.model import ARIMA

        if len(series) < 8:
            raise ValueError("Series too short for stable ARIMA fit")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ARIMA(series, order=(2, 1, 2))
            result = model.fit()
            forecast = result.forecast(steps=steps)
            predicted = max(0.0, float(np.mean(forecast)))
            conf_int = result.get_forecast(steps=steps).conf_int(alpha=0.2)
            width = float(np.mean(conf_int[:, 1] - conf_int[:, 0]))
            confidence = max(0.0, min(1.0, 1.0 - width / (predicted + 1e-9) * 0.1))
        return round(predicted, 2), round(confidence, 3)
    except Exception as exc:
        log.warning("arima_failed_ema_fallback", extra={"error": str(exc)})
        return ema_predict(series, steps)


def train_lstm_model() -> Optional["SpikeDetectorLSTM"]:
    """Train a lightweight LSTM once at startup using synthetic spike data."""
    try:
        from prediction_engine.models.lstm_spike_detector import (
            generate_synthetic_spike_data,
            train_spike_detector,
        )

        X_train, y_train = generate_synthetic_spike_data(
            samples=LSTM_TRAINING_SAMPLES,
            normal_ratio=0.6,
        )
        model, _ = train_spike_detector(
            X_train,
            y_train,
            epochs=LSTM_EPOCHS,
            batch_size=32,
        )
        log.info(
            "lstm_model_ready",
            extra={"samples": LSTM_TRAINING_SAMPLES, "epochs": LSTM_EPOCHS},
        )
        return model
    except Exception as exc:
        log.warning("lstm_model_unavailable", extra={"error": str(exc)})
        return None


def should_retrain_prophet(state: ModelState) -> bool:
    if state.prophet is None or state.prophet_last_trained_at is None:
        return True
    age = datetime.now(timezone.utc) - state.prophet_last_trained_at
    return age >= timedelta(minutes=PROPHET_RETRAIN_MINUTES)


def prepare_lstm_sequence(frame: pd.DataFrame) -> Optional[np.ndarray]:
    if frame.empty:
        return None
    series = frame["y"].astype(float).tail(288).to_numpy()
    if len(series) < 288:
        series = np.pad(series, (288 - len(series), 0), mode="edge")
    return series


def build_prediction(
    state: ModelState,
    frame: pd.DataFrame,
) -> dict:
    """
    Create a unified prediction payload from the best available model path.
    """
    if not frame.empty and len(frame) >= 2016 and state.prophet is not None:
        prophet_prediction = state.prophet.predict_next_10_minutes(frame)
        spike_probability = prophet_prediction.get("spike_probability", 0.0)
        if state.lstm is not None:
            sequence = prepare_lstm_sequence(frame)
            if sequence is not None:
                spike_probability, _ = state.lstm.predict_spike_probability(sequence)

        return {
            "predicted_rps": prophet_prediction["predicted_value"],
            "predicted_cpu": None,
            "confidence": prophet_prediction["confidence"],
            "lower_bound": prophet_prediction["lower_bound"],
            "upper_bound": prophet_prediction["upper_bound"],
            "spike_probability": round(float(spike_probability), 3),
            "model_name": "prophet_lstm",
        }

    series = frame["y"].astype(float).tolist()
    if len(series) >= 8:
        predicted_rps, confidence = arima_predict(series, HORIZON_MINUTES)
        model_name = "arima_fallback"
    elif len(series) >= 1:
        predicted_rps, confidence = ema_predict(series, HORIZON_MINUTES)
        model_name = "ema_fallback"
    else:
        predicted_rps, confidence = 0.0, 0.0
        model_name = "insufficient_data"

    return {
        "predicted_rps": predicted_rps,
        "predicted_cpu": None,
        "confidence": confidence,
        "lower_bound": predicted_rps,
        "upper_bound": predicted_rps,
        "spike_probability": 0.0,
        "model_name": model_name,
    }


async def store_prediction(
    pool: "asyncpg_module.Pool",
    prediction: dict[str, Any],
) -> None:
    try:
        async with _pg_cb:
            async with pool.acquire() as con:
                await con.execute(
                    """INSERT INTO predictions
                           (predicted_at, horizon_minutes, predicted_rps, predicted_cpu,
                            confidence, lower_bound, upper_bound, spike_probability, model_name)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    datetime.now(timezone.utc),
                    HORIZON_MINUTES,
                    prediction["predicted_rps"],
                    prediction["predicted_cpu"],
                    prediction["confidence"],
                    prediction["lower_bound"],
                    prediction["upper_bound"],
                    prediction["spike_probability"],
                    prediction["model_name"],
                )
        log.info("prediction_stored", extra=prediction)
    except CircuitBreakerError as exc:
        log.warning("circuit_open_store", extra={"error": str(exc)})
    except Exception as exc:
        log.error("prediction_store_failed", extra={"error": str(exc)})


async def ensure_prophet_model(state: ModelState, frame: pd.DataFrame) -> None:
    """Train or refresh the Prophet model when enough history is available."""
    if len(frame) < 2016 or not should_retrain_prophet(state):
        return

    try:
        from prediction_engine.models.prophet_forecaster import ProphetForecaster

        forecaster = ProphetForecaster()
        forecaster.train(frame.tail(max(2016, len(frame))))
        state.prophet = forecaster
        state.prophet_last_trained_at = datetime.now(timezone.utc)
        log.info("prophet_model_ready", extra={"training_points": len(frame)})
    except Exception as exc:
        log.warning("prophet_training_failed", extra={"error": str(exc)})


async def main() -> None:
    log.info("prediction_engine_starting", extra={"interval_s": RUN_INTERVAL})
    pool = await create_pool()
    state = ModelState(lstm=train_lstm_model())

    while True:
        try:
            frame = await fetch_rps_frame(pool, PROPHET_HISTORY_MINUTES)
            await ensure_prophet_model(state, frame)
            prediction = build_prediction(state, frame)
            await store_prediction(pool, prediction)
        except Exception as exc:
            log.error("prediction_cycle_error", extra={"error": str(exc)}, exc_info=True)
        await asyncio.sleep(RUN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
