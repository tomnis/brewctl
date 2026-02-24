"""
Unit tests for the KalmanFilter class.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewctl.brew_strategy import KalmanFilter


class TestKalmanFilter:
    """Tests for the KalmanFilter class."""

    def test_initial_state(self):
        """Test that KalmanFilter initializes with correct defaults."""
        kf = KalmanFilter()
        assert kf.q == 0.001
        assert kf.r == 0.1
        assert kf.x == 0.0
        assert kf.p == 1.0

    def test_custom_initial_params(self):
        """Test KalmanFilter with custom initial parameters."""
        kf = KalmanFilter(q=0.01, r=0.5, initial_estimate=2.0, initial_error=0.5)
        assert kf.q == 0.01
        assert kf.r == 0.5
        assert kf.x == 2.0
        assert kf.p == 0.5

    def test_first_measurement_sets_estimate(self):
        """Test that the first measurement initializes the estimate."""
        kf = KalmanFilter(initial_error=1e10)  # large error = uninitialized
        kf.is_initialized = False
        result = kf.update(5.0)
        assert result == 5.0
        assert kf.is_initialized is True

    def test_update_smooths_noisy_measurements(self):
        """Test that repeated updates smooth out noisy measurements."""
        kf = KalmanFilter(q=0.001, r=0.1, initial_estimate=10.0, initial_error=1.0)
        
        # Feed a series of noisy measurements around 10.0
        measurements = [10.5, 9.5, 10.2, 9.8, 10.1, 9.9, 10.0]
        results = [kf.update(m) for m in measurements]
        
        # The filtered result should be close to 10.0 and less variable than input
        assert abs(results[-1] - 10.0) < 0.5

    def test_update_converges_to_stable_value(self):
        """Test that filter converges when given constant measurements."""
        kf = KalmanFilter(q=0.001, r=0.1, initial_estimate=0.0, initial_error=1.0)
        
        # Feed constant value
        for _ in range(50):
            result = kf.update(5.0)
        
        assert abs(result - 5.0) < 0.01

    def test_update_with_none_returns_current_estimate(self):
        """Test that None measurement returns current estimate unchanged."""
        kf = KalmanFilter(initial_estimate=3.0)
        result = kf.update(None)
        assert result == 3.0

    def test_reset(self):
        """Test that reset returns filter to initial state."""
        kf = KalmanFilter(initial_estimate=5.0)
        kf.update(10.0)
        kf.update(12.0)
        
        kf.reset()
        
        assert kf.x == 0.0
        assert kf.p == 1.0
        assert kf.is_initialized is False

    def test_high_process_noise_tracks_changes_faster(self):
        """Test that higher process noise makes filter more responsive."""
        kf_low_q = KalmanFilter(q=0.0001, r=0.1, initial_estimate=0.0)
        kf_high_q = KalmanFilter(q=1.0, r=0.1, initial_estimate=0.0)
        
        # Both start at 0, feed measurement of 10
        result_low = kf_low_q.update(10.0)
        result_high = kf_high_q.update(10.0)
        
        # High Q should track the jump faster (closer to 10)
        assert result_high > result_low

    def test_high_measurement_noise_smooths_more(self):
        """Test that higher measurement noise causes more smoothing."""
        kf_low_r = KalmanFilter(q=0.001, r=0.01, initial_estimate=5.0)
        kf_high_r = KalmanFilter(q=0.001, r=10.0, initial_estimate=5.0)
        
        # Feed a noisy measurement
        result_low_r = kf_low_r.update(10.0)
        result_high_r = kf_high_r.update(10.0)
        
        # High R should stay closer to prior estimate (5.0)
        assert abs(result_high_r - 5.0) < abs(result_low_r - 5.0)

    def test_kalman_gain_decreases_over_time(self):
        """Test that the estimate error covariance decreases with updates."""
        kf = KalmanFilter(q=0.001, r=0.1, initial_estimate=0.0, initial_error=10.0)
        
        initial_p = kf.p
        for _ in range(10):
            kf.update(5.0)
        
        assert kf.p < initial_p
