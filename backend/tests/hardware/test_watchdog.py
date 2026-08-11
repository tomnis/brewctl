"""
Tests for the hardware valve watchdog (deadman switch).
"""

import asyncio

import pytest

import brewctl.hardware.server as hw_server


@pytest.fixture
def fast_watchdog(monkeypatch, hardware_mock_valve):
    """
    Install the mock valve and shrink the watchdog timings so a trip happens in
    milliseconds. Returns a setter for the valve's reported position.
    """
    monkeypatch.setattr(hw_server, "valve", hardware_mock_valve)
    monkeypatch.setattr(hw_server, "WATCHDOG_POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(hw_server, "WATCHDOG_TIMEOUT_SECONDS", 0.02)
    hw_server._last_valve_command_time = 0.0  # already stale

    def _at(position):
        hardware_mock_valve.get_position.return_value = position
        return hardware_mock_valve

    return _at


def run_watchdog_for(seconds: float) -> asyncio.Task:
    """Run the watchdog briefly and return the (cancelled) task for inspection."""

    async def _run():
        task = asyncio.create_task(hw_server.hardware_watchdog())
        await asyncio.sleep(seconds)
        died = task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return died

    return asyncio.run(_run())


def test_watchdog_closes_open_valve_after_timeout(fast_watchdog):
    """An open valve with a stale command time gets closed."""
    valve = fast_watchdog(5)

    run_watchdog_for(0.1)

    valve.return_to_start.assert_called()


def test_watchdog_leaves_closed_valve_alone(fast_watchdog):
    """A valve already at the start position is not touched, however stale."""
    valve = fast_watchdog(0)

    run_watchdog_for(0.1)

    valve.return_to_start.assert_not_called()


def test_watchdog_survives_valve_errors(fast_watchdog):
    """A throwing valve must not kill the watchdog task."""
    valve = fast_watchdog(5)
    valve.return_to_start.side_effect = RuntimeError("motor jammed")

    died = run_watchdog_for(0.1)

    assert not died, "watchdog died on a valve error"
    valve.return_to_start.assert_called()


def test_heartbeat_endpoint_feeds_watchdog(hardware_client):
    """POST /api/valve/heartbeat refreshes the deadman timer."""
    hw_server._last_valve_command_time = 0.0

    response = hardware_client.post("/api/valve/heartbeat")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert hw_server._last_valve_command_time > 0.0


def test_health_does_not_feed_watchdog(hardware_client):
    """
    Unrelated traffic must not defeat the deadman switch -- only valve commands and
    the explicit heartbeat count.
    """
    hw_server._last_valve_command_time = 0.0

    assert hardware_client.get("/health").status_code == 200
    assert hardware_client.get("/api/valve/status").status_code == 200
    assert hardware_client.get("/").status_code == 200

    assert hw_server._last_valve_command_time == 0.0


def test_valve_commands_feed_watchdog(hardware_client):
    """Valve commands refresh the deadman timer."""
    hw_server._last_valve_command_time = 0.0

    assert hardware_client.post("/api/valve/return_to_start").status_code == 200

    assert hw_server._last_valve_command_time > 0.0
