"""
Predictive autoscaling that integrates PID control with ML predictions.

Combines three decision factors:
  1. PID Control: Handles current utilization with smooth, responsive control
  2. Prophet Forecasting: Uses predicted upper bound for capacity headroom
  3. LSTM Spike Detection: Emergency decisions when spike probability > threshold

This creates intelligent autoscaling that is:
  - Stable: PID control prevents oscillation
  - Proactive: Predicts spikes and pre-scales using Prophet upper bounds
  - Reactive: LSTM spike detection triggers immediate action for anomalies
  - Cost-aware: Scales conservatively at baseline, aggressively during spikes
"""

import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass
import time

from .pid_controller import PIDController, PIDConfig

logger = logging.getLogger(__name__)


@dataclass
class PredictiveScalerConfig:
    """Configuration for predictive autoscaler."""

    # PID tuning
    pid_kp: float = 1.0
    pid_ki: float = 0.05
    pid_kd: float = 0.5
    pid_setpoint: float = 70.0

    # Prophet integration (forecast-based scaling)
    prophet_enabled: bool = True
    prophet_headroom_factor: float = 0.15  # 15% safety margin above predicted

    # LSTM spike detection
    lstm_enabled: bool = True
    spike_probability_threshold: float = 0.6  # Trigger emergency scaling at 60% spike probability
    spike_scaling_boost: float = 1.5  # Multiply scaling action by 1.5 during spikes

    # Scaling bounds
    min_scaling_action: float = -5.0  # Maximum scale-up action (negative)
    max_scaling_action: float = 10.0  # Maximum scale-down action (positive)

    # Thrashing prevention
    min_decision_interval: float = 300.0  # No scaling decisions more than every 5 minutes
    min_scaling_magnitude: float = 0.5  # Ignore scaling decisions < 0.5 instances


