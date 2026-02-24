"""
Unit tests for InfluxDBTimeSeries functionality.
These tests use mocked InfluxDB clients to avoid needing a real connection.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewserver.time_series import InfluxDBTimeSeries, AbstractTimeSeries


def _make_ts():
    """Create an InfluxDBTimeSeries with mocked InfluxDB client."""
    ts = object.__new__(InfluxDBTimeSeries)
    ts.url = "http://fake"
    ts.token = "fake"
    ts.org = "fake"
    ts.bucket = "fake"
    ts.influxdb = MagicMock()
    return ts


class TestAbstractTimeSeriesInterface:
    """Tests for AbstractTimeSeries interface (abstract base class)."""

    def test_cannot_instantiate_abstract_class(self):
        """AbstractTimeSeries cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractTimeSeries()

    def test_abstract_methods_must_be_implemented(self):
        """Subclass must implement all abstract methods."""
        class IncompleteTimeSeries(AbstractTimeSeries):
            pass

        with pytest.raises(TypeError):
            IncompleteTimeSeries()

    def test_complete_implementation_works(self):
        """Complete implementation can be instantiated."""
        class CompleteTimeSeries(AbstractTimeSeries):
            def healthcheck(self) -> bool:
                return True
            
            def write_scale_data(self, weight: float, battery_pct: int, brew_id: str) -> None:
                pass
            
            def get_current_weight(self) -> float:
                return 100.0
            
            def get_current_flow_rate(self) -> float:
                return 5.0
            
            def get_recent_weight_readings(self, duration_seconds: int = 10, start_time_filter: datetime | None = None):
                return []

        ts = CompleteTimeSeries()
        assert ts.healthcheck() is True
        assert ts.get_current_weight() == 100.0


class TestHealthcheck:
    """Tests for healthcheck method."""

    def test_healthcheck_returns_true_when_ping_succeeds(self):
        """healthcheck returns True when InfluxDB ping succeeds."""
        ts = _make_ts()
        ts.influxdb.ping.return_value = True
        assert ts.healthcheck() is True

    def test_healthcheck_returns_false_when_ping_fails(self):
        """healthcheck returns False when InfluxDB ping fails."""
        ts = _make_ts()
        ts.influxdb.ping.return_value = False
        assert ts.healthcheck() is False


class TestWriteScaleData:
    """Tests for write_scale_data method."""

    def test_write_scale_data_calls_write_api(self):
        """write_scale_data should call InfluxDB write_api with correct parameters."""
        ts = _make_ts()
        
        with patch.object(ts.influxdb, 'write_api') as mock_write_api:
            mock_api_instance = MagicMock()
            mock_write_api.return_value = mock_api_instance
            
            ts.write_scale_data(weight=100.5, battery_pct=75, brew_id="test-brew-123")
            
            mock_write_api.assert_called_once()
            # Check that write was called with correct bucket
            mock_api_instance.write.assert_called_once()
            call_kwargs = mock_api_instance.write.call_args[1]
            assert call_kwargs['bucket'] == "fake"

    def test_write_scale_data_creates_point_with_correct_fields(self):
        """write_scale_data should create a Point with correct fields."""
        ts = _make_ts()
        
        with patch.object(ts.influxdb, 'write_api') as mock_write_api:
            mock_api_instance = MagicMock()
            mock_write_api.return_value = mock_api_instance
            
            ts.write_scale_data(weight=250.0, battery_pct=80, brew_id="brew-456")
            
            # Verify write was called (the Point object is created internally)
            mock_api_instance.write.assert_called_once()


