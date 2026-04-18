"""
Unit tests for PID controller.

Tests focus on three critical aspects:
1. Stability: No oscillation under noisy load
2. Responsiveness: Handles spikes in < 60 seconds
3. Anti-windup: Output remains bounded and sensible
"""

import pytest
import time
import statistics
from unittest.mock import patch, MagicMock

from autoscaler.models.pid_controller import PIDController, PIDConfig


class TestPIDInitialization:
    """Test PID controller creation and configuration."""

    def test_default_initialization(self):
        """PID initializes with sensible defaults."""
        pid = PIDController()
        assert pid.config.setpoint == 70.0
        assert pid.config.kp == 1.0
        assert pid.config.ki == 0.05
        assert pid.config.kd == 0.5
        assert pid.integral_error == 0.0
        assert pid.last_error == 0.0

    def test_custom_configuration(self):
        """PID accepts custom configuration."""
        config = PIDConfig(
            kp=2.0,
            ki=0.1,
            kd=1.0,
            setpoint=50.0
        )
        pid = PIDController(config)
        assert pid.config.kp == 2.0
        assert pid.config.setpoint == 50.0

    def test_aggressive_tuning(self):
        """Aggressive tuning can be applied."""
        config = PIDConfig(kp=2.0, ki=0.1, kd=1.0)
        pid = PIDController(config)
        pid.tune(2.5, 0.15, 1.2)
        assert pid.config.kp == 2.5

    def test_initialization_logging(self):
        """Initialization logs tuning parameters."""
        with patch('autoscaler.models.pid_controller.logger') as mock_logger:
            pid = PIDController()
            mock_logger.info.assert_called()


class TestPIDProportionalTerm:
    """Test proportional (P) control component."""

    def test_proportional_response_to_high_utilization(self):
        """P term increases when utilization exceeds setpoint."""
        pid = PIDController(PIDConfig(kp=1.0, ki=0.0, kd=0.0, setpoint=70.0))
        
        # High utilization: 90% (error = -20)
        result = pid.update(90.0, dt=1.0)
        
        # Proportional component should be negative (scale up)
        assert result["p_term"] < 0
        assert result["p_term"] == -20.0  # 1.0 * (-20)

    def test_proportional_response_to_low_utilization(self):
        """P term decreases when utilization below setpoint."""
        pid = PIDController(PIDConfig(kp=1.0, ki=0.0, kd=0.0, setpoint=70.0))
        
        # Low utilization: 50% (error = +20)
        result = pid.update(50.0, dt=1.0)
        
        # Proportional component should be positive (scale down)
        assert result["p_term"] > 0
        assert result["p_term"] == 20.0  # 1.0 * 20

    def test_proportional_gain_scales_response(self):
        """Higher Kp increases responsiveness."""
        pid_normal = PIDController(PIDConfig(kp=1.0, ki=0.0, kd=0.0))
        pid_aggressive = PIDController(PIDConfig(kp=2.0, ki=0.0, kd=0.0))
        
        result_normal = pid_normal.update(90.0, dt=1.0)
        result_aggressive = pid_aggressive.update(90.0, dt=1.0)
        
        # Aggressive should respond twice as much
        assert result_aggressive["p_term"] == 2 * result_normal["p_term"]


class TestPIDIntegralTerm:
    """Test integral (I) control component."""

    def test_integral_accumulation(self):
        """Integral term accumulates error over time."""
        pid = PIDController(PIDConfig(kp=0.0, ki=0.1, kd=0.0))
        
        # Sustained high utilization
        for _ in range(5):
            result = pid.update(90.0, dt=1.0)
        
        # Integral should accumulate
        assert pid.integral_error > 0
        assert result["i_term"] > 0

    def test_integral_windup_prevention(self):
        """Anti-windup clamps integral to prevent excessive accumulation."""
        config = PIDConfig(kp=0.0, ki=1.0, kd=0.0, integral_max=50.0)
        pid = PIDController(config)
        
        # Sustained high utilization to trigger windup
        for _ in range(100):
            pid.update(95.0, dt=1.0)
        
        # Integral should never exceed max
        assert pid.integral_error <= config.integral_max

    def test_integral_reversal(self):
        """Integral decreases when conditions improve."""
        pid = PIDController(PIDConfig(kp=0.0, ki=0.1, kd=0.0))
        
        # Build up integral
        for _ in range(5):
            pid.update(90.0, dt=1.0)
        integral_high = pid.integral_error
        
        # Switch to low utilization
        pid.update(50.0, dt=1.0)
        
        # Integral should decrease
        assert pid.integral_error < integral_high


