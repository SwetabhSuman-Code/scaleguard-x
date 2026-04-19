"""
ScaleGuard X — Unit Tests: Prediction Engine (pure functions)
"""

from __future__ import annotations

import pytest

from prediction_engine.main import arima_predict, ema_predict


@pytest.mark.unit
class TestEmaPrediction:
    def test_ema_returns_tuple(self) -> None:
        series = [100.0, 110.0, 105.0, 120.0, 115.0]
        rps, conf = ema_predict(series, steps=10)
        assert isinstance(rps, float)
        assert isinstance(conf, float)

    def test_ema_confidence_is_0_6(self) -> None:
        series = [50.0] * 20
        _, conf = ema_predict(series, steps=10)
        assert conf == 0.6

    def test_ema_non_negative_prediction(self) -> None:
        series = [1.0, 2.0, 1.0, 2.0]
        rps, _ = ema_predict(series, steps=5)
        assert rps >= 0.0

    def test_ema_stable_series(self) -> None:
        series = [200.0] * 30
        rps, _ = ema_predict(series, steps=10)
        assert abs(rps - 200.0) < 10.0  # should be near 200


@pytest.mark.unit
class TestArimaPrediction:
    def test_arima_or_ema_returns_non_negative(self) -> None:
        series = list(range(10, 40))  # 30 data points
        rps, conf = arima_predict(series, steps=10)
        assert rps >= 0.0
        assert 0.0 <= conf <= 1.0

    def test_arima_falls_back_for_short_series(self) -> None:
        # Too short for clean ARIMA; should still return a result via EMA
        series = [10.0, 12.0, 11.0]
        rps, conf = arima_predict(series, steps=10)
        assert isinstance(rps, float)
        assert conf == 0.6  # EMA fallback confidence
