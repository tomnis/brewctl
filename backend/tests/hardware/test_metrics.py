"""Tests for the hardware service's Prometheus metrics."""

import asyncio

import pytest

import brewctl.hardware.server as hw_server
from brewctl.core import metrics



@pytest.fixture
def fast_watchdog(monkeypatch, hardware_mock_valve):
    """Mock valve plus watchdog timings shrunk so a trip happens in milliseconds.

    Deliberately duplicated from test_watchdog.py rather than imported: a
    cross-module test import only resolves when pytest is run as `python -m
    pytest` (which puts the cwd on sys.path), not via the `pytest` script.
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


def run_watchdog_for(seconds: float):
    async def _run():
        task = asyncio.create_task(hw_server.hardware_watchdog())
        await asyncio.sleep(seconds)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    return asyncio.run(_run())


def sample(name, labels=None):
    return metrics.REGISTRY.get_sample_value(name, labels or {})


class TestEndpoint:
    def test_returns_prometheus_text(self, hardware_client):
        resp = hardware_client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")

    def test_exposes_the_hardware_metric_names(self, hardware_client):
        body = hardware_client.get("/metrics").text
        for name in (
            "brewctl_watchdog_trips_total",
            "brewctl_scale_connected",
            "brewctl_scale_healthy",
            "brewctl_scale_reconnects_total",
            "brewctl_sse_clients",
        ):
            assert name in body

    def test_does_not_feed_the_watchdog(self, hardware_client, monkeypatch):
        """A scraper polling every 15s must not hold the deadman open."""
        fed = []
        monkeypatch.setattr(hw_server, "feed_watchdog", lambda: fed.append(1))

        hardware_client.get("/metrics")

        assert fed == []


class TestWatchdogTrips:
    def test_counts_a_trip(self, fast_watchdog):
        fast_watchdog(5)

        run_watchdog_for(0.1)

        assert sample("brewctl_watchdog_trips_total") >= 1

    def test_no_trip_on_a_closed_valve(self, fast_watchdog):
        fast_watchdog(0)

        run_watchdog_for(0.1)

        assert sample("brewctl_watchdog_trips_total") == 0


class TestScaleConnected:
    def test_tracks_the_scale(self, hardware_client, hardware_mock_scale):
        hardware_mock_scale.connected = True
        hardware_client.get("/api/scale/status")
        assert sample("brewctl_scale_connected") == 1

        hardware_mock_scale.connected = False
        hardware_client.get("/api/scale/status")
        assert sample("brewctl_scale_connected") == 0


class TestSseClients:
    """Drives the generators directly.

    The decrement lands in the generator's finally, which runs when the response
    generator is closed -- TestClient's portal does not synchronise that with
    exiting the stream() context, so a client-side assertion on the decrement is
    flaky by construction.
    """

    @pytest.mark.parametrize(
        "stream,generator_name",
        [("valve", "sse_valve_status_generator"), ("scale", "sse_scale_status_generator")],
    )
    def test_counts_up_then_back_down(
        self, hardware_client, stream, generator_name, monkeypatch
    ):
        monkeypatch.setattr(hw_server, "VALVE_SSE_INTERVAL", 0.01)
        monkeypatch.setattr(hw_server, "SCALE_SSE_INTERVAL", 0.01)
        labels = {"stream": stream}

        async def one_event_then_close():
            gen = getattr(hw_server, generator_name)()
            await gen.__anext__()
            assert sample("brewctl_sse_clients", labels) == 1
            await gen.aclose()

        asyncio.run(one_event_then_close())

        assert sample("brewctl_sse_clients", labels) == 0
