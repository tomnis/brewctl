"""Tests for the api service's Prometheus metrics.

Anything that exercises brew_step_task drives the coroutine directly rather than
going through TestClient, which does not reliably schedule background tasks --
same reasoning as test_brew_pause.py and test_strategy_switch.py.

Values are read back with REGISTRY.get_sample_value and compared as deltas: the
registry is rebuilt per test by an autouse fixture, but delta assertions stay
honest even if that ever stops being true.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from brewctl.core import metrics
from brewctl.core.model import (
    Brew,
    BrewState,
    BrewStrategyType,
    SwitchStrategyRequest,
    ValveCommand,
)
from brewctl.api.brew_strategy import DefaultBrewStrategy


BASE_PARAMS = {
    "target_flow_rate": 0.05,
    "scale_interval": 0.5,
    "valve_interval": 10,
    "target_weight": 500,
    "vessel_weight": 100,
    "epsilon": 0.008,
}


@pytest.fixture
def server(client):
    """The patched server module. Depends on client so HttpScale/HttpValve are mocked."""
    import brewctl.api.server as server_module

    return server_module


def sample(name, labels=None):
    return metrics.REGISTRY.get_sample_value(name, labels or {})


def _brew(status=BrewState.BREWING, brew_id="test-brew"):
    return Brew(
        id=brew_id,
        status=status,
        time_started=datetime.now(timezone.utc),
        vessel_weight=100.0,
        target_weight=500.0,
        strategy=BrewStrategyType.DEFAULT,
    )


class _FixedStrategy:
    """Returns one command, then keeps the loop from spinning."""

    target_flow_rate = 0.05
    valve_interval = 10

    def __init__(self, command):
        self.command = command
        self.calls = 0

    def step(self, flow_rate, weight):
        self.calls += 1
        return (self.command, 0.01)


def _run_one_step(server, monkeypatch, strategy, brew=None, flow_rate=0.02):
    """Drive brew_step_task for exactly one iteration."""
    brew = brew or _brew()
    monkeypatch.setattr(server, "cur_brew", brew)
    monkeypatch.setattr(server, "cur_strategy", strategy)
    monkeypatch.setattr(server, "cur_base_params", dict(BASE_PARAMS))
    monkeypatch.setattr(server.weight_buffer, "is_ready", lambda *a, **k: True)
    monkeypatch.setattr(server.weight_buffer, "is_stale", lambda *a, **k: False)
    monkeypatch.setattr(server.weight_buffer, "get_flow_rate", lambda: flow_rate)
    monkeypatch.setattr(server.weight_buffer, "get_current_weight", lambda: 250.0)

    async def one_iteration():
        async def stop_after_first_sleep(seconds):
            # End the loop by clearing the brew, which is exactly how stop/kill
            # terminates it.
            server.cur_brew = None
            return False

        monkeypatch.setattr(server, "sleep_with_heartbeat", stop_after_first_sleep)
        await server.brew_step_task(brew.id)

    asyncio.run(one_iteration())
    return brew


class TestEndpoint:
    def test_returns_prometheus_text(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert "version=" in resp.headers["content-type"]

    def test_exposes_the_api_metric_names(self, client):
        body = client.get("/metrics").text
        for name in (
            "brewctl_flow_rate_grams_per_second",
            "brewctl_flow_rate_error",
            "brewctl_valve_position",
            "brewctl_valve_commands_total",
            "brewctl_brews_total",
            "brewctl_scale_data_age_seconds",
            "brewctl_influx_write_failures_total",
        ):
            assert name in body

    def test_scale_data_age_is_read_at_scrape_time(self, server, monkeypatch):
        """Not written from the collection loop, where it would always be ~0."""
        stale = datetime.now(timezone.utc) - timedelta(seconds=7)
        server.weight_buffer.clear()
        server.weight_buffer.add_reading(100.0, timestamp=stale)

        age = sample("brewctl_scale_data_age_seconds")
        assert age == pytest.approx(7, abs=1)

    def test_valve_position_never_makes_a_blocking_call(self, server, monkeypatch):
        """cached_position, not get_position -- the fallback is synchronous HTTP."""
        valve = MagicMock()
        valve.cached_position.return_value = 42
        monkeypatch.setattr(server, "valve", valve)

        assert sample("brewctl_valve_position") == 42
        valve.get_position.assert_not_called()


class TestBrewLoop:
    def test_records_flow_rate_and_error(self, server, monkeypatch):
        _run_one_step(
            server, monkeypatch, _FixedStrategy(ValveCommand.FORWARD), flow_rate=0.02
        )

        assert sample(
            "brewctl_flow_rate_grams_per_second", {"brew_id": "test-brew"}
        ) == pytest.approx(0.02)
        assert sample("brewctl_flow_rate_error") == pytest.approx(0.05 - 0.02)

    def test_counts_every_command_including_noop(self, server, monkeypatch):
        _run_one_step(server, monkeypatch, _FixedStrategy(ValveCommand.NOOP))
        assert sample("brewctl_valve_commands_total", {"command": "NOOP"}) == 1

    def test_counts_completed_on_the_stop_command(self, server, monkeypatch):
        _run_one_step(server, monkeypatch, _FixedStrategy(ValveCommand.STOP))
        assert sample("brewctl_brews_total", {"outcome": "completed"}) == 1

    def test_discarded_command_is_not_counted(self, server, monkeypatch):
        """A brew that ends mid-step has its command dropped; the counter must agree."""
        brew = _brew()

        class EndsTheBrew(_FixedStrategy):
            def step(self, flow_rate, weight):
                server.cur_brew = None
                return (ValveCommand.FORWARD, 0.01)

        monkeypatch.setattr(server, "cur_brew", brew)
        monkeypatch.setattr(server, "cur_strategy", EndsTheBrew(ValveCommand.FORWARD))
        monkeypatch.setattr(server, "cur_base_params", dict(BASE_PARAMS))
        monkeypatch.setattr(server.weight_buffer, "is_ready", lambda *a, **k: True)
        monkeypatch.setattr(server.weight_buffer, "is_stale", lambda *a, **k: False)
        monkeypatch.setattr(server.weight_buffer, "get_flow_rate", lambda: 0.02)
        monkeypatch.setattr(server.weight_buffer, "get_current_weight", lambda: 250.0)

        asyncio.run(server.brew_step_task(brew.id))

        assert sample("brewctl_valve_commands_total", {"command": "FORWARD"}) is None

    def test_error_is_counted_once_per_transition(self, server, monkeypatch):
        """The loop keeps running while ERROR; only the way in counts."""
        brew = _brew()
        calls = {"n": 0}

        class Explodes(_FixedStrategy):
            def step(self, flow_rate, weight):
                calls["n"] += 1
                raise RuntimeError("boom")

        monkeypatch.setattr(server, "cur_brew", brew)
        monkeypatch.setattr(server, "cur_strategy", Explodes(ValveCommand.NOOP))
        monkeypatch.setattr(server, "cur_base_params", dict(BASE_PARAMS))

        async def sleep_until_third_failure(seconds):
            if calls["n"] >= 3:
                server.cur_brew = None
            return False

        monkeypatch.setattr(server, "sleep_with_heartbeat", sleep_until_third_failure)
        asyncio.run(server.brew_step_task(brew.id))

        assert calls["n"] >= 3
        assert sample("brewctl_brews_total", {"outcome": "error"}) == 1


class TestOutcomeEndpoints:
    def test_kill_counts_killed(self, server, monkeypatch):
        monkeypatch.setattr(server, "cur_brew", _brew())
        monkeypatch.setattr(server, "scale", MagicMock())
        monkeypatch.setattr(server, "valve", MagicMock())

        asyncio.run(server.kill_brew())

        assert sample("brewctl_brews_total", {"outcome": "killed"}) == 1

    def test_stop_counts_stopped(self, server, monkeypatch):
        monkeypatch.setattr(server, "cur_brew", _brew())
        monkeypatch.setattr(server, "scale", MagicMock())
        monkeypatch.setattr(server, "valve", MagicMock())
        monkeypatch.setattr(server.time, "sleep", lambda s: None)

        asyncio.run(server.stop_brew("test-brew"))

        assert sample("brewctl_brews_total", {"outcome": "stopped"}) == 1

    def test_stopping_a_completed_brew_does_not_double_count(self, server, monkeypatch):
        """The normal UI flow: the loop already counted it as completed."""
        monkeypatch.setattr(server, "cur_brew", _brew(status=BrewState.COMPLETED))
        monkeypatch.setattr(server, "scale", MagicMock())
        monkeypatch.setattr(server, "valve", MagicMock())
        monkeypatch.setattr(server.time, "sleep", lambda s: None)

        asyncio.run(server.stop_brew("test-brew"))

        assert sample("brewctl_brews_total", {"outcome": "stopped"}) is None


class TestTeardown:
    def test_clear_strategy_state_drops_the_brew_id_series(self, server):
        metrics.flow_rate.labels(brew_id="test-brew").set(0.02)
        metrics.flow_rate_error.set(0.03)

        server._clear_strategy_state()

        assert (
            sample("brewctl_flow_rate_grams_per_second", {"brew_id": "test-brew"})
            is None
        )
        assert sample("brewctl_flow_rate_error") == 0

    def test_valve_position_survives_teardown(self, server, monkeypatch):
        """The physical valve keeps its position after a brew ends."""
        valve = MagicMock()
        valve.cached_position.return_value = 12
        monkeypatch.setattr(server, "valve", valve)

        server._clear_strategy_state()

        assert sample("brewctl_valve_position") == 12


class TestStrategySwitch:
    def test_switch_zeroes_the_stale_error(self, server, monkeypatch):
        monkeypatch.setattr(server, "cur_brew", _brew())
        monkeypatch.setattr(server, "cur_base_params", dict(BASE_PARAMS))
        monkeypatch.setattr(
            server, "cur_strategy", DefaultBrewStrategy.from_params({}, BASE_PARAMS)
        )
        monkeypatch.setattr(server, "_last_strategy_switch_at", None)
        metrics.flow_rate_error.set(0.04)

        asyncio.run(
            server.switch_strategy(
                SwitchStrategyRequest(strategy=BrewStrategyType.PID, strategy_params={})
            )
        )

        assert sample("brewctl_flow_rate_error") == 0


class TestInfluxWriteFailures:
    """Instantiates InfluxDBTimeSeries directly.

    tests/api/conftest.py replaces brewctl.api.server.time_series with a MagicMock,
    so patching through the server module would exercise nothing at all.
    """

    def _time_series(self, write_api):
        from brewctl.api.time_series import InfluxDBTimeSeries

        with patch("brewctl.api.time_series.InfluxDBClient") as client_cls:
            client_cls.return_value.write_api.return_value = write_api
            return InfluxDBTimeSeries(
                url="http://influx.test", token="t", org="o", bucket="b"
            )

    def test_counts_and_reraises(self):
        write_api = MagicMock()
        write_api.write.side_effect = RuntimeError("influx down")
        ts = self._time_series(write_api)

        with pytest.raises(RuntimeError):
            ts.write_scale_data(100.0, 75, "test-brew")

        assert sample("brewctl_influx_write_failures_total") == 1

    def test_successful_write_does_not_count(self):
        ts = self._time_series(MagicMock())

        ts.write_scale_data(100.0, 75, "test-brew")

        assert sample("brewctl_influx_write_failures_total") == 0
