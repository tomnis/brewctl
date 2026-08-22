"""
Tests for the scale monitor -- the task that reconnects a scale that has stopped
delivering readings.

The failure it guards against is specific: pyacaia marks the Lunar connected as
soon as BLE notifications are subscribed, before any weight packet arrives, and
never resets weight back to None once set. So a scale whose notification thread
died reports connected forever while every read returns None, until the process
restarts. `connected` alone therefore cannot drive recovery -- staleness must.

Policy since docs/plans/scale-recovery-stability-plan.md: a CONNECTED scale is
given a patience window (BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS) before being
torn down -- reconnect churn through the leaky BLE path made recovery strictly
worse. Two conditions skip patience: the link itself is down, or nothing has
EVER arrived (age None -- the disease itself).
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
    monkeypatch.setattr(hw_server, "BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS", 30.0)
    hw_server._monitor_kick.clear()

    def _install(healthy: bool, age=999.0, connected: bool = True):
        scale = MagicMock()
        scale.connected = connected
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


def test_reconnects_after_quiet_exceeds_the_patience_window(fast_monitor):
    """Connected but silent far past the window: assume dead stream, rebuild."""
    scale = fast_monitor(healthy=False, age=999.0)

    run_monitor_for(0.1)

    scale.reconnect_with_backoff.assert_called()


def test_keeps_the_link_while_quiet_within_the_patience_window(fast_monitor):
    """
    Connected and recently streaming: leave it alone. The stream may be quiet
    simply because nothing changed; reconnect churn made things worse.
    """
    scale = fast_monitor(healthy=False, age=5.0)

    run_monitor_for(0.1)

    scale.reconnect_with_backoff.assert_not_called()


def test_never_delivered_skips_patience(fast_monitor):
    """
    age None means not one packet has ever arrived on this connection -- that
    is the pyacaia dead-subscription disease itself, so no patience.
    """
    scale = fast_monitor(healthy=False, age=None)

    run_monitor_for(0.1)

    scale.reconnect_with_backoff.assert_called()


def test_a_disconnected_scale_skips_patience(fast_monitor):
    scale = fast_monitor(healthy=False, age=0.0, connected=False)

    run_monitor_for(0.1)

    scale.reconnect_with_backoff.assert_called()


def test_patience_window_is_configurable(fast_monitor, monkeypatch):
    monkeypatch.setattr(hw_server, "BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS", 3.0)
    # Quiet for 5s: inside the 30s default but past a 3s window.
    scale = fast_monitor(healthy=False, age=5.0)

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


def test_kick_prompts_an_immediate_tick_despite_a_long_interval(
    fast_monitor, monkeypatch
):
    """The disconnect endpoint sets the kick so post-teardown reconnect is
    immediate rather than up to a full (here: hour-long) interval later."""
    monkeypatch.setattr(hw_server, "SCALE_MONITOR_INTERVAL_SECONDS", 3600.0)
    scale = fast_monitor(healthy=False)
    hw_server._monitor_kick.set()

    run_monitor_for(0.1)

    scale.reconnect_with_backoff.assert_called()


def test_disconnect_endpoint_sets_the_monitor_kick(hardware_client):
    """Cancel/stop POSTs here; the kick is what makes recovery immediate."""
    hardware_client.post("/api/scale/disconnect")

    assert hw_server._monitor_kick.is_set()
