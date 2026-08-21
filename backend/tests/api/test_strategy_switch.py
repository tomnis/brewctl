"""
Tests for live strategy switching (POST /api/brew/strategy).

Like test_brew_pause.py, anything that exercises brew_step_task drives the coroutine
directly rather than going through TestClient, which does not reliably schedule
background tasks. Switches in those tests call the endpoint coroutine on the *same*
loop as the task: strategy_switch_event only wakes a waiter parked on its own loop.
"""
import asyncio
import time
from datetime import datetime, timezone

import pytest

from brewctl.core.model import (
    Brew,
    BrewState,
    BrewStrategyType,
    SwitchStrategyRequest,
    ValveCommand,
)
from brewctl.api.brew_strategy import PIDBrewStrategy, DefaultBrewStrategy


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


def _brew(status=BrewState.BREWING):
    return Brew(
        id="test-brew",
        status=status,
        time_started=datetime.now(timezone.utc),
        vessel_weight=100.0,
        target_weight=500.0,
        strategy=BrewStrategyType.DEFAULT,
    )


def _running(server, monkeypatch, status=BrewState.BREWING, base_params=None, valve=None):
    brew = _brew(status)
    if valve is not None:
        # The client fixture patches HttpValve at *class* level and only bites on the
        # first import of the server module, so the live global has to be set directly.
        monkeypatch.setattr(server, "valve", valve)
    monkeypatch.setattr(server, "cur_brew", brew)
    monkeypatch.setattr(server, "cur_base_params", base_params or dict(BASE_PARAMS))
    monkeypatch.setattr(
        server, "cur_strategy", DefaultBrewStrategy.from_params({}, BASE_PARAMS)
    )
    monkeypatch.setattr(server, "_last_strategy_switch_at", None)
    return brew


def _switch(server, strategy=BrewStrategyType.PID, params=None):
    req = SwitchStrategyRequest(
        strategy=strategy, strategy_params=params if params is not None else {}
    )
    return asyncio.run(server.switch_strategy(req))


class TestGuards:
    def test_409_when_no_brew_running(self, server, monkeypatch):
        monkeypatch.setattr(server, "cur_brew", None)
        with pytest.raises(Exception) as e:
            _switch(server)
        assert e.value.status_code == 409

    def test_409_when_brew_completed(self, server, monkeypatch):
        _running(server, monkeypatch, status=BrewState.COMPLETED)
        with pytest.raises(Exception) as e:
            _switch(server)
        assert e.value.status_code == 409

    def test_400_when_the_strategy_cannot_be_built(self, server, monkeypatch):
        """An unknown type never reaches the handler -- pydantic rejects the body --
        so the 400 path that matters is create_brew_strategy raising."""
        _running(server, monkeypatch)
        monkeypatch.setattr(
            server,
            "create_brew_strategy",
            lambda *a, **k: (_ for _ in ()).throw(ValueError("bad params")),
        )
        with pytest.raises(Exception) as e:
            _switch(server)
        assert e.value.status_code == 400

    def test_429_on_a_second_switch_inside_the_min_interval(self, server, monkeypatch):
        _running(server, monkeypatch)
        _switch(server)
        with pytest.raises(Exception) as e:
            _switch(server, strategy=BrewStrategyType.DEFAULT)
        assert e.value.status_code == 429


