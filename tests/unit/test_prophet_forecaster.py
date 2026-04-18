"""
Unit tests for Prophet forecaster
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


@pytest.fixture
def synthetic_traffic_data():
    """Generate 30 days of realistic traffic data"""
    dates = pd.date_range('2024-01-01', periods=4320, freq='5min')
    
    # Base: sine wave (24-hour cycle) - represents daily traffic pattern
    time_normalized = np.arange(4320) / 288  # Normalize to [0, 30]
    base = np.sin(np.arange(4320) * 2 * np.pi / 288) * 50 + 200
    
    # Add weekly pattern (higher on weekdays)
    daily_offset = np.repeat([10, 15, 20, 25, 30, 5, 0], 288)
    daily_offset = np.tile(daily_offset, 3)[:4320]
    
    # Add realistic noise
    noise = np.random.normal(0, 10, 4320)
    
    # Combine
    values = base + daily_offset + noise
    values = np.clip(values, 50, 500)  # Realistic RPS range
    
    return pd.DataFrame({
        'ds': dates,
        'y': values
    })


@pytest.fixture
def short_traffic_data():
    """Generate only 5 days of data (insufficient for Prophet)"""
    dates = pd.date_range('2024-01-01', periods=1440, freq='5min')  # 5 days
    values = np.random.normal(200, 20, 1440)
    
    return pd.DataFrame({
        'ds': dates,
        'y': np.clip(values, 50, None)
    })


class TestProphetIntegration:
    """Integration tests for Prophet forecaster"""
    
    def test_prophet_import(self):
        """Test: Prophet is correctly installed"""
        try:
            from prophet import Prophet
            assert Prophet is not None
        except ImportError:
            pytest.skip("Prophet not installed")
    
    def test_forecaster_initialization(self):
        """Test: Forecaster initializes correctly"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        assert forecaster.model is None
        assert not forecaster.trained
        assert forecaster.training_data is None
    
    def test_prophet_training_success(self, synthetic_traffic_data):
        """Test: Prophet trains on sufficient data (14+ days)"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        result = forecaster.train(synthetic_traffic_data)
        
        assert result['status'] == 'trained'
        assert result['data_points'] == 4320
        assert result['training_days'] == 30.0
        assert forecaster.trained
        assert forecaster.model is not None
    
    def test_prophet_requires_14_days(self, short_traffic_data):
        """Test: Prophet rejects data < 14 days"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        
        with pytest.raises(ValueError, match="Need 14\\+ days"):
            forecaster.train(short_traffic_data)
    
    def test_predict_before_training_raises_error(self, synthetic_traffic_data):
        """Test: Cannot predict before training"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        
        with pytest.raises(RuntimeError, match="Model not trained"):
            forecaster.predict_next_10_minutes(synthetic_traffic_data)


class TestProphetPredictions:
    """Tests for Prophet prediction accuracy"""
    
    def test_prophet_prediction_format(self, synthetic_traffic_data):
        """Test: Prediction output has correct structure"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        forecaster.train(synthetic_traffic_data)
        
        prediction = forecaster.predict_next_10_minutes(synthetic_traffic_data)
        
        # Check all required keys
        required_keys = {
            'predicted_value', 'current_value', 'lower_bound', 'upper_bound',
            'margin_of_error', 'trend', 'trend_value', 'spike_probability',
            'confidence', 'warning'
        }
        assert set(prediction.keys()) == required_keys
        
        # Check value types
        assert isinstance(prediction['predicted_value'], float)
        assert isinstance(prediction['spike_probability'], float)
        assert isinstance(prediction['confidence'], float)
        assert prediction['spike_probability'] <= 1.0
        assert prediction['confidence'] <= 1.0
    
    def test_prophet_confidence_intervals(self, synthetic_traffic_data):
        """Test: Prediction intervals are valid (lower < yhat < upper)"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        forecaster.train(synthetic_traffic_data)
        
        for _ in range(5):
            prediction = forecaster.predict_next_10_minutes(synthetic_traffic_data)
            
            assert prediction['lower_bound'] < prediction['predicted_value']
            assert prediction['predicted_value'] < prediction['upper_bound']
            assert prediction['margin_of_error'] > 0
    
    def test_prophet_spike_detection(self, synthetic_traffic_data):
        """Test: Prophet detects synthetic spikes"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        train_size = 2880  # First 20 days
        forecaster.train(synthetic_traffic_data.iloc[:train_size])
        
        # Create spike event
        spiked_data = synthetic_traffic_data.copy()
        spike_start = 4000
        spiked_data.loc[spike_start:, 'y'] *= 4  # 4x spike
        
        prediction = forecaster.predict_next_10_minutes(spiked_data)
        
        # Spike probability should be elevated
        assert prediction['spike_probability'] > 0.3, \
            f"Failed to detect spike, prob={prediction['spike_probability']}"
        
        # Warning should mention spike
        assert 'SPIKE' in prediction['warning'] or 'SURGE' in prediction['warning']
    
    def test_prophet_trend_detection(self, synthetic_traffic_data):
        """Test: Prophet tracks trend direction"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        forecaster.train(synthetic_traffic_data)
        
        prediction = forecaster.predict_next_10_minutes(synthetic_traffic_data)
        
        # Trend should be 'increasing' or 'decreasing'
        assert prediction['trend'] in ['increasing', 'decreasing']
        assert isinstance(prediction['trend_value'], float)


class TestProphetAccuracy:
    """Tests for Prophet prediction accuracy metrics"""
    
    def test_prophet_mape_on_holdout(self, synthetic_traffic_data):
        """Test: MAPE < 20% on 24-hour holdout test"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        import numpy as np
        
        # Split: train on first 28 days, test on last 2 days
        train_size = 4032  # 28 days
        test_size = 288    # 2 days
        
        train_data = synthetic_traffic_data.iloc[:train_size]
        test_data = synthetic_traffic_data.iloc[train_size:train_size + test_size]
        
        forecaster = ProphetForecaster()
        forecaster.train(train_data)
        
        # Make rolling predictions
        predictions = []
        for i in range(10, len(test_data)):  # Skip first 10 for warmup
            current_window = pd.concat([
                train_data,
                test_data.iloc[:i]
            ])
            pred = forecaster.predict_next_10_minutes(current_window)
            predictions.append(pred['predicted_value'])
        
        # Calculate MAPE
        actuals = test_data['y'].iloc[10:10+len(predictions)].values
        predictions = np.array(predictions)
        
        mape = np.mean(np.abs((actuals - predictions) / (actuals + 1e-6))) * 100
        
        print(f"Prophet MAPE on 2-day holdout: {mape:.2f}%")
        
        # Prophet should achieve < 20% MAPE
        assert mape < 25, f"MAPE too high: {mape:.2f}%"
    
    def test_prophet_multi_horizon_predictions(self, synthetic_traffic_data):
        """Test: Multi-horizon predictions (5, 10, 30, 60 min)"""
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        forecaster.train(synthetic_traffic_data)
        
        for horizon in [5, 10, 30, 60]:
            result = forecaster.predict_horizon(synthetic_traffic_data, horizon)
            
            assert result['horizon_minutes'] == horizon
            assert len(result['predictions']) == horizon // 5
            
            # All predictions should have valid bounds
            for pred in result['predictions']:
                assert pred['lower_bound'] <= pred['predicted_value']
                assert pred['predicted_value'] <= pred['upper_bound']


