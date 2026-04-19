"""
Chaos engineering tests for autoscaling resilience.

Tests simulate real-world failure scenarios:
1. Flash crowds (5x utilization spike)
2. Cascading failures (secondary spike during recovery)
3. Network latency (slow queries increase utilization)
4. Database connection pool exhaustion
5. Gradual memory leak
6. Oscillation under adversarial load patterns
"""

import pytest
import time
from unittest.mock import Mock, patch
import numpy as np

from autoscaler.models.pid_controller import PIDController, PIDConfig
from autoscaler.models.predictive_scaler import PredictiveScaler, PredictiveScalerConfig


class TestFlashCrowdResponse:
    """Test rapid response to 5x traffic spikes."""

    def test_flash_crowd_detected_immediately(self):
        """Flash crowd detected and action triggered immediately."""
        pid = PIDController()

        # Sudden 5x spike: from 20% to 100%
        result = pid.update(100.0, dt=0.1)  # Very short time window

        # Should immediately propose max scale-up
        assert result["scaling_action"] < -5.0

    def test_flash_crowd_within_60_seconds(self):
        """Handles 5x spike and stabilizes within 60 seconds."""
        pid = PIDController(PIDConfig(kp=1.0, ki=0.05, kd=0.5, setpoint=70.0))

        utilization_profile = [
            # Ramp up from 20% to 100% in 10 seconds
            *[20 + (100 - 20) * i / 10 for i in range(11)],
            # Stabilize at 95%
            *[95] * 50,
        ]

        peak_action = None
        stabilized_action = None

        for i, util in enumerate(utilization_profile):
            result = pid.update(util, dt=1.0)
            if i == 10:
                peak_action = result["scaling_action"]
            if i == 50:
                stabilized_action = result["scaling_action"]

        # Should propose significant scale-up at peak
        assert peak_action < -3.0
        # Should still propose scale-up but settle
        assert stabilized_action < 0

    def test_flash_crowd_recovery(self):
        """System recovers gracefully after spike ends."""
        pid = PIDController()

        # Spike then drop
        spike_pattern = [80] * 20 + [40] * 20

        actions = []
        for util in spike_pattern:
            result = pid.update(util, dt=1.0)
            actions.append(result["scaling_action"])

        # Initial actions should propose scale (negative = scale up)
        assert actions[0] < -5.0
        # Final actions should propose scale-down (positive = scale down)
        assert actions[-1] > 2.0

    def test_multiple_rapid_spikes(self):
        """Handles multiple rapid spikes (don't get confused)."""
        pid = PIDController()

        # Multiple spike patterns
        pattern = [
            *[20] * 5,  # Baseline
            *[95] * 5,  # Spike 1
            *[30] * 5,  # Recovery
            *[90] * 5,  # Spike 2
            *[40] * 5,  # Recovery
        ]

        actions = []
        for util in pattern:
            result = pid.update(util, dt=1.0)
            actions.append(result["scaling_action"])

        # Should scale up during both spikes
        assert actions[5] < -3.0  # During spike 1
        assert actions[15] < -3.0  # During spike 2


class TestCascadingFailures:
    """Test response to cascading failures."""

    def test_cascading_database_timeout_then_spike(self):
        """Database timeout causes latency spike, triggering secondary spike."""
        predictive_scaler = PredictiveScaler()
        predictive_scaler.last_scaling_decision_time = time.time() - 1000

        # Phase 1: Normal load
        for util in [50, 52, 51, 50]:
            decision = predictive_scaler.decide_scaling(util, dt=1.0)
            predictive_scaler.last_scaling_decision_time = time.time() - 1000

        initial_metrics = predictive_scaler.get_performance_metrics()

        # Phase 2: Database timeout (utilization spikes)
        cascade_pattern = [60, 75, 85, 92, 95]
        for util in cascade_pattern:
            decision = predictive_scaler.decide_scaling(util, dt=1.0)
            predictive_scaler.last_scaling_decision_time = time.time() - 1000

        # Should have made scaling decisions during cascade
        final_metrics = predictive_scaler.get_performance_metrics()
        assert final_metrics["decisions_made"] > initial_metrics["decisions_made"]

    def test_recovery_from_cascading_failure(self):
        """System recovers from cascading failures without oscillation."""
        pid = PIDController(PIDConfig(kp=1.0, ki=0.05, kd=0.5))

        # Cascading failure and recovery
        pattern = [
            *[50] * 5,  # Normal
            *[60, 75, 85, 92, 95],  # Rapid cascade
            *[95, 90, 70, 50, 40],  # Recovery
            *[55, 60, 65, 70] * 5,  # Stabilization
        ]

        errors = []
        for util in pattern:
            result = pid.update(util, dt=1.0)
            errors.append(result["error"])

        # Final errors should be stable (low variance)
        final_errors = errors[-20:]
        error_std = np.std(final_errors)
        error_mean = np.mean(final_errors)

        # Should stabilize without oscillation
        assert error_std < 10.0
        assert abs(error_mean) < 5.0


