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
