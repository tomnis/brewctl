"""
Tests for the valve heartbeat that keeps the hardware watchdog fed during a brew.
"""

import asyncio

import pytest


@pytest.fixture
def heartbeat_valve(client, monkeypatch, mock_valve):
    """
    The `client` fixture is what imports api.server under the HttpValve/HttpScale
    patches -- importing the module at test-module scope would bind the real classes.
    """
    import brewctl.api.server as server_module

    monkeypatch.setattr(server_module, "valve", mock_valve)
    # The client fixture installs mock_valve as the module global *before* TestClient
    # starts, so lifespan startup has already sent one connect+heartbeat through it.
    # These tests count heartbeats from the call under test only -- drop the
    # startup traffic. (reset_mock keeps the return_value configured in conftest.)
    mock_valve.reset_mock()
    monkeypatch.setattr(server_module, "HEARTBEAT_INTERVAL_SECONDS", 0.01)
    return server_module, mock_valve


def test_long_sleep_heartbeats_repeatedly(heartbeat_valve):
    """A sleep far longer than the heartbeat interval sends several heartbeats."""
    server_module, valve = heartbeat_valve

    asyncio.run(server_module.sleep_with_heartbeat(0.05))

    assert valve.heartbeat.call_count >= 4


def test_short_sleep_still_heartbeats_once(heartbeat_valve):
    """Even a sleep shorter than the interval sends one heartbeat."""
    server_module, valve = heartbeat_valve

    asyncio.run(server_module.sleep_with_heartbeat(0.005))

    assert valve.heartbeat.call_count == 1


def test_heartbeat_failure_does_not_break_the_loop(heartbeat_valve):
    """A hardware service that is down must not raise out of the brew loop."""
    server_module, valve = heartbeat_valve
    valve.heartbeat.side_effect = RuntimeError("hardware unreachable")

    asyncio.run(server_module.sleep_with_heartbeat(0.03))

    assert valve.heartbeat.call_count >= 2


def test_run_step_with_heartbeat_feeds_watchdog_during_a_slow_step(heartbeat_valve):
    """A strategy that blocks for seconds must not starve the hardware watchdog."""
    import time

    server_module, valve = heartbeat_valve

    class SlowStrategy:
        valve_interval = 90

        def step(self, flow_rate, weight):
            time.sleep(0.05)
            return ValveCommand.NOOP, 7

    from brewctl.core.model import ValveCommand

    result = asyncio.run(
        server_module.run_step_with_heartbeat(SlowStrategy(), 0.05, 100.0)
    )

    assert result == (ValveCommand.NOOP, 7)
    assert valve.heartbeat.call_count >= 2


def test_run_step_with_heartbeat_propagates_exceptions(heartbeat_valve):
    """Strategy errors must still reach brew_step_task's ERROR handler."""
    server_module, _valve = heartbeat_valve

    class ExplodingStrategy:
        def step(self, flow_rate, weight):
            raise RuntimeError("strategy blew up")

    with pytest.raises(RuntimeError, match="strategy blew up"):
        asyncio.run(
            server_module.run_step_with_heartbeat(ExplodingStrategy(), 0.05, 100.0)
        )


def test_brew_stopped_during_step_applies_no_valve_command(heartbeat_valve, mock_time_series):
    """
    A brew that ends while step() is in flight must not move the valve afterwards.

    Nothing cancels the brew tasks and asyncio.to_thread is not cancellable, so the
    step result outlives the brew. Applying it would drive the valve after
    return_to_start had already run.
    """
    import threading
    import time
    import uuid

    from brewctl.core.model import Brew, BrewState, ValveCommand

    server_module, valve = heartbeat_valve
    entered = threading.Event()

    class SlowForwardStrategy:
        valve_interval = 90

        def step(self, flow_rate, weight):
            entered.set()
            time.sleep(0.2)
            return ValveCommand.FORWARD, 1

    from datetime import datetime, timezone

    brew = Brew(
        id=str(uuid.uuid4()),
        status=BrewState.BREWING,
        time_started=datetime.now(timezone.utc),
        vessel_weight=229,
        target_weight=1337,
    )
    server_module.cur_brew = brew
    server_module.cur_strategy = SlowForwardStrategy()

    async def scenario():
        task = asyncio.create_task(server_module.brew_step_task(brew.id))
        # Stop the brew while the strategy is still thinking.
        await asyncio.to_thread(entered.wait, 2.0)
        server_module.cur_brew = None
        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(scenario())

    assert valve.step_forward.call_count == 0