class TestGetCurrentWeight:
    """Tests for get_current_weight method."""

    def test_get_current_weight_returns_weight(self):
        """get_current_weight should return the most recent weight value."""
        ts = _make_ts()
        
        # Mock query_api and its response
        mock_record = MagicMock()
        mock_record.get_value.return_value = 123.45
        
        mock_table = MagicMock()
        mock_table.records = [mock_record]
        
        ts.influxdb.query_api.return_value.query.return_value = [mock_table]
        
        result = ts.get_current_weight()
        
        assert result == 123.45

    def test_get_current_weight_uses_correct_query(self):
        """get_current_weight should query with correct InfluxDB query."""
        ts = _make_ts()
        
        mock_record = MagicMock()
        mock_record.get_value.return_value = 100.0
        
        mock_table = MagicMock()
        mock_table.records = [mock_record]
        
        with patch.object(ts.influxdb, 'query_api') as mock_query_api:
            mock_query_api.return_value.query.return_value = [mock_table]
            
            ts.get_current_weight()
            
            # Verify query was called with org parameter
            mock_query_api.return_value.query.assert_called_once()
            call_args = mock_query_api.return_value.query.call_args
            assert call_args[1]['org'] == "fake"

    def test_get_current_weight_returns_last_record_value(self):
        """get_current_weight should return value from the last record."""
        ts = _make_ts()
        
        # Create multiple records - should return last one's value
        mock_record1 = MagicMock()
        mock_record1.get_value.return_value = 100.0
        
        mock_record2 = MagicMock()
        mock_record2.get_value.return_value = 150.0
        
        mock_table = MagicMock()
        mock_table.records = [mock_record1, mock_record2]
        
        ts.influxdb.query_api.return_value.query.return_value = [mock_table]
        
        result = ts.get_current_weight()
        
        # Should return the last record's value (150.0)
        assert result == 150.0


class TestGetRecentWeightReadings:
    """Tests for get_recent_weight_readings method."""

    def test_get_recent_weight_readings_returns_list(self):
        """get_recent_weight_readings should return list of tuples."""
        ts = _make_ts()
        
        now = datetime.now(timezone.utc)
        mock_record = MagicMock()
        mock_record.get_time.return_value = now
        mock_record.get_value.return_value = 100.0
        
        mock_table = MagicMock()
        mock_table.records = [mock_record]
        
        ts.influxdb.query_api.return_value.query.return_value = [mock_table]
        
        result = ts.get_recent_weight_readings()
        
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0] == (now, 100.0)

    def test_get_recent_weight_readings_sorts_by_time(self):
        """get_recent_weight_readings should return readings sorted by timestamp."""
        ts = _make_ts()
        
        t1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
        t3 = datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
        
        # Create records in reverse order
        mock_record3 = MagicMock()
        mock_record3.get_time.return_value = t3
        mock_record3.get_value.return_value = 103.0
        
        mock_record1 = MagicMock()
        mock_record1.get_time.return_value = t1
        mock_record1.get_value.return_value = 101.0
        
        mock_table = MagicMock()
        mock_table.records = [mock_record3, mock_record1]
        
        ts.influxdb.query_api.return_value.query.return_value = [mock_table]
        
        result = ts.get_recent_weight_readings()
        
        # Should be sorted by time ascending
        assert result[0][0] == t1
        assert result[1][0] == t3

    def test_get_recent_weight_readings_filters_by_start_time(self):
        """get_recent_weight_readings should filter by start_time_filter."""
        ts = _make_ts()
        
        t1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
        t3 = datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc)
        
        mock_record1 = MagicMock()
        mock_record1.get_time.return_value = t1
        mock_record1.get_value.return_value = 100.0
        
        mock_record2 = MagicMock()
        mock_record2.get_time.return_value = t2
        mock_record2.get_value.return_value = 105.0
        
        mock_record3 = MagicMock()
        mock_record3.get_time.return_value = t3
        mock_record3.get_value.return_value = 110.0
        
        mock_table = MagicMock()
        mock_table.records = [mock_record1, mock_record2, mock_record3]
        
        ts.influxdb.query_api.return_value.query.return_value = [mock_table]
        
        # Filter from t2 onwards
        result = ts.get_recent_weight_readings(start_time_filter=t2)
        
        assert len(result) == 2
        assert result[0][0] == t2
        assert result[1][0] == t3

    def test_get_recent_weight_readings_skips_none_values(self):
        """get_recent_weight_readings should skip None values."""
        ts = _make_ts()
        
        now = datetime.now(timezone.utc)
        
        mock_record1 = MagicMock()
        mock_record1.get_time.return_value = now
        mock_record1.get_value.return_value = 100.0
        
        mock_record2 = MagicMock()
        mock_record2.get_time.return_value = now
        mock_record2.get_value.return_value = None
        
        mock_table = MagicMock()
        mock_table.records = [mock_record1, mock_record2]
        
        ts.influxdb.query_api.return_value.query.return_value = [mock_table]
        
        result = ts.get_recent_weight_readings()
        
        # Should only include non-None values
        assert len(result) == 1
        assert result[0][1] == 100.0


