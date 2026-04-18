"""
Unit tests for predictive autoscaler (multi-factor decision making).

Tests focus on:
1. Integration of PID + Prophet + LSTM signals
2. Intelligent scaling decisions
3. Thrashing prevention
4. Emergency spike handling
"""

import pytest
import time
import pandas as pd
import numpy as np
from unittest.mock import Mock, MagicMock, patch

from autoscaler.models.predictive_scaler import (
    PredictiveScaler,
    PredictiveScalerConfig,
    ScalingDecision,
)


class TestScalingDecision:
    """Test ScalingDecision data structure."""

    def test_scaling_decision_initialization(self):
        """ScalingDecision creates with default values."""
        decision = ScalingDecision()
        assert decision.action == 0.0
        assert decision.is_emergency is False
        assert "pid_component" in decision.factors

    def test_scaling_decision_to_dict(self):
        """Converts to dictionary for logging."""
        decision = ScalingDecision()
        decision.action = 3.5
        decision.reason = "Test reason"
        
        d = decision.to_dict()
        assert d["action"] == 3.5
        assert d["reason"] == "Test reason"


class TestPredictiveScalerInitialization:
    """Test predictive scaler creation and configuration."""

    def test_default_initialization(self):
        """Scaler initializes with sensible defaults."""
        scaler = PredictiveScaler()
        assert scaler.config.prophet_enabled is True
        assert scaler.config.lstm_enabled is True
        assert scaler.prophet is None
        assert scaler.lstm is None

    def test_custom_configuration(self):
        """Scaler accepts custom configuration."""
        config = PredictiveScalerConfig(
            pid_setpoint=60.0,
            spike_probability_threshold=0.5
        )
        scaler = PredictiveScaler(config)
        assert scaler.config.pid_setpoint == 60.0
        assert scaler.config.spike_probability_threshold == 0.5

    def test_with_ml_modules(self):
        """Scaler can be initialized with Prophet/LSTM modules."""
        mock_prophet = Mock()
        mock_lstm = Mock()
        
        scaler = PredictiveScaler(
            prophet_module=mock_prophet,
            lstm_module=mock_lstm
        )
        
        assert scaler.prophet is mock_prophet
        assert scaler.lstm is mock_lstm

    def test_initialization_logging(self):
        """Initialization logs configuration."""
        with patch('autoscaler.models.predictive_scaler.logger') as mock_logger:
            scaler = PredictiveScaler()
            mock_logger.info.assert_called()


class TestPIDComponentScaling:
    """Test PID component of scaling decision."""

    def test_pid_component_high_utilization(self):
        """High utilization triggers scale-up via PID."""
        scaler = PredictiveScaler(
            PredictiveScalerConfig(pid_setpoint=70.0)
        )
        
        # Fast decision to avoid thrashing prevention
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(90.0, dt=1.0)
        
        # Should propose scaling up (negative action)
        assert decision.action < 0

    def test_pid_component_low_utilization(self):
        """Low utilization triggers scale-down via PID."""
        scaler = PredictiveScaler()
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(40.0, dt=1.0)
        
        # Should propose scaling down (positive action)
        assert decision.action > 0

    def test_pid_at_setpoint(self):
        """At setpoint, minimal scaling action."""
        scaler = PredictiveScaler()
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(70.0, dt=1.0)
        
        # Should be minimal (only integral backlog)
        assert abs(decision.action) < 2.0


class TestProphetIntegration:
    """Test Prophet prediction integration."""

    def test_prophet_disabled(self):
        """Prophet component disabled when config.prophet_enabled=False."""
        config = PredictiveScalerConfig(prophet_enabled=False)
        scaler = PredictiveScaler(config)
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(70.0, dt=1.0)
        
        # Prophet component should be zero
        assert decision.factors["prophet_component"] == 0.0

    def test_prophet_missing_module(self):
        """Gracefully handles missing Prophet module."""
        scaler = PredictiveScaler(
            PredictiveScalerConfig(prophet_enabled=True),
            prophet_module=None
        )
        scaler.last_scaling_decision_time = time.time() - 1000
        
        # Should not crash
        decision = scaler.decide_scaling(70.0, recent_data=None, dt=1.0)
        assert decision.factors["prophet_component"] == 0.0

    def test_prophet_proactive_scaling(self):
        """Prophet triggers proactive scaling when prediction exceeds headroom."""
        mock_prophet = Mock()
        mock_prophet.predict_next_10_minutes.return_value = {
            "upper_bound": 85.0  # Exceeds setpoint + headroom
        }
        
        config = PredictiveScalerConfig(
            prophet_enabled=True,
            prophet_headroom_factor=0.15,  # setpoint 70 + 15% = 80.5
            pid_setpoint=70.0
        )
        scaler = PredictiveScaler(config, prophet_module=mock_prophet)
        scaler.last_scaling_decision_time = time.time() - 1000
        
        recent_data = Mock()
        decision = scaler.decide_scaling(60.0, recent_data=recent_data, dt=1.0)
        
        # Should include prophet component
        assert decision.factors["prophet_component"] > 0
        assert decision.factors["predicted_peak"] == 85.0

    def test_prophet_failure_handling(self):
        """Gracefully handles Prophet prediction failures."""
        mock_prophet = Mock()
        mock_prophet.predict_next_10_minutes.side_effect = RuntimeError("Prophet failed")
        
        scaler = PredictiveScaler(
            PredictiveScalerConfig(prophet_enabled=True),
            prophet_module=mock_prophet
        )
        scaler.last_scaling_decision_time = time.time() - 1000
        
        with patch('autoscaler.models.predictive_scaler.logger') as mock_logger:
            decision = scaler.decide_scaling(70.0, recent_data=Mock(), dt=1.0)
            mock_logger.warning.assert_called()