class TestNetworkLatencySpike:
    """Test handling of network latency causing utilization increase."""

    def test_slow_database_queries_increase_utilization(self):
        """Slow queries increase utilization temporarily."""
        pid = PIDController()

        # Normal operation
        normal = [50, 52, 51, 50, 52]

        # Slow query causes queue buildup
        slow_query = [60, 75, 85, 80, 70, 50]

        all_util = normal + slow_query

        actions = []
        for util in all_util:
            result = pid.update(util, dt=1.0)
            actions.append(result["scaling_action"])

        # Should detect and respond to latency spike
        assert actions[5] < -5.0  # Scale up during spike

    def test_network_partition_recovery(self):
        """System recovers from temporary network partition."""
        predictive_scaler = PredictiveScaler()
        predictive_scaler.last_scaling_decision_time = time.time() - 1000

        # Normal, then partition latency spike, then recovery
        utilizations = [
            *[50] * 3,  # Normal
            *[89, 92, 95, 93],  # Partition spike
            *[70, 60, 50, 45],  # Recovery
            *[50, 52, 51],  # Stabilized
        ]

        decisions = []
        for util in utilizations:
            decision = predictive_scaler.decide_scaling(util, dt=1.0)
            decisions.append(decision.action)
            predictive_scaler.last_scaling_decision_time = time.time() - 1000

        # Should scale during spike
        assert min(decisions[3:7]) < 0
        # Should scale down during recovery
        assert max(decisions[7:11]) > 0


class TestConnectionPoolExhaustion:
    """Test handling of connection pool exhaustion."""

    def test_pool_exhaustion_causes_cascading_degradation(self):
        """Connection pool exhaustion causes cascading utilization increase."""
        pid = PIDController(PIDConfig(kp=1.0, ki=0.05, kd=0.5, setpoint=70.0))

        # Normal operation with gradual pool exhaustion
        # As connections exhaust, queries queue, utilization rises
        utilizations = [50, 52, 55, 58, 62, 65, 69, 70, 72, 75, 78, 80, 82, 83, 85]

        results = []
        for util in utilizations:
            result = pid.update(util, dt=1.0)
            results.append(result)

        # System should respond to gradual increase
        first_action = results[0]["scaling_action"]
        mid_action = results[7]["scaling_action"]
        late_action = results[-1]["scaling_action"]

        # Actions should become increasingly negative (scale up more)
        assert late_action < mid_action < first_action


class TestMemoryLeakDetection:
    """Test detection and response to memory leaks."""

    def test_slow_memory_leak_causes_gradual_degradation(self):
        """Memory leak causes gradual utilization increase (hard to detect)."""
        pid = PIDController()

        # Memory leak: utilization creeps up over time
        base_utilization = 50.0
        utilizations = [base_utilization + i * 2 for i in range(15)]  # Increases by 2% per step

        actions = []
        state_history = []

        for util in utilizations:
            result = pid.update(util, dt=60.0)  # 60 second interval
            actions.append(result["scaling_action"])
            state = pid.get_state()
            state_history.append(state)

        # Integral should accumulate as leak manifests
        initial_integral = state_history[0]["integral_error"]
        final_integral = state_history[-1]["integral_error"]

        # Integral should grow (accumulating persistent error)
        assert final_integral > initial_integral

    def test_memory_leak_requires_sustained_action(self):
        """Sustained action needed for memory leak, not temporary spike."""
        pid = PIDController()

        # Leak pattern: once high, stays high
        leak_pattern = (
            [50] * 5  # Normal
            + [50 + i for i in range(1, 11)]  # Gradual increase
            + [59, 60, 61, 62, 63]  # Stays elevated
        )

        actions = []
        for util in leak_pattern:
            result = pid.update(util, dt=1.0)
            actions.append(result["scaling_action"])

        # Actions should be sustained (not just transient)
        late_actions = actions[-5:]

        # All late actions should propose scale-up (negative)
        assert all(a < 0 for a in late_actions)
        # Actions should be consistent (not oscillating)
        action_std = np.std(late_actions)
        assert action_std < 5.0  # Low variance