class ScalingDecision:
    """
    Container for a scaling decision with full justification.

    Attributes:
        action: Number of instances to add (positive) or remove (negative)
        factors: Dict of contributing factors with their values/scores
        timestamp: When decision was made
        reason: Human-readable justification
    """

    def __init__(self):
        self.action = 0.0
        self.factors = {
            "pid_component": 0.0,
            "prophet_component": 0.0,
            "lstm_component": 0.0,
            "current_utilization": 0.0,
            "predicted_peak": 0.0,
            "spike_probability": 0.0,
        }
        self.timestamp = time.time()
        self.reason = ""
        self.is_emergency = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/monitoring."""
        return {
            "action": self.action,
            "factors": self.factors,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "is_emergency": self.is_emergency,
        }


class PredictiveScaler:
    """
    Multi-factor intelligent autoscaler.

    Uses PID control as base, Prophet predictions for proactive scaling,
    and LSTM spike detection for emergency decisions. Respects thrashing
    prevention to avoid rapid scale-up/down oscillations.

    Attributes:
        config: PredictiveScalerConfig with all settings
        pid_controller: Internal PIDController instance
        last_scaling_decision_time: Timestamp of last scaling action
        scaling_decision_history: Recent decisions for analysis
    """

    def __init__(
        self,
        config: Optional[PredictiveScalerConfig] = None,
        prophet_module: Optional[Any] = None,
        lstm_module: Optional[Any] = None,
    ):
        """
        Initialize predictive scaler.

        Args:
            config: PredictiveScalerConfig (uses defaults if None)
            prophet_module: ProphetForecaster instance (optional for predictions)
            lstm_module: SpikeDetectorLSTM instance (optional for spike detection)
        """
        self.config = config or PredictiveScalerConfig()
        self.prophet = prophet_module
        self.lstm = lstm_module
        self.pid_controller = PIDController(
            PIDConfig(
                kp=self.config.pid_kp,
                ki=self.config.pid_ki,
                kd=self.config.pid_kd,
                setpoint=self.config.pid_setpoint,
                output_min=self.config.min_scaling_action,
                output_max=self.config.max_scaling_action,
            )
        )
        self.last_scaling_decision_time = time.time() - self.config.min_decision_interval
        self.scaling_decision_history = []

        logger.info(
            f"PredictiveScaler initialized: "
            f"Prophet={self.config.prophet_enabled}, "
            f"LSTM={self.config.lstm_enabled}, "
            f"spike_threshold={self.config.spike_probability_threshold}"
        )

    def decide_scaling(
        self,
        current_utilization: float,
        recent_data: Optional[Any] = None,
        current_metrics: Optional[Any] = None,
        dt: float = 60.0,
    ) -> ScalingDecision:
        """
        Make a scaling decision based on all available signals.

        Args:
            current_utilization: Current CPU/memory utilization (0-100)
            recent_data: Recent metrics for Prophet/LSTM (timeseries data)
            current_metrics: Current system metrics (optional context)
            dt: Time since last decision (seconds)

        Returns:
            ScalingDecision with action and justification

        Raises:
            ValueError: If current_utilization outside [0, 100]
        """
        decision = ScalingDecision()
        decision.factors["current_utilization"] = current_utilization

        if not 0 <= current_utilization <= 100:
            raise ValueError(f"Utilization must be 0-100, got {current_utilization}")

        # Check thrashing prevention
        time_since_last_decision = time.time() - self.last_scaling_decision_time
        if time_since_last_decision < self.config.min_decision_interval:
            # Too soon to make another scaling decision
            decision.action = 0.0
            decision.reason = (
                f"Thrashing prevention: {time_since_last_decision:.0f}s "
                f"since last decision (min: {self.config.min_decision_interval:.0f}s)"
            )
            return decision

        # 1. PID Control Component (always used)
        pid_result = self.pid_controller.update(current_utilization, dt)
        pid_component = pid_result["scaling_action"]
        decision.factors["pid_component"] = pid_component

        # 2. Prophet Prediction Component (if available)
        prophet_component = 0.0
        if self.config.prophet_enabled and self.prophet is not None and recent_data is not None:
            try:
                prophet_prediction = self.prophet.predict_next_10_minutes(recent_data)
                predicted_peak = prophet_prediction.get("upper_bound", 0)
                decision.factors["predicted_peak"] = predicted_peak

                # If predicted peak exceeds setpoint + headroom, add scaling
                headroom_threshold = self.config.pid_setpoint * (
                    1 + self.config.prophet_headroom_factor
                )
                if predicted_peak > headroom_threshold:
                    # Scale proactively based on how far above threshold we are
                    excess = predicted_peak - headroom_threshold
                    prophet_component = -min(
                        0.8 * abs(self.config.min_scaling_action),
                        0.1 * excess / 10.0,  # 0.1 instances per 10% exceed
                    )
                    decision.reason = (
                        f"Prophet detected predicted peak {predicted_peak:.1f}% "
                        f"exceeds headroom threshold {headroom_threshold:.1f}%"
                    )
                logger.debug(f"Prophet component: {prophet_component:.2f}")
            except Exception as e:
                logger.warning(f"Prophet prediction failed: {e}")

        decision.factors["prophet_component"] = prophet_component

        # 3. LSTM Spike Detection Component (if available)
        lstm_component = 0.0
        spike_probability = 0.0
        is_emergency = False
        if self.config.lstm_enabled and self.lstm is not None and recent_data is not None:
            try:
                spike_prob, normal_prob = self.lstm.predict_spike_probability(recent_data)
                spike_probability = spike_prob
                decision.factors["spike_probability"] = spike_probability

                if spike_prob > self.config.spike_probability_threshold:
                    # Emergency spike detected: aggressive scaling
                    lstm_component = self.config.min_scaling_action * 0.8
                    is_emergency = True
                    decision.reason = (
                        f"LSTM SPIKE ALERT: Spike probability {spike_prob:.1%} "
                        f"exceeds threshold {self.config.spike_probability_threshold:.1%}"
                    )
                logger.debug(f"LSTM spike probability: {spike_prob:.1%}")
            except Exception as e:
                logger.warning(f"LSTM spike detection failed: {e}")

        decision.factors["lstm_component"] = lstm_component
        decision.is_emergency = is_emergency

        # Combine all components with emergency boost
        combined_action = pid_component + prophet_component + lstm_component
        if is_emergency:
            # Boost scaling during spike emergency
            combined_action *= self.config.spike_scaling_boost

        # Apply final clamping
        final_action = max(
            self.config.min_scaling_action,
            min(self.config.max_scaling_action, combined_action),
        )

        # Ignore trivial scaling decisions (thrashing prevention)
        if abs(final_action) < self.config.min_scaling_magnitude:
            decision.action = 0.0
            decision.reason = (
                f"Scaling action {final_action:.2f} below minimum magnitude "
                f"{self.config.min_scaling_magnitude:.2f}"
            )
        else:
            decision.action = final_action
            if not decision.reason:  # Add reason if not already set
                decision.reason = (
                    f"PID: {pid_component:+.2f}, "
                    f"Prophet: {prophet_component:+.2f}, "
                    f"LSTM: {lstm_component:+.2f}"
                )

        # Update history and timestamp
        self.scaling_decision_history.append(decision)
        if len(self.scaling_decision_history) > 100:
            self.scaling_decision_history.pop(0)
        self.last_scaling_decision_time = time.time()

        log_level = logging.WARNING if is_emergency else logging.INFO
        logger.log(
            log_level,
            f"Scaling decision: action={decision.action:+.2f} instances, "
            f"reason={decision.reason}",
        )

        return decision

    def get_recent_decisions(self, count: int = 10) -> list:
        """Get last N scaling decisions for analysis."""
        return [d.to_dict() for d in self.scaling_decision_history[-count:]]

    def get_performance_metrics(self) -> Dict[str, float]:
        """
        Get performance metrics over decision history.

        Returns:
            Dict with average_action, min_action, max_action, emergency_count, etc.
        """
        if not self.scaling_decision_history:
            return {
                "decisions_made": 0,
                "average_action": 0.0,
                "emergency_count": 0,
            }

        actions = [d.action for d in self.scaling_decision_history]
        emergencies = sum(1 for d in self.scaling_decision_history if d.is_emergency)

        return {
            "decisions_made": len(self.scaling_decision_history),
            "average_action": sum(actions) / len(actions),
            "min_action": min(actions),
            "max_action": max(actions),
            "emergency_count": emergencies,
            "emergency_percentage": (emergencies / len(self.scaling_decision_history)) * 100,
        }

    def reset(self) -> None:
        """Reset scaler state and history."""
        self.pid_controller.reset()
        self.scaling_decision_history = []
        self.last_scaling_decision_time = time.time() - self.config.min_decision_interval
        logger.info("PredictiveScaler reset")