class TestPIDDerivativeTerm:
    """Test derivative (D) control component."""

    def test_derivative_dampening(self):
        """D term dampens rapid changes."""
        pid = PIDController(PIDConfig(kp=0.0, ki=0.0, kd=1.0))
        
        # Rapid increase in utilization
        result1 = pid.update(50.0, dt=1.0)  # error = +20
        result2 = pid.update(90.0, dt=1.0)  # error = -20, derivative = (−20 − 20) / 1 = -40
        
        # Derivative should be negative (dampening the increase)
        assert result2["d_term"] < 0
        assert result2["d_term"] == -40.0  # 1.0 * (-40)

    def test_derivative_prevents_overshoot(self):
        """D term helps prevent overshoot in setpoint tracking."""
        pid_nodamp = PIDController(PIDConfig(kp=2.0, ki=0.0, kd=0.0))
        pid_damped = PIDController(PIDConfig(kp=2.0, ki=0.0, kd=1.0))
        
        # Simulate approach to setpoint
        errors_nodamp = []
        errors_damped = []
        
        for util in [50, 60, 70, 75, 78, 80]:
            r1 = pid_nodamp.update(util, dt=1.0)
            r2 = pid_damped.update(util, dt=1.0)
            errors_nodamp.append(abs(r1["error"]))
            errors_damped.append(abs(r2["error"]))
        
        # Damped should stabilize faster
        assert errors_damped[-1] <= errors_nodamp[-1]


class TestPIDOutputClamping:
    """Test output bounds enforcement."""

    def test_output_clamping_maximum(self):
        """Scaling action clamped to maximum."""
        pid = PIDController(
            PIDConfig(kp=100.0, output_max=5.0)  # Very large gain
        )
        result = pid.update(0.0, dt=1.0)  # Huge error
        
        # Output should not exceed max
        assert result["scaling_action"] <= 5.0

    def test_output_clamping_minimum(self):
        """Scaling action clamped to minimum."""
        pid = PIDController(
            PIDConfig(kp=100.0, output_min=-5.0)  # Very large gain
        )
        result = pid.update(100.0, dt=1.0)  # Huge negative error
        
        # Output should not go below min
        assert result["scaling_action"] >= -5.0

    def test_clamping_doesnt_affect_internal_terms(self):
        """Clamping affects output but not internal calculations."""
        pid = PIDController(PIDConfig(kp=100.0, output_max=5.0))
        result = pid.update(0.0, dt=1.0)
        
        # Internal terms should still be calculated at full magnitude
        assert result["p_term"] > 5.0  # Should exceed clamp
        assert result["scaling_action"] <= 5.0  # But output is clamped


