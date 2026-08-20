"""
`/api/health` must not try to connect anything.

HttpScale.connect() makes a blocking 10s POST to the Pi, which then blocks
attempting BLE. get_scale_status() used to call it whenever the scale was
disconnected, and get_scale_status() is on the health path -- so with the scale
powered off, /api/health took up to 10s. The container healthcheck's timeout is
5s, so a healthy api reported unhealthy; and collect_scale_data_task makes the
same call every 0.5s during a brew, from inside the event loop.

Health is a status read. Connecting belongs to start_brew(), which does it with
backoff and fails loudly, and to the Pi, which owns physical reconnection.
"""

import pytest


@pytest.fixture
def server_scale(client):
    """
    The scale object the server is actually holding.

    Not the `mock_scale` fixture: api/server.py binds its module-global `scale`
    at import time, so every test after the first gets a fresh mock that the
    server never looks at. Reach for the module attribute instead.
    """
    import brewctl.api.server as server_module

    return server_module.scale


@pytest.fixture
def disconnected_scale(server_scale):
    """
    The interesting case: health checked while the scale is unreachable.

    Restores `connected` afterwards. That module-global scale object is shared by
    every test in the session, so leaving it False here fails unrelated tests
    later in the run.
    """
    previous = server_scale.connected
    server_scale.connected = False
    server_scale.connect.reset_mock()
    yield server_scale
    server_scale.connected = previous


def test_health_does_not_connect_the_scale(client, disconnected_scale):
    response = client.get("/api/health")

    assert response.status_code == 200
    disconnected_scale.connect.assert_not_called()


def test_health_reports_the_scale_disconnected(client, disconnected_scale):
    response = client.get("/api/health")

    assert response.json()["scale"]["connected"] is False


def test_health_still_reports_a_connected_scale(client, server_scale):
    # The read path must keep working -- this is not "health ignores the scale".
    server_scale.connected = True

    body = client.get("/api/health").json()

    assert body["scale"]["connected"] is True
    assert body["scale"]["battery_pct"] == 75


def test_scale_endpoint_does_not_connect_either(client, disconnected_scale):
    # /api/scale goes through the same get_scale_status().
    response = client.get("/api/scale")

    assert response.status_code == 200
    assert response.json()["connected"] is False
    disconnected_scale.connect.assert_not_called()
