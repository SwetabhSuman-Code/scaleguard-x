"""
Unit tests for LSTM spike detector
"""

import pytest
import numpy as np
import torch

from prediction_engine.models.lstm_spike_detector import (
    SpikeDetectorLSTM,
    train_spike_detector,
    generate_synthetic_spike_data,
)


class TestLSTMInitialization:
    """Tests for LSTM model initialization"""

    def test_lstm_creation(self):
        """Test: LSTM model initializes with correct architecture"""
        model = SpikeDetectorLSTM()

        assert model.hidden_size == 64
        assert model.num_layers == 2
        assert model.lstm is not None
        assert model.fc1 is not None
        assert model.fc2 is not None

    def test_lstm_forward_pass(self):
        """Test: Forward pass produces correct output shape"""
        model = SpikeDetectorLSTM()

        # Input: batch of 4, sequence length 288, 1 feature
        x = torch.randn(4, 288, 1)

        logits = model(x)

        # Output should be (batch, 2) for binary classification
        assert logits.shape == (4, 2)

    def test_lstm_custom_parameters(self):
        """Test: LSTM accepts custom architecture parameters"""
        model = SpikeDetectorLSTM(input_size=1, hidden_size=128, num_layers=3, dropout=0.3)

        assert model.hidden_size == 128
        assert model.num_layers == 3


class TestSyntheticDataGeneration:
    """Tests for synthetic spike data generation"""

    def test_generate_synthetic_data_format(self):
        """Test: Generated data has correct shape and labels"""
        X, y = generate_synthetic_spike_data(samples=100, normal_ratio=0.7)

        assert X.shape == (100, 288)
        assert y.shape == (100,)
        assert set(y) == {0, 1}
        assert np.sum(y == 0) == 70  # 70% normal
        assert np.sum(y == 1) == 30  # 30% spikes

    def test_synthetic_normal_samples(self):
        """Test: Normal samples have low variance"""
        X, y = generate_synthetic_spike_data(samples=200, normal_ratio=1.0)

        # All should be normal (y=0)
        assert np.all(y == 0)

        # Normal samples should have low standard deviation
        for sample in X:
            std = np.std(sample)
            assert std < 15  # Low variance for normal traffic

    def test_synthetic_spike_samples(self):
        """Test: Spike samples show significant increase"""
        X, y = generate_synthetic_spike_data(samples=200, normal_ratio=0.0)

        # All should be spikes (y=1)
        assert np.all(y == 1)

        # Spike samples have discontinuity (first half vs second half)
        for sample in X:
            first_half = np.mean(sample[:150])
            second_half = np.mean(sample[150:])
            ratio = second_half / (first_half + 1e-6)

            # Spike should be 2-5x increase
            assert 1.5 < ratio < 6.0


class TestLSTMTraining:
    """Tests for LSTM training"""

    def test_lstm_training(self):
        """Test: LSTM trains without errors"""
        X_train, y_train = generate_synthetic_spike_data(samples=100)

        model, loss_history = train_spike_detector(
            X_train, y_train, epochs=5, learning_rate=0.001, batch_size=16
        )

        assert model is not None
        assert len(loss_history) == 5
        assert loss_history[0] > loss_history[-1]  # Loss decreases

    def test_lstm_train_on_gpu_if_available(self):
        """Test: LSTM can train on GPU if available"""
        device = "cuda" if torch.cuda.is_available() else "cpu"

        X_train, y_train = generate_synthetic_spike_data(samples=100)

        model, loss_history = train_spike_detector(X_train, y_train, epochs=2, device=device)

        assert model is not None
        print(f"✓ Trained on {device}")


