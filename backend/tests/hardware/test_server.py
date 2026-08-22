"""
Tests for hardware server endpoints.
"""

import time


def test_root(hardware_client):
    """Test root endpoint returns hello message."""
    response = hardware_client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()
    assert "BrewCTL Hardware" in response.json()["message"]


def test_health(hardware_client):
    """Test health endpoint returns valve and scale status."""
    response = hardware_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["mode"] == "hardware"
    assert "valve" in data
    assert "scale" in data


def test_nudge_open(hardware_client):
    """Test nudge open endpoint steps valve forward."""
    response = hardware_client.post("/api/valve/nudge/open")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "nudged_open"
    assert "position" in data


def test_nudge_close(hardware_client):
    """Test nudge close endpoint steps valve backward."""
    response = hardware_client.post("/api/valve/nudge/close")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "nudged_closed"
    assert "position" in data


def test_return_to_start(hardware_client):
    """Test return_to_start endpoint resets valve position."""
    response = hardware_client.post("/api/valve/return_to_start")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "returned_to_start"


def test_release(hardware_client):
    """Test release endpoint releases valve."""
    response = hardware_client.post("/api/valve/release")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "released"


def test_valve_position(hardware_client):
    """Test valve position endpoint returns current position."""
    response = hardware_client.get("/api/valve/position")
    assert response.status_code == 200
    data = response.json()
    assert "position" in data


def test_valve_status(hardware_client):
    """Test valve status endpoint returns availability and position."""
    response = hardware_client.get("/api/valve/status")
    assert response.status_code == 200
    data = response.json()
    assert "available" in data
    assert "position" in data
    assert "status" in data


def test_scale_status(hardware_client):
    """Test scale status endpoint returns weight, units, battery."""
    response = hardware_client.get("/api/scale/status")
    assert response.status_code == 200
    data = response.json()
    assert "connected" in data
    assert "weight" in data
    assert "units" in data
    assert "battery_pct" in data


def test_scale_connect(hardware_client):
    """Test scale connect endpoint connects scale."""
    response = hardware_client.post("/api/scale/connect")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "connected"


def test_scale_disconnect(hardware_client):
    """Test scale disconnect endpoint disconnects scale."""
    response = hardware_client.post("/api/scale/disconnect")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disconnected"


def test_nudge_rate_limit(hardware_client):
    """Test nudge returns 429 when called too frequently."""
    response = hardware_client.post("/api/valve/nudge/open")
    assert response.status_code == 200

    response = hardware_client.post("/api/valve/nudge/open")
    assert response.status_code == 429
    assert "nudge too frequent" in response.json()["detail"]


def test_valve_not_available(hardware_client):
    """Test valve endpoints return 503 when valve is None."""
    import brewctl.hardware.server as hw_server

    original_valve = hw_server.valve
    hw_server.valve = None

    try:
        response = hardware_client.get("/api/valve/position")
        assert response.status_code == 503
        assert "valve not available" in response.json()["detail"]
    finally:
        hw_server.valve = original_valve


def test_scale_not_available(hardware_client):
    """Test scale endpoints return 503 when scale is None."""
    import brewctl.hardware.server as hw_server

    original_scale = hw_server.scale
    hw_server.scale = None

    try:
        response = hardware_client.get("/api/scale/status")
        assert response.status_code == 503
        assert "scale not available" in response.json()["detail"]
    finally:
        hw_server.scale = original_scale


class TestScaleHealthReporting:
    """
    A connected scale that has stopped streaming readings must be visible as such.
    `connected` alone cannot show it: pyacaia sets that flag before any weight
    packet arrives and never clears it when the notification stream dies.
    """

    def test_status_reports_health_and_age(self, hardware_client):
        data = hardware_client.get("/api/scale/status").json()

        assert data["healthy"] is True
        assert data["last_weight_age_seconds"] == 0.1

    def test_connected_but_stale_is_unhealthy(
        self, hardware_client, hardware_mock_scale
    ):
        hardware_mock_scale.is_weight_stale.return_value = True
        hardware_mock_scale.last_weight_age_seconds.return_value = 45.0

        data = hardware_client.get("/api/scale/status").json()

        assert data["connected"] is True
        assert data["healthy"] is False
        assert data["last_weight_age_seconds"] == 45.0

    def test_health_endpoint_carries_the_verdict(
        self, hardware_client, hardware_mock_scale
    ):
        hardware_mock_scale.is_weight_stale.return_value = True

        data = hardware_client.get("/health").json()

        # The top-level status is a liveness signal for container probes and
        # apply.sh -- a dead scale is not a dead service.
        assert data["status"] == "healthy"
        assert data["scale"]["connected"] is True
        assert data["scale"]["healthy"] is False

    def test_a_raising_read_degrades_rather_than_500s(
        self, hardware_client, hardware_mock_scale
    ):
        """An unguarded BLE exception used to take out /health and the SSE stream."""
        hardware_mock_scale.get_weight.side_effect = RuntimeError("BLE disconnected")

        response = hardware_client.get("/api/scale/status")

        assert response.status_code == 200
        assert response.json()["weight"] is None

    def test_status_payload_is_json_serialisable(self, hardware_mock_scale):
        """The SSE generator json.dumps() this dict -- a MagicMock in it raises."""
        import json

        import brewctl.hardware.server as hw_server

        hw_server.scale = hardware_mock_scale
        try:
            json.dumps(hw_server._read_scale_status())
        finally:
            hw_server.scale = None