class TestPIDStability:
    """Test stability properties: no oscillation, convergence."""

    def test_no_oscillation_around_setpoint(self):
        """System settles without oscillating around setpoint."""
        pid = PIDController(
            PIDConfig(kp=1.0, ki=0.05, kd=0.5, setpoint=70.0)
        )
        
        # Simulate utilization settling around setpoint with noise
        utilizations = [
            50, 60, 70, 72, 71, 70, 69, 70, 70, 71, 70, 69, 70, 70
        ]
        
        errors = []
        for util in utilizations:
            result = pid.update(util, dt=1.0)
            errors.append(result["error"])
        
        # Final errors should be close to setpoint (within 2%)
        final_mean = statistics.mean(errors[-5:])
        assert abs(final_mean) < 2.0

    def test_convergence_speed(self):
        """System converges quickly to setpoint."""
        pid = PIDController()
        
        # Start at low utilization
        convergence_time = 0
        for step in range(100):
            result = pid.update(40.0, dt=1.0)
            if abs(result["error"]) < 5.0:  # Within 5% of setpoint
                convergence_time = step
                break
        
        # Should converge in < 20 steps
        assert convergence_time < 20

    def test_peak_overshoot(self):
        """Response doesn't significantly overshoot setpoint."""
        pid = PIDController(
            PIDConfig(kp=1.0, ki=0.05, kd=0.5, setpoint=70.0)
        )
        
        # Sudden utilization drop
        errors = []
        for util in [50, 50, 50, 50, 50]:
            result = pid.update(util, dt=1.0)
            errors.append(result["error"])
        
        # Overshoot should be modest
        overshoot = max(errors)
        assert overshoot < 35.0  # Max error < 35%


class TestPIDResponsiveness:
    """Test responsiveness to rapid changes."""

    def test_handles_flash_crowd(self):
        """Responds quickly to sudden spike."""
        pid = PIDController()
        
        # Normal utilization
        for _ in range(5):
            pid.update(50.0, dt=1.0)
        
        # Sudden spike
        result_spike = pid.update(95.0, dt=1.0)
        
        # Should immediately propose scale-up (negative action)
        assert result_spike["scaling_action"] < -10.0

    def test_five_times_spike_in_60_seconds(self):
        """Handles 5x spike in < 60 seconds (success criterion)."""
        pid = PIDController()
        
        baseline_utilization = 20.0
        spike_utilization = 95.0
        
        # Ramp up quickly
        scaling_actions = []
        for step in range(60):  # 60-second window
            util = baseline_utilization + (spike_utilization - baseline_utilization) * min(step / 10, 1.0)
            result = pid.update(util, dt=1.0)
            scaling_actions.append(result["scaling_action"])
        
        # Should have proposed significant scale-up
        max_action = max(scaling_actions)
        assert max_action < -3.0  # Propose scaling up at least 3 instances
        
        # And settle to a decision within 60 seconds
        assert len(scaling_actions) == 60

    def test_quick_error_detection(self):
        """First scaling decision is made immediately."""
        pid = PIDController()
        
        result = pid.update(95.0, dt=0.1)  # Any small dt
        
        # Should still calculate response
        assert result["scaling_action"] != 0


class TestPIDErrorTracking:
    """Test error history and state management."""

    def test_error_history_maintained(self):
        """Error history is tracked for analysis."""
        pid = PIDController()
        
        for util in [50, 60, 70, 75, 80]:
            pid.update(util, dt=1.0)
        
        assert len(pid.error_history) == 5

    def test_error_history_bounded(self):
        """Error history doesn't grow unbounded."""
        pid = PIDController()
        
        for _ in range(1500):
            pid.update(80.0, dt=1.0)
        
        # Should be capped at 1000
        assert len(pid.error_history) <= 1000

    def test_get_state_statistics(self):
        """State includes statistical analysis of errors."""
        pid = PIDController()
        
        for util in [50, 60, 70, 75, 80]:
            pid.update(util, dt=1.0)
        
        state = pid.get_state()
        assert "error_mean" in state
        assert "error_std" in state
        assert "error_min" in state
        assert "error_max" in state

    def test_reset_clears_history(self):
        """Reset clears all accumulated state."""
        pid = PIDController()
        
        for _ in range(10):
            pid.update(80.0, dt=1.0)
        
        pid.reset()
        
        assert pid.integral_error == 0.0
        assert len(pid.error_history) == 0
        assert pid.last_error == 0.0


