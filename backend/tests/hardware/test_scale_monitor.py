"""
Tests for the scale monitor -- the task that reconnects a scale that has stopped
delivering readings.

The failure it guards against is specific: pyacaia marks the Lunar connected as
soon as BLE notifications are subscribed, before any weight packet arrives, and
never resets weight back to None once set. So a scale whose notification thread
died reports connected forever while every read returns None, until the process
restarts. `connected` alone therefore cannot drive recovery -- staleness must.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

import brewctl.hardware.server as hw_server


@pytest.fixture
def fast_monitor(monkeypatch):
    """Shrink the monitor interval so a tick happens in milliseconds."""
    monkeypatch.setattr(hw_server, "SCALE_MONITOR_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(hw_server, "SCALE_MAX_WEIGHT_AGE_SECONDS", 10.0)

    def _install(healthy: bool, age=None):
        scale = MagicMock()
        scale.connected = True
        scale.healthy.return_value = healthy
        scale.last_weight_age_seconds.return_value = age
        scale.reconnect_with_backoff.return_value = True
        monkeypatch.setattr(hw_server, "scale", scale)
        return scale

    return _install


def run_monitor_for(seconds: float) -> bool:
    """Run the monitor briefly. Returns True if the task died on its own."""

    async def _run():
        task = asyncio.create_task(hw_server.scale_monitor())
        await asyncio.sleep(seconds)
        died = task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return died

    return asyncio.run(_run())


def test_reconnects_a_connected_but_silent_scale(fast_monitor):
    """The whole point: connected is True, readings are not arriving."""
    scale = fast_monitor(healthy=False)

    run_monitor_for(0.1)

    scale.reconnect_with_backoff.assert_called()


def test_leaves_a_healthy_scale_alone(fast_monitor):
    scale = fast_monitor(healthy=True)

    run_monitor_for(0.1)

    scale.reconnect_with_backoff.assert_not_called()


def test_survives_a_failing_reconnect(fast_monitor):
    """A raising BLE reconnect must not kill the task -- it is the only recovery."""
    scale = fast_monitor(healthy=False)
    scale.reconnect_with_backoff.side_effect = RuntimeError("bluetooth is down")

    died = run_monitor_for(0.1)

    assert not died
    assert scale.reconnect_with_backoff.call_count > 1


def test_tolerates_a_scale_that_disappears(fast_monitor, monkeypatch):
    """Tests and the disconnect endpoint set the global to None underneath it."""
    fast_monitor(healthy=False)
    monkeypatch.setattr(hw_server, "scale", None)

    died = run_monitor_for(0.05)

    assert not died


def test_rereads_the_global_each_tick(fast_monitor, monkeypatch):
    """A captured reference would keep poking a scale that has been replaced."""
    stale = fast_monitor(healthy=False)
    replacement = MagicMock()
    replacement.connected = True
    replacement.healthy.return_value = True

    async def _run():
        task = asyncio.create_task(hw_server.scale_monitor())
        await asyncio.sleep(0.05)
        monkeypatch.setattr(hw_server, "scale", replacement)
        calls_at_swap = stale.reconnect_with_backoff.call_count
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return calls_at_swap

    calls_at_swap = asyncio.run(_run())

    assert stale.reconnect_with_backoff.call_count == calls_at_swap
    replacement.reconnect_with_backoff.assert_not_called()


def test_counts_reconnect_cycles(fast_monitor):
    from brewctl.core import metrics

    fast_monitor(healthy=False)

    run_monitor_for(0.05)

    body = metrics.metrics_response().body.decode()
    assert "brewctl_scale_reconnects_total" in body
