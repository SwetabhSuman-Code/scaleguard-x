"""
Facebook Prophet-based forecaster for traffic spike prediction

Advantages over ARIMA:
- Handles changepoints/trends
- Includes seasonality (hourly, daily, weekly)  
- Robust to missing data
- Better for detecting spikes

Limitations:
- Requires 14+ days warm-up
- Not real-time (batch predictions)
- Assumes patterns repeat
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

try:
    from prophet import Prophet
except ImportError:
    Prophet = None

logger = logging.getLogger(__name__)


class ProphetForecaster:
    """
    Facebook Prophet-based forecaster for RPS and CPU forecasting
    
    Replaces the flawed ARIMA with modern time-series ML that handles:
    - Trend changes (changepoint detection)
    - Multiple seasonalities (hourly, daily, weekly)
    - Missing data robustly
    - Spike prediction
    """
    
    def __init__(self):
        """Initialize forecaster"""
        if Prophet is None:
            raise ImportError(
                "Prophet not installed. Install with: pip install prophet"
            )
        self.model: Optional[Prophet] = None
        self.trained = False
        self.training_data: Optional[pd.DataFrame] = None
        self.training_days = 0
        
    def train(self, historical_data: pd.DataFrame) -> Dict:
        """
        Train Prophet on historical metrics
        
        Args:
            historical_data: DataFrame with columns:
                - 'ds' (datetime): timestamp
                - 'y' (float): metric value (RPS, CPU, etc)
        
        Returns:
            {
                "status": "trained",
                "data_points": 2016,
                "training_days": 14.0,
                "last_update": "2026-04-18T14:00:00"
            }
        
        Raises:
            ValueError: If insufficient data (< 14 days)
        """
        data_points = len(historical_data)
        
        # Require 14 days minimum (2016 points at 5-min intervals)
        if data_points < 2016:
            raise ValueError(
                f"Need 14+ days of data, got {data_points} points "
                f"({data_points / 144:.1f} days). Prophet needs sufficient "
                f"history to learn seasonality patterns."
            )
        
        logger.info(f"Training Prophet on {data_points} data points")
        
        # Create model with tuned parameters
        self.model = Prophet(
            changepoint_prior_scale=0.05,      # Detect trend changes
            seasonality_prior_scale=10,        # Strong seasonality
            seasonality_mode='multiplicative',  # RPS has multiplicative patterns
            interval_width=0.95,               # 95% confidence intervals
            yearly_seasonality=False,          # Not enough data typically
            daily_seasonality=True,            # Hour-of-day patterns
            weekly_seasonality=True,           # Day-of-week patterns
            seasonal_periods=288,              # 24 hours at 5-min intervals
        )
        
        # Fit model
        with open(os.devnull, 'w') as devnull:
            old_output = sys.stdout
            sys.stdout = devnull
            try:
                self.model.fit(historical_data)
            finally:
                sys.stdout = old_output
        
        self.trained = True
        self.training_data = historical_data.copy()
        self.training_days = data_points / 144
        
        logger.info(f"Prophet trained successfully on {data_points} points")
        
        return {
            "status": "trained",
            "data_points": data_points,
            "training_days": round(self.training_days, 1),
            "last_update": datetime.utcnow().isoformat()
        }
    
    def predict_next_10_minutes(
        self,
        current_data: pd.DataFrame
    ) -> Dict:
        """
        Predict traffic 10 minutes ahead (2 periods at 5-min intervals)
        
        Args:
            current_data: DataFrame with 'ds' and 'y' columns
        
        Returns:
            {
                "predicted_value": 450.2,
                "current_value": 420.0,
                "lower_bound": 400.1,
                "upper_bound": 520.5,
                "margin_of_error": 120.4,
                "trend": "increasing",
                "trend_value": 1.5,
                "spike_probability": 0.65,
                "confidence": 0.85,
                "warning": "⚠️ SPIKE ALERT: 7% increase predicted"
            }
        """
        if not self.trained:
            raise RuntimeError(
                "Model not trained. Call train() first."
            )
        
        # Get last 24 hours (288 points at 5-min intervals)
        recent_data = current_data.tail(288).copy()
        
        # Forecast 2 periods (10 minutes at 5-min intervals)
        future = self.model.make_future_dataframe(
            periods=2,
            freq='5min',
            include_history=False
        )
        
        forecast = self.model.predict(future)
        
        # Get 10-minute ahead prediction (period 2)
        next_period = forecast.iloc[-1]  # Last period (10 min ahead)
        current_value = float(recent_data['y'].iloc[-1])
        predicted_value = float(next_period['yhat'])
        
        # Calculate trend
        previous_value = float(recent_data['y'].iloc[-2])
        trend_direction = "increasing" if predicted_value > current_value else "decreasing"
        trend_magnitude = (predicted_value - previous_value) / (previous_value + 1e-6)
        
        # Detect spike (predicted > 1.5x current)
        spike_threshold = current_value * 1.5
        spike_probability = self._calculate_spike_probability(
            next_period, current_value
        )
        
        # Confidence based on interval width
        confidence = self._calculate_confidence(next_period, recent_data)
        
        # Generate warning
        warning = self._generate_warning(predicted_value, current_value)
        
        return {
            "predicted_value": round(predicted_value, 2),
            "current_value": round(current_value, 2),
            "lower_bound": round(float(next_period['yhat_lower']), 2),
            "upper_bound": round(float(next_period['yhat_upper']), 2),
            "margin_of_error": round(
                float(next_period['yhat_upper'] - next_period['yhat_lower']), 2
            ),
            "trend": trend_direction,
            "trend_value": round(trend_magnitude, 3),
            "spike_probability": round(spike_probability, 2),
            "confidence": round(confidence, 2),
            "warning": warning
        }
    
    def predict_horizon(
        self,
        current_data: pd.DataFrame,
        horizon_minutes: int = 60
    ) -> Dict:
        """
        Predict multiple time horizons ahead
        
        Args:
            current_data: DataFrame with 'ds' and 'y' columns
            horizon_minutes: How far ahead to predict (5, 10, 30, 60)
        
        Returns:
            {
                "horizon_minutes": 60,
                "predictions": [
                    {"time_offset": 5, "predicted": 450, "upper": 520, "lower": 400},
                    ...
                ]
            }
        """
        if not self.trained:
            raise RuntimeError("Model not trained")
        
        periods = horizon_minutes // 5  # Convert to 5-min periods
        
        future = self.model.make_future_dataframe(
            periods=periods,
            freq='5min',
            include_history=False
        )
        forecast = self.model.predict(future)
        
        predictions = []
        for i, row in forecast.iterrows():
            predictions.append({
                "time_offset_minutes": (i + 1) * 5,
                "predicted_value": round(float(row['yhat']), 2),
                "lower_bound": round(float(row['yhat_lower']), 2),
                "upper_bound": round(float(row['yhat_upper']), 2),
                "trend": float(row['trend'])
            })
        
        return {
            "horizon_minutes": horizon_minutes,
            "predictions": predictions
        }
    
    def _calculate_spike_probability(self, prediction, current_value: float) -> float:
        """
        Calculate probability of spike based on prediction interval
        
        If upper bound > 1.5x current, probability of spike increases
        """
        upper = float(prediction['yhat_upper'])
        spike_threshold = current_value * 1.5
        
        # Sigmoid-based probability
        if upper > spike_threshold:
            excess = (upper - spike_threshold) / (current_value + 1e-6)
            probability = min(1.0, excess / 2.0)  # Cap at 1.0
        else:
            probability = 0.0
        
        return np.clip(probability, 0.0, 1.0)
    
    def _calculate_confidence(
        self,
        prediction,
        recent_data: pd.DataFrame
    ) -> float:
        """
        Confidence based on recent pattern consistency
        
        Wider prediction intervals = lower confidence
        More consistent recent data = higher confidence
        """
        # Measure recent data variance
        recent_variance = float(recent_data['y'].std())
        
        # Prediction interval width
        margin = float(prediction['yhat_upper'] - prediction['yhat_lower'])
        
        # Calculate confidence: inverse of relative margin width
        # High variance recent data = lower confidence
        # Narrow prediction interval = higher confidence
        if recent_variance > 0:
            ratio = margin / (recent_variance + 1e-6)
            confidence = 1.0 / (1.0 + ratio)
        else:
            confidence = 0.9
        
        return np.clip(confidence, 0.3, 0.95)
    
    def _generate_warning(self, predicted: float, current: float) -> str:
        """Generate human-readable warning if spike detected"""
        if current == 0:
            return ""
        
        change_pct = ((predicted - current) / current) * 100
        
        if change_pct > 100:
            return f"⚠️ SPIKE ALERT: {abs(change_pct):.0f}% increase predicted"
        elif change_pct > 50:
            return f"⚠️ SURGE: {abs(change_pct):.0f}% increase detected"
        elif change_pct < -50:
            return f"⚠️ DROP ALERT: {abs(change_pct):.0f}% decrease predicted"
        
        return ""


# Suppress Prophet logging (optional)
import os
import sys

logging.getLogger("prophet.plot.diagnostics").setLevel(logging.ERROR)
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
