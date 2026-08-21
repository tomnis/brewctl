"""Dry-run brews: simulated hardware, accelerated clock, tagged time series.

`brewctl.api.server` is imported inside fixtures that depend on `client`, never
at module scope -- a top-level import binds the real HttpScale/HttpValve and
breaks the rest of the api suite with 503s.
"""

import asyncio

import pytest

from brewctl.core.model import BrewState
from brewctl.core.simulated_scale import SimulatedScale
from brewctl.core.valve import MockValve


@pytest.fixture
def server(client):
    import brewctl.api.server as server_module

    yield server_module

    # Never leave simulated hardware installed for the next test.
    server_module._restore_hardware()
    server_module.cur_brew = None


def start_payload(**overrides):
    payload = {
        "dry_run": True,
        "time_scale": 60.0,
        "target_flow_rate": 0.05,
        "valve_interval": 90,
        "epsilon": 0.008,
        "target_weight": 200.0,
        "vessel_weight": 0.0,
        "strategy": "default",
        "strategy_params": {},
    }
    payload.update(overrides)
    return payload


def test_dry_run_installs_simulated_hardware(client, server):
    response = client.post("/api/brew/start", json=start_payload())

    assert response.status_code == 200
    assert isinstance(server.valve, MockValve)
    assert isinstance(server.scale, SimulatedScale)
    assert server.scale.connected is True
    assert server._time_scale == 60.0


def test_dry_run_skips_the_hardware_version_check(client, server):
    # An out-of-date Pi 409s a real brew. A dry run does not involve the Pi at
    # all, so it must start anyway. Patch the valve the server module actually
    # holds -- the module is imported once per session, so it is not necessarily
    # this test's mock_valve fixture instance.
    original = server._real_valve.hardware_api_version
    server._real_valve.hardware_api_version = 0
    try:
        assert client.post("/api/brew/start", json=start_payload()).status_code == 200
        assert client.post("/api/brew/kill").status_code == 200

        # Same stale hardware, real brew: refused.
        refused = client.post("/api/brew/start", json=start_payload(dry_run=False))
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "hardware_version_mismatch"
    finally:
        server._real_valve.hardware_api_version = original


def test_brew_record_is_flagged(client, server):
    client.post("/api/brew/start", json=start_payload())

    assert server.cur_brew.dry_run is True
    assert client.get("/api/brew/status").json()["dry_run"] is True


def test_real_brew_is_not_flagged_and_keeps_real_hardware(client, server):
    client.post("/api/brew/start", json=start_payload(dry_run=False))

    assert server.cur_brew.dry_run is False
    assert server.scale is server._real_scale
    assert server.valve is server._real_valve
    assert server._time_scale == 1.0


@pytest.mark.parametrize("endpoint", ["/api/brew/kill", "/api/brew/stop"])
def test_hardware_is_restored_when_the_brew_ends(client, server, endpoint):
    client.post("/api/brew/start", json=start_payload())
    assert isinstance(server.valve, MockValve)

    url = endpoint
    if endpoint.endswith("/stop"):
        url = f"{endpoint}?brew_id={server.cur_brew.id}"
    assert client.post(url).status_code == 200

    # The load-bearing assertion: a dry run that leaked would leave the next real
    # brew driving a mock while reporting healthy.
    assert server.scale is server._real_scale
    assert server.valve is server._real_valve
    assert server._time_scale == 1.0


def test_hardware_is_restored_on_completion(client, server):
    client.post("/api/brew/start", json=start_payload())
    assert isinstance(server.valve, MockValve)

    server.cur_brew.status = BrewState.COMPLETED
    server._restore_hardware()

    assert server.valve is server._real_valve


def test_scale_writes_are_tagged_as_dry_run(client, server, mock_time_series):
    client.post("/api/brew/start", json=start_payload())

    asyncio.run(_one_scale_read(server))

    kwargs = mock_time_series.write_scale_data.call_args.kwargs
    assert kwargs["dry_run"] is True


async def _one_scale_read(server):
    """Run collect_scale_data_task just long enough for a single write."""
    task = asyncio.create_task(server.collect_scale_data_task(server.cur_brew.id, 0.01))
    await asyncio.sleep(0.05)
    server.cur_brew = None
    await asyncio.sleep(0.02)
    task.cancel()


def test_measured_flow_is_converted_to_the_brew_clock(server):
    # SimulatedScale fills time_scale times faster, but WeightBuffer measures in
    # wall-clock seconds -- so an unconverted flow reads time_scale times too
    # high and the strategy closes the valve on the first step. That is what the
    # first end-to-end dry run actually did.
    server._time_scale = 60.0
    assert server._simulated_flow(3.0) == pytest.approx(0.05)
    assert server._simulated_flow(None) is None

    server._time_scale = 1.0
    assert server._simulated_flow(3.0) == 3.0


def test_sleep_is_divided_by_the_time_scale(server):
    server._time_scale = 60.0
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    async def run():
        await server.sleep_with_heartbeat(90)

    original = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        asyncio.run(run())
    finally:
        asyncio.sleep = original

    # 90s at 60x is 1.5s of wall clock, chunked by the 3s heartbeat interval.
    assert sum(slept) == pytest.approx(1.5)