class TestSwap:
    def test_swaps_strategy_and_records_the_switch(self, server, monkeypatch):
        brew = _running(server, monkeypatch)
        resp = _switch(server)

        assert resp.status == "strategy_switched"
        assert isinstance(server.cur_strategy, PIDBrewStrategy)
        assert brew.strategy == BrewStrategyType.PID
        assert len(brew.strategy_switches) == 1
        entry = brew.strategy_switches[0]
        assert entry.from_strategy == BrewStrategyType.DEFAULT
        assert entry.to_strategy == BrewStrategyType.PID

    def test_switch_while_paused_does_not_resume(self, server, monkeypatch):
        brew = _running(server, monkeypatch, status=BrewState.PAUSED)
        _switch(server)
        assert brew.status == BrewState.PAUSED
        assert isinstance(server.cur_strategy, PIDBrewStrategy)

    def test_new_strategy_inherits_the_brews_base_params(self, server, monkeypatch):
        """Not the config defaults: target_flow_rate lives only in cur_base_params."""
        params = dict(BASE_PARAMS, target_flow_rate=1.5)
        _running(server, monkeypatch, base_params=params)
        _switch(server)
        assert server.cur_strategy.target_flow_rate == 1.5

    def test_warm_start_seeds_the_new_strategy(self, server, monkeypatch, mock_valve):
        _running(server, monkeypatch, valve=mock_valve)
        mock_valve.get_position.return_value = 42
        monkeypatch.setattr(server.weight_buffer, "is_ready", lambda: True)
        monkeypatch.setattr(server.weight_buffer, "is_stale", lambda: False)
        monkeypatch.setattr(server.weight_buffer, "get_flow_rate", lambda: 0.03)

        _switch(server)

        pid = server.cur_strategy
        assert pid.integral == 0.0
        assert pid.prev_timestamp is not None
        assert pid.prev_error == pytest.approx(pid.target_flow_rate - 0.03)
        assert server.cur_brew.strategy_switches[0].valve_position == 42

    def test_annotates_the_time_series(self, server, monkeypatch, mock_time_series):
        _running(server, monkeypatch)
        _switch(server)
        assert mock_time_series.write_strategy_switch.called

    def test_annotation_failure_does_not_abort_the_switch(
        self, server, monkeypatch, mock_time_series
    ):
        _running(server, monkeypatch)
        mock_time_series.write_strategy_switch.side_effect = RuntimeError("influx down")
        resp = _switch(server)
        assert resp.status == "strategy_switched"
        assert isinstance(server.cur_strategy, PIDBrewStrategy)


class _RecordingStrategy:
    """Returns a long interval so the loop is asleep unless something wakes it."""

    def __init__(self, name, interval=90):
        self.name = name
        self.valve_interval = interval
        self.interval = interval
        self.calls = []

    def step(self, flow_rate, weight):
        # time.monotonic, not the loop clock: brew_step_task runs step() in a
        # worker thread (run_step_with_heartbeat), where there is no running loop.
        self.calls.append(time.monotonic())
        return (ValveCommand.NOOP, self.interval)

    def warm_start(self, valve_position, flow_rate):
        pass


class TestLoopIntegration:
    def test_switch_interrupts_the_in_flight_sleep(self, server, monkeypatch):
        """A 90s interval must not delay the swap by 90s."""
        brew = _running(server, monkeypatch)
        old = _RecordingStrategy("old")
        new = _RecordingStrategy("new")
        monkeypatch.setattr(server, "cur_strategy", old)

        async def scenario():
            task = asyncio.create_task(server.brew_step_task(brew.id))
            await asyncio.sleep(0.05)  # let it step once and enter the long sleep
            server.cur_strategy = new
            server.strategy_switch_event.set()
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(scenario())

        assert len(old.calls) == 1
        assert len(new.calls) >= 1, "new strategy never ran -- sleep was not interrupted"

    def test_switch_during_a_step_does_not_burst_valve_commands(
        self, server, monkeypatch
    ):
        """The event is cleared at the top of the loop, so a switch that lands while
        the loop is inside step() does not make the next sleep return instantly."""
        brew = _running(server, monkeypatch)
        new = _RecordingStrategy("new")

        class SwitchingStrategy(_RecordingStrategy):
            def step(self, flow_rate, weight):
                out = super().step(flow_rate, weight)
                # Mimic a switch arriving while the loop is not sleeping.
                server.cur_strategy = new
                server.strategy_switch_event.set()
                return out

        old = SwitchingStrategy("old")
        monkeypatch.setattr(server, "cur_strategy", old)

        async def scenario():
            task = asyncio.create_task(server.brew_step_task(brew.id))
            await asyncio.sleep(0.2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(scenario())

        # The new strategy runs on the next iteration but must then wait out its own
        # 90s interval rather than spinning.
        assert len(new.calls) == 1

    def test_early_wake_still_heartbeats(self, server, monkeypatch, mock_valve):
        brew = _running(server, monkeypatch, valve=mock_valve)
        monkeypatch.setattr(server, "cur_strategy", _RecordingStrategy("s"))

        async def scenario():
            task = asyncio.create_task(server.brew_step_task(brew.id))
            await asyncio.sleep(0.05)
            before = mock_valve.heartbeat.call_count
            server.strategy_switch_event.set()
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return before

        before = asyncio.run(scenario())
        assert mock_valve.heartbeat.call_count > before

    def test_loop_ends_if_the_strategy_is_cleared(self, server, monkeypatch):
        brew = _running(server, monkeypatch)
        monkeypatch.setattr(server, "cur_strategy", None)
        asyncio.run(asyncio.wait_for(server.brew_step_task(brew.id), timeout=1))
        assert brew.status == BrewState.BREWING