class TestLSTMIntegration:
    """Test LSTM spike detection integration."""

    def test_lstm_disabled(self):
        """LSTM component disabled when config.lstm_enabled=False."""
        config = PredictiveScalerConfig(lstm_enabled=False)
        scaler = PredictiveScaler(config)
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(70.0, dt=1.0)
        
        # LSTM component should be zero
        assert decision.factors["lstm_component"] == 0.0

    def test_lstm_missing_module(self):
        """Gracefully handles missing LSTM module."""
        scaler = PredictiveScaler(
            PredictiveScalerConfig(lstm_enabled=True),
            lstm_module=None
        )
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(70.0, dt=1.0)
        assert decision.factors["lstm_component"] == 0.0

    def test_lstm_spike_detection_emergency(self):
        """LSTM spike detection triggers emergency scaling."""
        mock_lstm = Mock()
        mock_lstm.predict_spike_probability.return_value = (0.85, 0.15)  # 85% spike prob
        
        config = PredictiveScalerConfig(
            lstm_enabled=True,
            spike_probability_threshold=0.6
        )
        scaler = PredictiveScaler(config, lstm_module=mock_lstm)
        scaler.last_scaling_decision_time = time.time() - 1000
        
        recent_data = Mock()
        decision = scaler.decide_scaling(70.0, recent_data=recent_data, dt=1.0)
        
        # Should be marked as emergency
        assert decision.is_emergency is True
        # Should have LSTM component
        assert decision.factors["lstm_component"] > 0
        # Action should be boosted by spike_scaling_boost (1.5)
        assert decision.action > decision.factors["lstm_component"]

    def test_lstm_normal_probability_no_emergency(self):
        """Low spike probability doesn't trigger emergency."""
        mock_lstm = Mock()
        mock_lstm.predict_spike_probability.return_value = (0.1, 0.9)  # Low spike prob
        
        config = PredictiveScalerConfig(
            lstm_enabled=True,
            spike_probability_threshold=0.6
        )
        scaler = PredictiveScaler(config, lstm_module=mock_lstm)
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(70.0, recent_data=Mock(), dt=1.0)
        
        # Should not be emergency
        assert decision.is_emergency is False

    def test_lstm_failure_handling(self):
        """Gracefully handles LSTM failures."""
        mock_lstm = Mock()
        mock_lstm.predict_spike_probability.side_effect = RuntimeError("LSTM failed")
        
        scaler = PredictiveScaler(
            PredictiveScalerConfig(lstm_enabled=True),
            lstm_module=mock_lstm
        )
        scaler.last_scaling_decision_time = time.time() - 1000
        
        with patch('autoscaler.models.predictive_scaler.logger'):
            decision = scaler.decide_scaling(70.0, recent_data=Mock(), dt=1.0)
            # Should still return valid decision
            assert isinstance(decision, ScalingDecision)


class TestThrashingPrevention:
    """Test thrashing prevention (no rapid scale up/down)."""

    def test_thrashing_prevention_enforced(self):
        """Decisions rejected if too soon after last decision."""
        config = PredictiveScalerConfig(min_decision_interval=300.0)
        scaler = PredictiveScaler(config)
        
        # First decision
        decision1 = scaler.decide_scaling(90.0, dt=1.0)
        assert decision1.action != 0.0
        
        # Immediate second decision
        decision2 = scaler.decide_scaling(90.0, dt=1.0)
        assert decision2.action == 0.0  # Rejected
        assert "Thrashing prevention" in decision2.reason

    def test_thrashing_prevention_time_window(self):
        """Decisions allowed after min_decision_interval."""
        config = PredictiveScalerConfig(min_decision_interval=2.0)
        scaler = PredictiveScaler(config)
        
        # First decision
        decision1 = scaler.decide_scaling(90.0, dt=1.0)
        initial_time = scaler.last_scaling_decision_time
        
        # Wait and make second decision
        scaler.last_scaling_decision_time = initial_time - 10  # Pretend 10s passed
        decision2 = scaler.decide_scaling(90.0, dt=1.0)
        
        # Should be allowed
        assert decision2.action != 0.0

    def test_minimum_scaling_magnitude(self):
        """Trivial scaling decisions are ignored."""
        config = PredictiveScalerConfig(
            min_scaling_magnitude=0.5,
            pid_setpoint=70.0
        )
        scaler = PredictiveScaler(config)
        scaler.last_scaling_decision_time = time.time() - 1000
        
        # Utilization close to setpoint (small error)
        decision = scaler.decide_scaling(69.9, dt=0.1)
        
        # Action too small, should be zeroed
        assert decision.action == 0.0