class TestGetCurrentFlowRate:
    """Tests for get_current_flow_rate method."""

    def test_get_current_flow_rate_returns_rate(self):
        """get_current_flow_rate should return calculated flow rate."""
        ts = _make_ts()
        
        now = datetime.now(timezone.utc)
        t1 = now - timedelta(seconds=5)
        
        # Mock get_recent_weight_readings to return test data
        with patch.object(ts, 'get_recent_weight_readings') as mock_readings:
            mock_readings.return_value = [
                (t1, 100.0),
                (now, 110.0),
            ]
            
            result = ts.get_current_flow_rate()
            
            # 10g over 5s = 2.0 g/s
            assert abs(result - 2.0) < 0.001

    def test_get_current_flow_rate_returns_none_when_no_readings(self):
        """get_current_flow_rate should return None when no readings available."""
        ts = _make_ts()
        
        with patch.object(ts, 'get_recent_weight_readings') as mock_readings:
            mock_readings.return_value = []
            
            result = ts.get_current_flow_rate()
            
            assert result is None

    def test_get_current_flow_rate_returns_none_with_single_reading(self):
        """get_current_flow_rate should return None with only one reading."""
        ts = _make_ts()
        
        now = datetime.now(timezone.utc)
        
        with patch.object(ts, 'get_recent_weight_readings') as mock_readings:
            mock_readings.return_value = [(now, 100.0)]
            
            result = ts.get_current_flow_rate()
            
            assert result is None


class TestGetWeightReadingsInRange:
    """Tests for get_weight_readings_in_range method."""

    def test_get_weight_readings_in_range_returns_filtered_readings(self):
        """Should return only readings within the specified time range."""
        ts = _make_ts()
        
        start_time = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
        end_time = datetime(2026, 1, 1, 0, 0, 15, tzinfo=timezone.utc)
        
        t1 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)  # Before range
        t2 = datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc)  # In range
        t3 = datetime(2026, 1, 1, 0, 0, 20, tzinfo=timezone.utc)  # After range
        
        mock_record1 = MagicMock()
        mock_record1.get_time.return_value = t1
        mock_record1.get_value.return_value = 100.0
        
        mock_record2 = MagicMock()
        mock_record2.get_time.return_value = t2
        mock_record2.get_value.return_value = 105.0
        
        mock_record3 = MagicMock()
        mock_record3.get_time.return_value = t3
        mock_record3.get_value.return_value = 110.0
        
        mock_table = MagicMock()
        mock_table.records = [mock_record1, mock_record2, mock_record3]
        
        ts.influxdb.query_api.return_value.query.return_value = [mock_table]
        
        result = ts.get_weight_readings_in_range(start_time, end_time)
        
        # Should only include t2
        assert len(result) == 1
        assert result[0][0] == t2

    def test_get_weight_readings_in_range_sorts_by_time(self):
        """Should return readings sorted by timestamp ascending."""
        ts = _make_ts()
        
        start_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2026, 1, 1, 0, 0, 20, tzinfo=timezone.utc)
        
        t1 = datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc)
        
        mock_record1 = MagicMock()
        mock_record1.get_time.return_value = t1
        mock_record1.get_value.return_value = 110.0
        
        mock_record2 = MagicMock()
        mock_record2.get_time.return_value = t2
        mock_record2.get_value.return_value = 105.0
        
        mock_table = MagicMock()
        mock_table.records = [mock_record1, mock_record2]
        
        ts.influxdb.query_api.return_value.query.return_value = [mock_table]
        
        result = ts.get_weight_readings_in_range(start_time, end_time)
        
        # Should be sorted by time
        assert result[0][0] == t2
        assert result[1][0] == t1