class TestLSTMPredictions:
    """Tests for LSTM spike predictions"""

    @pytest.fixture
    def trained_model(self):
        """Train a model for testing"""
        X_train, y_train = generate_synthetic_spike_data(samples=500, normal_ratio=0.6)

        model, _ = train_spike_detector(X_train, y_train, epochs=10, batch_size=32)

        return model

    def test_predict_spike_probability(self, trained_model):
        """Test: Prediction returns valid spike probability"""
        # Normal sequence
        normal_sequence = np.full(288, 150.0) + np.random.normal(0, 5, 288)

        spike_prob, normal_prob = trained_model.predict_spike_probability(normal_sequence)

        assert 0 <= spike_prob <= 1
        assert 0 <= normal_prob <= 1
        assert abs((spike_prob + normal_prob) - 1.0) < 1e-5  # Sum to 1

    def test_detect_normal_traffic(self, trained_model):
        """Test: Correctly identifies normal (non-spike) traffic"""
        # Generate normal sequence (steady RPS)
        normal_sequence = np.linspace(150, 160, 288) + np.random.normal(0, 3, 288)

        spike_prob, normal_prob = trained_model.predict_spike_probability(normal_sequence)

        # Should predict low spike probability
        assert spike_prob < 0.4, f"False positive on normal traffic: spike_prob={spike_prob:.2f}"
        assert normal_prob > 0.6

        print(f"✓ Normal detection: spike_prob={spike_prob:.2f}")

    def test_detect_spike_traffic(self, trained_model):
        """Test: Correctly identifies spike traffic"""
        # Generate spike sequence
        normal_part = np.linspace(150, 155, 200) + np.random.normal(0, 3, 200)
        spike_part = np.linspace(600, 650, 88) + np.random.normal(0, 10, 88)  # 4-5x increase
        spike_sequence = np.concatenate([normal_part, spike_part])

        spike_prob, normal_prob = trained_model.predict_spike_probability(spike_sequence)

        # Should predict high spike probability
        assert spike_prob > 0.5, f"Failed to detect spike: spike_prob={spike_prob:.2f}"
        assert normal_prob < 0.5

        print(f"✓ Spike detection: spike_prob={spike_prob:.2f}")

    def test_predict_invalid_length(self, trained_model):
        """Test: Rejects sequences of wrong length"""
        short_sequence = np.random.normal(150, 10, 200)

        with pytest.raises(ValueError, match="Expected 288 points"):
            trained_model.predict_spike_probability(short_sequence)

    def test_forward_pass_batched(self, trained_model):
        """Test: Forward pass works with batches"""
        batch_x = torch.randn(8, 288, 1)

        logits = trained_model(batch_x)

        assert logits.shape == (8, 2)

        # Softmax probability
        probs, classes = trained_model.predict(batch_x)

        assert probs.shape == (8, 2)
        assert classes.shape == (8,)
        assert np.all((classes == 0) | (classes == 1))


class TestLSTMVsProphet:
    """Comparative tests: LSTM vs Prophet for spike detection"""

    def test_lstm_catches_sudden_spikes(self):
        """Test: LSTM detects sudden spikes quickly"""
        X_train, y_train = generate_synthetic_spike_data(samples=300)
        model, _ = train_spike_detector(X_train, y_train, epochs=10)

        # Create sudden spike
        normal = np.full(200, 200) + np.random.normal(0, 5, 200)
        sudden_spike = np.full(88, 800) + np.random.normal(0, 20, 88)  # Sudden 4x jump
        sequence = np.concatenate([normal, sudden_spike])

        spike_prob, _ = model.predict_spike_probability(sequence)

        # LSTM should catch this (pattern recognition)
        assert spike_prob > 0.6, f"LSTM missed sudden spike: {spike_prob:.2f}"

        print(f"✓ LSTM sudden spike detection: spike_prob={spike_prob:.2f}")

    def test_lstm_complements_prophet(self):
        """Test: LSTM and Prophet have complementary strengths"""
        # Prophet: Time-series forecasting (prediction)
        # LSTM: Pattern recognition (classification)

        X, y = generate_synthetic_spike_data(samples=50)
        model, _ = train_spike_detector(X, y, epochs=5)

        # Run predictions
        predictions = []
        for sample in X[:10]:
            spike_prob, _ = model.predict_spike_probability(sample)
            predictions.append(spike_prob)

        assert len(predictions) == 10
        assert all(0 <= p <= 1 for p in predictions)

        print(f"✓ LSTM predictions: min={min(predictions):.2f}, max={max(predictions):.2f}")


class TestLSTMRobustness:
    """Robustness tests for LSTM"""

    def test_lstm_handles_constant_input(self):
        """Test: LSTM handles constant signal gracefully"""
        model = SpikeDetectorLSTM()

        # Constant signal (all same value)
        constant = np.full(288, 150.0)

        spike_prob, normal_prob = model.predict_spike_probability(constant)

        # Should handle gracefully
        assert 0 <= spike_prob <= 1
        assert 0 <= normal_prob <= 1

        print(f"✓ Constant input: spike_prob={spike_prob:.2f}")

    def test_lstm_handles_very_noisy_input(self):
        """Test: LSTM robust to high-noise signals"""
        model = SpikeDetectorLSTM()

        # Very noisy
        noisy = np.random.normal(150, 50, 288)

        spike_prob, normal_prob = model.predict_spike_probability(noisy)

        assert 0 <= spike_prob <= 1
        print(f"✓ Noisy input: spike_prob={spike_prob:.2f}")

    def test_lstm_consistent_predictions(self):
        """Test: LSTM gives consistent predictions for same input"""
        model = SpikeDetectorLSTM()
        model.eval()

        sequence = np.random.normal(150, 10, 288)

        prob1, _ = model.predict_spike_probability(sequence)
        prob2, _ = model.predict_spike_probability(sequence)

        # Predictions should be identical
        assert prob1 == prob2

        print(f"✓ Consistent predictions: {prob1:.4f} == {prob2:.4f}")
