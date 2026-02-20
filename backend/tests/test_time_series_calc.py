"""
Unit tests for InfluxDBTimeSeries.calculate_flow_rate_from_derivatives.
This is a pure function that can be tested without an actual InfluxDB connection.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewserver.time_series import InfluxDBTimeSeries


def _make_ts():
    """Create an InfluxDBTimeSeries with mocked InfluxDB client."""
    ts = object.__new__(InfluxDBTimeSeries)
    ts.url = "http://fake"
    ts.token = "fake"
    ts.org = "fake"
    ts.bucket = "fake"
    ts.influxdb = MagicMock()
    return ts


class TestCalculateFlowRateFromDerivatives:
    """Tests for calculate_flow_rate_from_derivatives."""

    def test_returns_none_with_empty_readings(self):
        ts = _make_ts()
        assert ts.calculate_flow_rate_from_derivatives([]) is None

    def test_returns_none_with_single_reading(self):
        ts = _make_ts()
        now = datetime.now(timezone.utc)
        assert ts.calculate_flow_rate_from_derivatives([(now, 100.0)]) is None

    def test_positive_flow_rate(self):
        ts = _make_ts()
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=10)
        # 10g over 10s = 1.0 g/s
        result = ts.calculate_flow_rate_from_derivatives([(t0, 100.0), (t1, 110.0)])
        assert abs(result - 1.0) < 0.001

    def test_zero_flow_rate(self):
        ts = _make_ts()
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=10)
        result = ts.calculate_flow_rate_from_derivatives([(t0, 100.0), (t1, 100.0)])
        assert result == 0.0

    def test_negative_flow_rate(self):
        """Negative flow rate means weight decreased (e.g., evaporation)."""
        ts = _make_ts()
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=10)
        result = ts.calculate_flow_rate_from_derivatives([(t0, 110.0), (t1, 100.0)])
        assert abs(result - (-1.0)) < 0.001

    def test_uses_first_and_last_readings_only(self):
        """Should use first and last readings, ignoring intermediate ones."""
        ts = _make_ts()
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=5)
        t2 = t0 + timedelta(seconds=10)
        # First=100, middle=999 (ignored), last=120 => 20g/10s = 2.0 g/s
        result = ts.calculate_flow_rate_from_derivatives([
            (t0, 100.0), (t1, 999.0), (t2, 120.0)
        ])
        assert abs(result - 2.0) < 0.001

    def test_returns_none_when_time_diff_zero(self):
        """Should return None when timestamps are identical."""
        ts = _make_ts()
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = ts.calculate_flow_rate_from_derivatives([(t0, 100.0), (t0, 110.0)])
        assert result is None

    def test_small_time_interval(self):
        """Test with sub-second time interval."""
        ts = _make_ts()
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(milliseconds=500)
        # 5g over 0.5s = 10.0 g/s
        result = ts.calculate_flow_rate_from_derivatives([(t0, 100.0), (t1, 105.0)])
        assert abs(result - 10.0) < 0.001

    def test_large_time_interval(self):
        """Test with large time interval."""
        ts = _make_ts()
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(hours=1)
        # 360g over 3600s = 0.1 g/s
        result = ts.calculate_flow_rate_from_derivatives([(t0, 0.0), (t1, 360.0)])
        assert abs(result - 0.1) < 0.001