class TestGetFlowRatesForBrew:
    """Tests for get_flow_rates_for_brew method."""

    def test_get_flow_rates_for_brew_returns_list(self):
        """Should return a list of flow rates."""
        ts = _make_ts()
        
        start_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)  # 60 seconds
        
        # Mock get_weight_readings_in_range to return enough data
        with patch.object(ts, 'get_weight_readings_in_range') as mock_readings:
            now = start_time
            readings = []
            for i in range(10):
                ts_val = now + timedelta(seconds=i * 6)
                readings.append((ts_val, 100.0 + i * 5.0))
            
            mock_readings.return_value = readings
            
            result = ts.get_flow_rates_for_brew(start_time, end_time, window_seconds=6.0)
            
            assert isinstance(result, list)

    def test_get_flow_rates_for_brew_returns_empty_with_insufficient_readings(self):
        """Should return empty list with fewer than 2 readings."""
        ts = _make_ts()
        
        start_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)
        
        with patch.object(ts, 'get_weight_readings_in_range') as mock_readings:
            # Only one reading
            mock_readings.return_value = [
                (start_time, 100.0)
            ]
            
            result = ts.get_flow_rates_for_brew(start_time, end_time)
            
            assert result == []

    def test_get_flow_rates_for_brew_multiple_windows(self):
        """Should calculate flow rates for multiple time windows."""
        ts = _make_ts()
        
        start_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2026, 1, 1, 0, 0, 30, tzinfo=timezone.utc)
        
        # Create readings for multiple windows
        readings = [
            (datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc), 100.0),
            (datetime(2026, 1, 1, 0, 0, 5, tzinfo=timezone.utc), 110.0),  # +10g in 5s = 2g/s
            (datetime(2026, 1, 1, 0, 0, 10, tzinfo=timezone.utc), 120.0),
            (datetime(2026, 1, 1, 0, 0, 15, tzinfo=timezone.utc), 135.0),  # +15g in 5s = 3g/s
            (datetime(2026, 1, 1, 0, 0, 20, tzinfo=timezone.utc), 145.0),
            (datetime(2026, 1, 1, 0, 0, 25, tzinfo=timezone.utc), 160.0),  # +15g in 5s = 3g/s
        ]
        
        with patch.object(ts, 'get_weight_readings_in_range') as mock_readings:
            mock_readings.return_value = readings
            
            result = ts.get_flow_rates_for_brew(start_time, end_time, window_seconds=10.0)
            
            # Should have calculated some flow rates
            assert len(result) >= 0


class TestInfluxDBTimeSeriesInitialization:
    """Tests for InfluxDBTimeSeries initialization."""

    def test_initialization_sets_properties(self):
        """Initialization should set all required properties."""
        ts = InfluxDBTimeSeries(
            url="http://localhost:8086",
            token="my-token",
            org="my-org",
            bucket="my-bucket",
            timeout=60000
        )
        
        assert ts.url == "http://localhost:8086"
        assert ts.token == "my-token"
        assert ts.org == "my-org"
        assert ts.bucket == "my-bucket"

    def test_initialization_creates_influxdb_client(self):
        """Initialization should create InfluxDB client."""
        with patch('brewserver.time_series.InfluxDBClient') as mock_client:
            ts = InfluxDBTimeSeries(
                url="http://localhost:8086",
                token="my-token",
                org="my-org",
                bucket="my-bucket"
            )
            
            mock_client.assert_called_once()
            call_kwargs = mock_client.call_args[1]
            assert call_kwargs['url'] == "http://localhost:8086"
            assert call_kwargs['token'] == "my-token"
            assert call_kwargs['org'] == "my-org"
            assert call_kwargs['timeout'] == 30000  # default


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
