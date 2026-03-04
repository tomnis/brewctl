"""
Unit tests for WeightBuffer functionality.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from brewctl.api.weight_buffer import WeightBuffer


class TestWeightBuffer:
    def test_empty_buffer_returns_none(self):
        buf = WeightBuffer(max_size=10)
        assert buf.get_flow_rate() is None
        assert buf.get_current_weight() is None
        assert buf.is_ready() is False

    def test_single_reading_returns_none_for_flow_rate(self):
        buf = WeightBuffer(max_size=10)
        buf.add_reading(100.0)
        assert buf.get_flow_rate() is None
        assert buf.get_current_weight() == 100.0
        assert buf.is_ready() is False

    def test_two_readings_calculates_flow_rate(self):
        buf = WeightBuffer(max_size=10)
        t1 = datetime.now(timezone.utc)
        buf.add_reading(100.0, t1)
        buf.add_reading(110.0, t1 + timedelta(seconds=1))

        assert buf.is_ready()
        assert buf.get_current_weight() == 110.0
        assert buf.get_flow_rate() == pytest.approx(10.0)

    def test_flow_rate_with_larger_time_diff(self):
        buf = WeightBuffer(max_size=10)
        t1 = datetime.now(timezone.utc)
        buf.add_reading(100.0, t1)
        buf.add_reading(105.0, t1 + timedelta(seconds=10))

        assert buf.get_flow_rate() == pytest.approx(0.5)

    def test_max_size_enforced(self):
        buf = WeightBuffer(max_size=3)
        for i in range(5):
            buf.add_reading(float(i))

        assert buf.size == 3
        assert buf.max_size == 3

    def test_is_stale_when_empty(self):
        buf = WeightBuffer(max_size=10)
        assert buf.is_stale() is True

    def test_is_stale_with_fresh_data(self):
        buf = WeightBuffer(max_size=10)
        buf.add_reading(100.0)
        assert buf.is_stale(max_age_seconds=2.0) is False

    def test_is_stale_with_old_data(self):
        buf = WeightBuffer(max_size=10)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=5)
        buf.add_reading(100.0, old_time)
        assert buf.is_stale(max_age_seconds=2.0) is True

    def test_clear_resets_buffer(self):
        buf = WeightBuffer(max_size=10)
        buf.add_reading(100.0)
        buf.add_reading(110.0)

        buf.clear()

        assert buf.size == 0
        assert buf.get_flow_rate() is None
        assert buf.is_ready() is False

    def test_get_readings_returns_copy(self):
        buf = WeightBuffer(max_size=10)
        buf.add_reading(100.0)
        buf.add_reading(110.0)

        readings = buf.get_readings()

        assert len(readings) == 2
        assert readings[0][1] == 100.0
        assert readings[1][1] == 110.0

    def test_flow_rate_zero_when_no_weight_change(self):
        buf = WeightBuffer(max_size=10)
        t1 = datetime.now(timezone.utc)
        buf.add_reading(100.0, t1)
        buf.add_reading(100.0, t1 + timedelta(seconds=1))

        assert buf.get_flow_rate() == pytest.approx(0.0)

    def test_negative_flow_rate(self):
        buf = WeightBuffer(max_size=10)
        t1 = datetime.now(timezone.utc)
        buf.add_reading(110.0, t1)
        buf.add_reading(100.0, t1 + timedelta(seconds=1))

        assert buf.get_flow_rate() == pytest.approx(-10.0)

    def test_flow_rate_with_zero_time_diff(self):
        buf = WeightBuffer(max_size=10)
        t1 = datetime.now(timezone.utc)
        buf.add_reading(100.0, t1)
        buf.add_reading(110.0, t1)

        assert buf.get_flow_rate() is None

    def test_is_ready_with_min_readings(self):
        buf = WeightBuffer(max_size=10)
        buf.add_reading(100.0)

        assert buf.is_ready(min_readings=1) is True
        assert buf.is_ready(min_readings=2) is False

        buf.add_reading(110.0)

        assert buf.is_ready(min_readings=2) is True

    def test_timestamp_none_uses_current_time(self):
        buf = WeightBuffer(max_size=10)
        before = datetime.now(timezone.utc)
        buf.add_reading(100.0)
        after = datetime.now(timezone.utc)

        timestamp = buf.get_readings()[0][0]
        assert before <= timestamp <= after

    def test_multiple_readings_flow_rate_uses_endpoints(self):
        buf = WeightBuffer(max_size=10)
        t1 = datetime.now(timezone.utc)
        buf.add_reading(100.0, t1)
        buf.add_reading(105.0, t1 + timedelta(seconds=2))
        buf.add_reading(110.0, t1 + timedelta(seconds=4))
        buf.add_reading(115.0, t1 + timedelta(seconds=6))

        assert buf.get_flow_rate() == pytest.approx(2.5)