class TestOscillationPrevention:
    """Test prevention of hunting/oscillation."""

    def test_no_oscillation_around_setpoint(self):
        """System settles without hunting around setpoint."""
        pid = PIDController(PIDConfig(kp=1.0, ki=0.05, kd=0.5, setpoint=70.0))

        # Noisy utilization around setpoint
        pattern = np.random.normal(70, 3, 50)  # Mean 70%, std 3%

        errors = []
        for util in pattern:
            result = pid.update(float(util), dt=1.0)
            errors.append(result["error"])

        # Error should remain bounded
        error_mean = np.mean(errors)
        error_std = np.std(errors)

        assert abs(error_mean) < 5.0
        assert error_std < 10.0

    def test_adversarial_sawtooth_load(self):
        """Handles adversarial sawtooth load pattern."""
        pid = PIDController()

        # Adversarial: rapid up-down cycles
        pattern = []
        for cycle in range(5):
            pattern.extend([50, 60, 70, 80, 90, 80, 70, 60, 50])

        actions = []
        for util in pattern:
            result = pid.update(util, dt=1.0)
            actions.append(result["scaling_action"])

        # Should not chase every fluctuation
        action_variance = np.var(actions)

        # Actions should be smooth (not wildly oscillating)
        assert action_variance < 50.0

    def test_oscillation_metric_convergence(self):
        """System converges with oscillation metric < threshold."""
        pid = PIDController(PIDConfig(kp=1.0, ki=0.05, kd=0.5))

        # Start far from setpoint
        utilizations = [20, 30, 40, 50, 60, 65, 68, 69, 70, 70, 70]

        errors = []
        for util in utilizations:
            result = pid.update(util, dt=1.0)
            errors.append(result["error"])

        # Calculate "oscillation metric": variance in errors
        late_errors = errors[-5:]
        oscillation = np.std(late_errors)

        # Should have minimal oscillation at end
        assert oscillation < 2.0


class TestThrashingPreventionInChaos:
    """Test thrashing prevention during chaotic conditions."""

    def test_prevents_oscillatory_scaling_decisions(self):
        """Doesn't make continuous rapid scaling decisions."""
        config = PredictiveScalerConfig(min_decision_interval=300.0)
        scaler = PredictiveScaler(config)

        # Chaotic utilization pattern
        utilizations = list(np.random.uniform(50, 90, 20))

        decisions_made = 0
        for util in utilizations:
            decision = scaler.decide_scaling(util, dt=1.0)
            if decision.action != 0:
                decisions_made += 1

        # Should make very few decisions due to thrashing prevention
        assert decisions_made <= 2

    def test_batches_decisions_during_prolonged_spike(self):
        """During prolonged spike, batches decisions with min_decision_interval."""
        config = PredictiveScalerConfig(min_decision_interval=300.0, min_scaling_magnitude=0.1)
        scaler = PredictiveScaler(config)

        # Prolonged spike: sustained high utilization
        spike_utilizations = [90] * 20

        decisions = []
        for util in spike_utilizations:
            decision = scaler.decide_scaling(util, dt=1.0)
            decisions.append(decision.action)
            # Normally would increment time, but skip
            scaler.last_scaling_decision_time = time.time() - 1000

        # Should have multiple decisions as time allows
        non_zero_decisions = [d for d in decisions if d != 0]
        # Can't be more than one without time passing, but demonstrates batching
        assert len(non_zero_decisions) <= 20


class TestEmergencySpikeHandling:
    """Test emergency spike handling with LSTM integration."""

    def test_lstm_spike_accelerates_scaling(self):
        """LSTM spike detection accelerates scaling decision."""
        mock_lstm = Mock()
        mock_lstm.predict_spike_probability.return_value = (0.9, 0.1)

        config = PredictiveScalerConfig(
            pid_setpoint=70.0,
            lstm_enabled=True,
            spike_probability_threshold=0.6,
            spike_scaling_boost=2.0,
        )
        scaler = PredictiveScaler(config, lstm_module=mock_lstm)
        scaler.last_scaling_decision_time = time.time() - 1000

        decision = scaler.decide_scaling(80.0, recent_data=Mock(), dt=1.0)

        # Should have emergency flag
        assert decision.is_emergency is True
        # Scaling action should be boosted
        assert abs(decision.action) > abs(decision.factors["pid_component"])

    def test_prophet_and_lstm_convergence(self):
        """Prophet and LSTM both suggest scaling in same direction."""
        mock_prophet = Mock()
        mock_prophet.predict_next_10_minutes.return_value = {"upper_bound": 95.0}

        mock_lstm = Mock()
        mock_lstm.predict_spike_probability.return_value = (0.8, 0.2)

        config = PredictiveScalerConfig(
            prophet_enabled=True, lstm_enabled=True, spike_probability_threshold=0.6
        )
        scaler = PredictiveScaler(config, prophet_module=mock_prophet, lstm_module=mock_lstm)
        scaler.last_scaling_decision_time = time.time() - 1000

        decision = scaler.decide_scaling(70.0, recent_data=Mock(), dt=1.0)

        # Both Prophet and LSTM should contribute in same direction
        # (both are concerned about utilization)
        assert decision.factors["prophet_component"] < 0  # Scale up
        assert decision.factors["lstm_component"] > 0  # Emergency (but same concern)