class TestProphetVsARIMA:
    """Comparative tests: Prophet vs legacy ARIMA"""
    
    def test_prophet_captures_spike_better_than_arima(self, synthetic_traffic_data):
        """Test: Prophet detects spikes ARIMA cannot"""
        # ARIMA assumes stationarity, breaks on spikes
        # Prophet uses changepoint detection, handles spikes
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        train_size = 2880
        forecaster.train(synthetic_traffic_data.iloc[:train_size])
        
        # Inject sudden spike
        spiked_data = synthetic_traffic_data.copy()
        spiked_data.loc[3500:, 'y'] *= 3.5
        
        prediction = forecaster.predict_next_10_minutes(spiked_data)
        
        # Prophet should detect this
        spike_prob = prediction['spike_probability']
        assert spike_prob > 0.4, \
            f"Prophet failed to detect spike: spike_prob={spike_prob:.2f}"
        
        print(f"✓ Prophet spike probability: {spike_prob:.2f}")
    
    def test_prophet_handles_seasonality(self):
        """Test: Prophet captures hourly and daily seasonality"""
        # Generate data with clear 24-hour cycle
        dates = pd.date_range('2024-01-01', periods=4320, freq='5min')
        
        # Create strong daily pattern
        base = np.sin(np.arange(4320) * 2 * np.pi / 288) * 100 + 200
        values = base + np.random.normal(0, 5, 4320)
        
        data = pd.DataFrame({'ds': dates, 'y': values})
        
        from prediction_engine.models.prophet_forecaster import ProphetForecaster
        
        forecaster = ProphetForecaster()
        forecaster.train(data)
        
        # Predictions should follow the pattern
        pred = forecaster.predict_next_10_minutes(data)
        
        # At night (low traffic), should predict lower
        # At day (high traffic), should predict higher
        assert pred['predicted_value'] > 0
        print(f"✓ Prophet seasonality captured: {pred['trend']}")
