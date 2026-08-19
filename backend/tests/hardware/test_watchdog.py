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
    monkeypatch.setattr(hw_server, "WATCHDOG_BACKSTOP_SECONDS", 0.5)
    hw_server._last_valve_command_time = 0.0  # already stale
    hw_server._last_heartbeat_time = 0.0

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


# ---------------------------------------------------------------------------
# Two-tier timeout.
#
# The api that talks to us may predate the heartbeat entirely. Such an api only
# contacts the hardware when it moves the valve, which can be as rare as
# BREWCTL_VALVE_INTERVAL_SECONDS (default 90) apart -- holding it to the 10s timer
# would close the valve ~10s into every brew. So the timeout is derived from
# whether a heartbeat has been seen recently, rather than stored as an armed flag.
# ---------------------------------------------------------------------------


@pytest.fixture
def tiers(monkeypatch):
    """Known tier values, and a clean heartbeat history."""
    monkeypatch.setattr(hw_server, "WATCHDOG_TIMEOUT_SECONDS", 10.0)
    monkeypatch.setattr(hw_server, "WATCHDOG_BACKSTOP_SECONDS", 300.0)
    hw_server._last_heartbeat_time = 0.0
    return hw_server


def test_recent_heartbeat_selects_short_timeout(tiers):
    """A current api heartbeats every few seconds and earns tight protection."""
    now = 1000.0
    tiers._last_heartbeat_time = now - 3.0

    assert tiers.effective_watchdog_timeout(now) == 10.0


def test_no_heartbeat_ever_selects_backstop(tiers):
    """
    An api from before the heartbeat existed must not be sabotaged: it feeds the
    timer only via valve commands, up to ~90s apart.
    """
    now = 1000.0
    tiers._last_heartbeat_time = 0.0

    assert tiers.effective_watchdog_timeout(now) == 300.0


def test_stale_heartbeat_decays_back_to_backstop(tiers):
    """
    Rolling back to an older api must not leave the tight timer latched on --
    that would close the valve mid-brew, the exact failure this design avoids.
    """
    now = 1000.0
    tiers._last_heartbeat_time = now - 301.0

    assert tiers.effective_watchdog_timeout(now) == 300.0


def test_valve_never_unguarded(tiers):
    """
    There is no state in which the watchdog is disabled. This is why arming only
    after a first heartbeat was rejected: a valve nudged open from the UI never
    produces one, and would have stayed open indefinitely.
    """
    now = 1000.0
    for last_heartbeat in (0.0, now - 1.0, now - 299.0, now - 1e6):
        tiers._last_heartbeat_time = last_heartbeat
        assert tiers.effective_watchdog_timeout(now) in (10.0, 300.0)


def test_record_heartbeat_feeds_both_timers(tiers):
    """A heartbeat proves liveness, so it also counts as feeding the watchdog."""
    tiers._last_valve_command_time = 0.0
    tiers._last_heartbeat_time = 0.0

    tiers.record_heartbeat()

    assert tiers._last_heartbeat_time > 0.0
    assert tiers._last_valve_command_time > 0.0


def test_valve_command_does_not_grant_short_timeout(tiers):
    """
    Only a heartbeat proves the caller speaks the current contract. An old api
    sends valve commands too, so those must not select the tight timer.
    """
    now = 1000.0
    tiers._last_heartbeat_time = 0.0
    tiers.feed_watchdog()

    assert tiers.effective_watchdog_timeout(now) == 300.0


def test_old_api_valve_commands_keep_valve_open(fast_watchdog):
    """
    End to end: an api that only sends valve commands (no heartbeats), at an
    interval below the backstop, must not have its valve closed.
    """
    valve = fast_watchdog(5)
    hw_server._last_heartbeat_time = 0.0

    async def _run():
        task = asyncio.create_task(hw_server.hardware_watchdog())
        # Backstop is 0.5s here; feed every 0.05s as an old api would.
        for _ in range(10):
            hw_server.feed_watchdog()
            await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())

    valve.return_to_start.assert_not_called()


def test_heartbeating_api_that_dies_trips_short_timer(fast_watchdog):
    """A current api that stops heartbeating loses the valve on the short timer."""
    valve = fast_watchdog(5)

    async def _run():
        hw_server.record_heartbeat()          # a live, current api
        task = asyncio.create_task(hw_server.hardware_watchdog())
        await asyncio.sleep(0.15)             # >> WATCHDOG_TIMEOUT_SECONDS (0.02)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run())

    valve.return_to_start.assert_called()