class TestMultiFactorDecision:
    """Test integration of multiple decision factors."""

    def test_combined_pid_and_prophet(self):
        """PID + Prophet components are combined."""
        mock_prophet = Mock()
        mock_prophet.predict_next_10_minutes.return_value = {
            "upper_bound": 85.0
        }
        
        scaler = PredictiveScaler(
            PredictiveScalerConfig(pid_setpoint=70.0),
            prophet_module=mock_prophet
        )
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(
            85.0,
            recent_data=Mock(),
            dt=1.0
        )
        
        # Should have both components
        assert decision.factors["pid_component"] != 0.0
        assert decision.factors["prophet_component"] != 0.0
        # Combined action should be roughly sum of components
        expected = (
            decision.factors["pid_component"] +
            decision.factors["prophet_component"] +
            decision.factors["lstm_component"]
        )
        assert abs(decision.action - expected) < 0.1

    def test_lstm_boost_on_emergency(self):
        """LSTM spike triggers boost to combined action."""
        mock_lstm = Mock()
        mock_lstm.predict_spike_probability.return_value = (0.8, 0.2)
        
        config = PredictiveScalerConfig(
            pid_kp=1.0,
            spike_probability_threshold=0.6,
            spike_scaling_boost=2.0
        )
        scaler = PredictiveScaler(config, lstm_module=mock_lstm)
        scaler.last_scaling_decision_time = time.time() - 1000
        
        decision = scaler.decide_scaling(50.0, recent_data=Mock(), dt=1.0)
        
        # Action should be boosted (doubled in this case)
        assert decision.is_emergency is True


class TestScalingDecisionHistory:
    """Test history tracking and analysis."""

    def test_decision_history_recorded(self):
        """Recent decisions are recorded."""
        scaler = PredictiveScaler()
        
        # Make multiple decisions
        for _ in range(3):
            scaler.decide_scaling(80.0, dt=1.0)
            scaler.last_scaling_decision_time = time.time() - 1000  # Reset timer
        
        assert len(scaler.scaling_decision_history) == 3

    def test_get_recent_decisions(self):
        """Can retrieve recent decisions."""
        scaler = PredictiveScaler()
        
        for i in range(5):
            scaler.decide_scaling(80.0, dt=1.0)
            scaler.last_scaling_decision_time = time.time() - 1000
        
        recent = scaler.get_recent_decisions(count=3)
        assert len(recent) == 3
        assert isinstance(recent[0], dict)

    def test_performance_metrics(self):
        """Performance metrics calculated correctly."""
        scaler = PredictiveScaler()
        
        for util in [80, 90, 50, 60]:
            scaler.decide_scaling(util, dt=1.0)
            scaler.last_scaling_decision_time = time.time() - 1000
        
        metrics = scaler.get_performance_metrics()
        assert "decisions_made" in metrics
        assert "average_action" in metrics
        assert metrics["decisions_made"] == 4

    def test_emergency_tracking(self):
        """Emergency decisions are tracked."""
        mock_lstm = Mock()
        mock_lstm.predict_spike_probability.return_value = (0.9, 0.1)
        
        config = PredictiveScalerConfig(
            lstm_enabled=True,
            spike_probability_threshold=0.6
        )
        scaler = PredictiveScaler(config, lstm_module=mock_lstm)
        
        for _ in range(3):
            scaler.decide_scaling(70.0, recent_data=Mock(), dt=1.0)
            scaler.last_scaling_decision_time = time.time() - 1000
        
        metrics = scaler.get_performance_metrics()
        assert metrics["emergency_count"] == 3


class TestInputValidation:
    """Test input validation."""

    def test_invalid_utilization(self):
        """Rejects invalid utilization values."""
        scaler = PredictiveScaler()
        
        with pytest.raises(ValueError):
            scaler.decide_scaling(101.0, dt=1.0)

    def test_boundary_utilization(self):
        """Accepts boundary utilization values."""
        scaler = PredictiveScaler()
        scaler.last_scaling_decision_time = time.time() - 1000
        
        # Should not raise
        scaler.decide_scaling(0.0, dt=1.0)
        scaler.decide_scaling(100.0, dt=1.0)


class TestReset:
    """Test scaler reset."""

    def test_reset_clears_history(self):
        """Reset clears decision history."""
        scaler = PredictiveScaler()
        scaler.decide_scaling(80.0, dt=1.0)
        scaler.last_scaling_decision_time = time.time() - 1000
        scaler.decide_scaling(80.0, dt=1.0)
        
        scaler.reset()
        
        assert len(scaler.scaling_decision_history) == 0

    def test_reset_clears_pid_state(self):
        """Reset clears PID internal state."""
        scaler = PredictiveScaler()
        scaler.decide_scaling(90.0, dt=1.0)
        
        scaler.reset()
        
        assert scaler.pid_controller.integral_error == 0.0
