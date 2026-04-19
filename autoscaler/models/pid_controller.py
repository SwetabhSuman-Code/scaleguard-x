"""
PID (Proportional-Integral-Derivative) Controller for autoscaling.

Implements a classic PID control loop with anti-windup and output clamping
to enable stable, responsive autoscaling without oscillation or thrashing.

Theory:
  - Output = Kp*error + Ki*integral(error) + Kd*derivative(error)
  - Proportional term: immediate response to current error
  - Integral term: response to accumulated error (eliminating steady-state bias)
  - Derivative term: dampening (prevents overshoot and oscillation)

Tuning Strategy (Ziegler-Nichols for autoscaling):
  - Guardian default: Kp=1.0, Ki=0.05, Kd=0.5
  - Aggressive: Kp=2.0, Ki=0.1, Kd=1.0 (faster response, higher oscillation risk)
  - Conservative: Kp=0.5, Ki=0.02, Kd=0.2 (stable, slower response)
"""

import time
from typing import Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class PIDConfig:
    """Configuration for PID controller tuning."""

    kp: float = 1.0  # Proportional gain
    ki: float = 0.05  # Integral gain
    kd: float = 0.5  # Derivative gain
    setpoint: float = 70.0  # Target utilization percentage
    output_min: float = -5.0  # Most aggressive scale-up action
    output_max: float = 10.0  # Most aggressive scale-down action
    integral_max: float = 100.0  # Anti-windup threshold


class PIDController:
    """
    PID controller for autoscaling decisions.

    Converts current utilization metrics into scaling decisions using
    a tuned PID control loop. Designed for stability (no oscillation)
    and responsiveness (handles spikes quickly).

    Attributes:
        config: PIDConfig with tuning parameters
        integral_error: Accumulated error for integral term
        last_error: Previous error for derivative calculation
        last_update_time: Timestamp of last update for time delta
    """

    def __init__(self, config: Optional[PIDConfig] = None):
        """
        Initialize PID controller.

        Args:
            config: PIDConfig instance (uses defaults if None)
        """
        self.config = config or PIDConfig()
        self.integral_error = 0.0
        self.last_error = 0.0
        self._has_previous_error = False
        self.last_update_time = time.time()
        self.error_history = []
        logger.info(
            f"PID Controller initialized: Kp={self.config.kp}, "
            f"Ki={self.config.ki}, Kd={self.config.kd}, "
            f"setpoint={self.config.setpoint}%"
        )

    def update(self, current_utilization: float, dt: Optional[float] = None) -> Dict[str, float]:
        """
        Calculate scaling action based on current utilization.

        Args:
            current_utilization: Current CPU/memory utilization (0-100)
            dt: Time delta in seconds. If None, calculated from last update.
                Must be > 0 for derivative calculation to be meaningful.

        Returns:
            Dict with keys:
                - scaling_action: Recommended scaling change (instances to add/remove)
                - error: Current error (setpoint - utilization)
                - p_term: Proportional component
                - i_term: Integral component
                - d_term: Derivative component
                - integral: Accumulated integral error

        Raises:
            ValueError: If current_utilization outside [0, 100] or dt < 0
        """
        if not 0 <= current_utilization <= 100:
            raise ValueError(f"Utilization must be 0-100, got {current_utilization}")

        # Calculate time delta if not provided
        if dt is None:
            current_time = time.time()
            dt = current_time - self.last_update_time
            self.last_update_time = current_time
        elif dt < 0:
            raise ValueError(f"Time delta must be >= 0, got {dt}")

        # Handle edge case: very small dt (prevent divide by zero in derivative)
        if dt < 0.001:
            dt = 0.001

        # Calculate error signal (positive = over-utilized, negative = under-utilized)
        error = self.config.setpoint - current_utilization
        self.error_history.append(error)
        if len(self.error_history) > 1000:
            self.error_history.pop(0)

        # Proportional term: immediate response to error
        p_term = self.config.kp * error

        # Integral term: accumulated error (with anti-windup)
        self.integral_error += error * dt
        # Anti-windup: clamp integral to prevent excessive accumulation
        if abs(self.integral_error) > self.config.integral_max:
            self.integral_error = (
                self.config.integral_max if self.integral_error > 0 else -self.config.integral_max
            )
        i_term = self.config.ki * self.integral_error

        # Derivative term: rate of change (dampening for stability)
        derivative = 0.0
        if self._has_previous_error and dt > 0:
            derivative = (error - self.last_error) / dt
        d_term = self.config.kd * derivative
        self.last_error = error
        self._has_previous_error = True

        # Calculate raw output
        raw_output = p_term + i_term + d_term

        # Clamp output to acceptable range
        scaling_action = max(self.config.output_min, min(self.config.output_max, raw_output))

        logger.debug(
            f"PID Update: utilization={current_utilization:.1f}%, "
            f"error={error:.1f}, P={p_term:.2f}, I={i_term:.2f}, "
            f"D={d_term:.2f}, scaling_action={scaling_action:.2f}"
        )

        return {
            "scaling_action": scaling_action,
            "error": error,
            "p_term": p_term,
            "i_term": i_term,
            "d_term": d_term,
            "integral_error": self.integral_error,
            "derivative": derivative,
        }

    def reset(self) -> None:
        """Reset controller state (integral, history, errors)."""
        self.integral_error = 0.0
        self.last_error = 0.0
        self._has_previous_error = False
        self.error_history = []
        self.last_update_time = time.time()
        logger.info("PID Controller reset")

    def get_state(self) -> Dict[str, float]:
        """
        Get current internal state for monitoring/debugging.

        Returns:
            Dict with integral_error, last_error, error_history stats
        """
        if not self.error_history:
            return {
                "integral_error": self.integral_error,
                "last_error": self.last_error,
                "error_history_length": 0,
                "error_mean": 0,
                "error_std": 0,
            }

        import statistics

        return {
            "integral_error": self.integral_error,
            "last_error": self.last_error,
            "error_history_length": len(self.error_history),
            "error_mean": statistics.mean(self.error_history),
            "error_std": statistics.stdev(self.error_history) if len(self.error_history) > 1 else 0,
            "error_min": min(self.error_history),
            "error_max": max(self.error_history),
        }

    def tune(self, kp: float, ki: float, kd: float) -> None:
        """
        Adjust PID tuning parameters dynamically.

        Args:
            kp: New proportional gain
            ki: New integral gain
            kd: New derivative gain
        """
        old_config = (self.config.kp, self.config.ki, self.config.kd)
        self.config.kp = kp
        self.config.ki = ki
        self.config.kd = kd
        logger.info(f"PID tuned: {old_config} -> ({kp}, {ki}, {kd})")

    def clamp_output(self, min_val: float, max_val: float) -> None:
        """
        Update output clamping bounds.

        Args:
            min_val: Minimum scaling action
            max_val: Maximum scaling action
        """
        self.config.output_min = min_val
        self.config.output_max = max_val
        logger.info(f"Output clamping updated: [{min_val}, {max_val}]")