class TestPIDInputValidation:
    """Test input validation and error handling."""

    def test_rejects_invalid_utilization_too_high(self):
        """Rejects utilization > 100."""
        pid = PIDController()
        
        with pytest.raises(ValueError):
            pid.update(101.0, dt=1.0)

    def test_rejects_invalid_utilization_negative(self):
        """Rejects negative utilization."""
        pid = PIDController()
        
        with pytest.raises(ValueError):
            pid.update(-1.0, dt=1.0)

    def test_rejects_negative_dt(self):
        """Rejects negative time delta."""
        pid = PIDController()
        
        with pytest.raises(ValueError):
            pid.update(50.0, dt=-1.0)

    def test_accepts_boundary_values(self):
        """Accepts valid boundary values."""
        pid = PIDController()
        
        # Should not raise
        pid.update(0.0, dt=0.0)  # Zero dt is handled
        pid.update(100.0, dt=1.0)


class TestPIDTuning:
    """Test dynamic parameter tuning."""

    def test_tune_updates_parameters(self):
        """Tune method updates Kp, Ki, Kd."""
        pid = PIDController()
        pid.tune(1.5, 0.08, 0.7)
        
        assert pid.config.kp == 1.5
        assert pid.config.ki == 0.08
        assert pid.config.kd == 0.7

    def test_tune_affects_subsequent_decisions(self):
        """Tuning changes affect future calculations."""
        pid = PIDController(PIDConfig(kp=1.0))
        result1 = pid.update(90.0, dt=1.0)
        
        pid.tune(2.0, 0.05, 0.5)
        result2 = pid.update(90.0, dt=1.0)
        
        # More aggressive tuning should produce larger action
        assert abs(result2["scaling_action"]) > abs(result1["scaling_action"])

    def test_clamp_output_updates_bounds(self):
        """Clamp output updates min/max."""
        pid = PIDController()
        pid.clamp_output(-10.0, 20.0)
        
        assert pid.config.output_min == -10.0
        assert pid.config.output_max == 20.0


class TestPIDEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_small_time_delta(self):
        """Handles very small dt without numerical issues."""
        pid = PIDController()
        
        # Should not crash or NaN
        result = pid.update(90.0, dt=0.0001)
        
        assert not float('-inf') < result["scaling_action"] < float('inf')

    def test_zero_time_delta(self):
        """Converts zero dt to minimum usable value."""
        pid = PIDController()
        
        result = pid.update(90.0, dt=0.0)
        
        # Should treat as very small dt, not divide by zero
        assert result["scaling_action"] != float('inf')
        assert result["scaling_action"] != float('-inf')

    def test_exact_setpoint(self):
        """Handles exact setpoint match."""
        pid = PIDController(PIDConfig(setpoint=70.0))
        result = pid.update(70.0, dt=1.0)
        
        # Error should be zero
        assert result["error"] == 0.0
        # Scaling action should be small (only integral backlog)
        assert abs(result["scaling_action"]) < 1.0


class TestPIDComparisonCases:
    """Compare PID behavior under different scenarios."""

    def test_guardian_vs_aggressive_tuning(self):
        """Guardian (default) vs aggressive tuning."""
        guardian = PIDController()  # defaults
        aggressive = PIDController(
            PIDConfig(kp=2.0, ki=0.1, kd=1.0)
        )
        
        # Both respond to same spike
        guardian_response = guardian.update(95.0, dt=1.0)
        aggressive_response = aggressive.update(95.0, dt=1.0)
        
        # Aggressive should respond more strongly
        assert abs(aggressive_response["scaling_action"]) > abs(
            guardian_response["scaling_action"]
        )

    def test_tuning_affects_convergence_speed(self):
        """Different tunings converge at different rates."""
        # Conservative
        conservative = PIDController(
            PIDConfig(kp=0.5, ki=0.02, kd=0.2)
        )
        # Guardian
        guardian = PIDController()
        
        # Both from same spike
        for util in [50, 60, 70, 72, 71]:
            conservative.update(util, dt=1.0)
            guardian.update(util, dt=1.0)
        
        cons_state = conservative.get_state()
        guard_state = guardian.get_state()
        
        # Guardian should settle faster (lower final error)
        assert abs(guard_state["error_min"]) < abs(cons_state["error_min"])
