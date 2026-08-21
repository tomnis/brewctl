"""
InfluxDB must not be able to hang or fail /api/health.

Two failure modes, both live:

  - Slow. InfluxDBTimeSeries built its client with a 30s timeout and healthcheck()
    used it. The container healthcheck's timeout is 5s and apply.sh's deploy gate
    curls with --max-time 10, so a slow or unreachable InfluxDB meant every probe
    and every gate poll timed out -- container unhealthy, app stuck in DEPLOYING,
    deploy failed, for a dependency that is non-fatal by design.
  - Silent. influxdb_client.ping() swallows exceptions and returns False rather
    than raising, and the health builders only set connected=False in an except.
    So an InfluxDB that was down but fast reported "connected": true.

A brew drives the valve off the in-process WeightBuffer and only falls back to
Influx derivative queries, so a missing InfluxDB degrades health -- never unhealthy.
"""

import pytest


@pytest.fixture
def server_valve(client):
    """The valve the server module is actually holding (bound at import time)."""
    import brewctl.api.server as server_module

    return server_module.valve


def test_influx_down_is_reported_disconnected(client, mock_time_series):
    # ping() returning False is the failure signal -- it does not raise.
    mock_time_series.healthcheck.return_value = False

    body = client.get("/api/health").json()

    assert body["influxdb"]["connected"] is False
    assert body["influxdb"]["error"]


def test_influx_raising_is_reported_disconnected(client, mock_time_series):
    mock_time_series.healthcheck.side_effect = RuntimeError("boom")

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["influxdb"]["connected"] is False
    assert "boom" in response.json()["influxdb"]["error"]


def test_influx_up_is_reported_connected(client, mock_time_series):
    mock_time_series.healthcheck.return_value = True

    body = client.get("/api/health").json()

    assert body["influxdb"] == {"connected": True, "error": None}


def test_influx_down_degrades_but_never_fails_the_deploy_gate(client, mock_time_series):
    # apply.sh accepts healthy or degraded; unhealthy fails the deploy.
    mock_time_series.healthcheck.return_value = False

    assert client.get("/api/health").json()["status"] == "degraded"


def test_influx_down_alone_never_reaches_unhealthy(
    client, mock_time_series, server_valve
):
    # Everything else down too: influxdb must not be the component that tips it over.
    import brewctl.api.server as server_module

    mock_time_series.healthcheck.return_value = False
    previous_connected = server_module.scale.connected
    previous_available = server_valve.available
    server_module.scale.connected = False
    server_valve.available = False
    try:
        body = client.get("/api/health").json()
    finally:
        # These are module-globals shared across the session -- leaving them false
        # fails unrelated tests later in the run.
        server_module.scale.connected = previous_connected
        server_valve.available = previous_available

    assert body["influxdb"]["connected"] is False
    assert body["status"] == "degraded"


def test_component_health_reports_influx_down(client, mock_time_series):
    # /sse/health and /ws/health go through get_component_health(), which had the
    # same swallowed-False bug.
    from brewctl.api.server import get_component_health

    mock_time_series.healthcheck.return_value = False

    assert get_component_health()["influxdb"]["connected"] is False