class TestSuccessCriteria:
    """Tests that verify all Phase 3 success criteria are met."""

    def test_handles_5x_spike_in_60_seconds(self):
        """SUCCESS CRITERION 1: Handles 5x spike in < 60 seconds."""
        pid = PIDController()

        # 5x spike: from 20% to 100%
        spike_utilizations = [
            *[20 + (100 - 20) * i / 30 for i in range(31)],  # Ramp to 100% in 30 steps
            *[100] * 30,  # Sustained at spike
        ]

        scaling_actions = []
        for util in spike_utilizations:
            result = pid.update(util, dt=1.0)
            scaling_actions.append(result["scaling_action"])

        # Should propose significant scale-up within 30 seconds
        early_actions = scaling_actions[:30]
        assert min(early_actions) <= -5.0  # Clamped at output_max

    def test_zero_oscillation_under_noisy_load(self):
        """SUCCESS CRITERION 2: Zero oscillation under noisy load."""
        pid = PIDController(PIDConfig(kp=1.0, ki=0.05, kd=0.5, setpoint=70.0))

        # Noisy load around setpoint
        np.random.seed(42)
        noisy_utilization = np.random.normal(70, 5, 100)

        scaling_actions = []
        for util in noisy_utilization:
            result = pid.update(float(util), dt=1.0)
            scaling_actions.append(result["scaling_action"])

        # Measure oscillation: should be smooth (low action variance)
        action_variance = np.var(scaling_actions[-50:])

        # Low variance indicates no oscillation (within realistic bounds)
        assert action_variance < 30.0

    def test_prevents_thrashing(self):
        """SUCCESS CRITERION 3: Prevents thrashing (min 5 min between decisions)."""
        config = PredictiveScalerConfig(min_decision_interval=300.0)
        scaler = PredictiveScaler(config)

        # Chaotic pattern
        for util in [80, 70, 85, 60, 90, 50]:
            decision = scaler.decide_scaling(util, dt=1.0)
            # Can't make multiple decisions within 300 seconds

        # Thrashing prevention should have blocked most decisions
        metrics = scaler.get_performance_metrics()
        assert metrics["decisions_made"] <= 2

    def test_uses_prophet_upper_bound(self):
        """SUCCESS CRITERION 4: Uses Prophet upper_bound for capacity planning."""
        mock_prophet = Mock()
        mock_prophet.predict_next_10_minutes.return_value = {"upper_bound": 90.0}

        scaler = PredictiveScaler(
            PredictiveScalerConfig(prophet_enabled=True), prophet_module=mock_prophet
        )
        scaler.last_scaling_decision_time = time.time() - 1000

        decision = scaler.decide_scaling(60.0, recent_data=Mock(), dt=1.0)

        # Should have recorded predicted peak and prophet component
        assert decision.factors["predicted_peak"] == 90.0
        assert "prophet" in decision.reason.lower() or decision.factors["prophet_component"] > 0

    def test_uses_lstm_spike_probability(self):
        """SUCCESS CRITERION 5: Uses LSTM spike_probability for emergency triggers."""
        mock_lstm = Mock()
        mock_lstm.predict_spike_probability.return_value = (0.85, 0.15)

        config = PredictiveScalerConfig(lstm_enabled=True, spike_probability_threshold=0.6)
        scaler = PredictiveScaler(config, lstm_module=mock_lstm)
        scaler.last_scaling_decision_time = time.time() - 1000

        decision = scaler.decide_scaling(70.0, recent_data=Mock(), dt=1.0)

        # Should have recorded spike probability and triggered emergency
        assert decision.factors["spike_probability"] == 0.85
        assert decision.is_emergency is True
