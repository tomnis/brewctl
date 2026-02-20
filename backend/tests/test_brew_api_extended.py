"""
Extended API tests covering edge cases and endpoints not covered by test_brew_api.py.
Covers: scale endpoint, acquire/release, valve forward/backward, start with custom params,
pause/resume edge cases, and brew status in various states.
"""
import time


def test_scale_endpoint(client):
    """Test the /api/scale endpoint returns scale status."""
    response = client.get("/api/scale")
    assert response.status_code == 200
    data = response.json()
    assert "connected" in data
    assert "weight" in data
    assert "units" in data
    assert "battery_pct" in data


def test_scale_endpoint_returns_mock_values(client):
    """Test that scale endpoint returns the mocked values."""
    response = client.get("/api/scale")
    data = response.json()
    assert data["connected"] is True
    assert data["weight"] == 100.0
    assert data["units"] == "g"
    assert data["battery_pct"] == 75


def test_acquire_brew(client):
    """Test acquiring a brew via acquire endpoint."""
    response = client.post("/api/brew/acquire")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "valve acquired"
    assert "brew_id" in data

    # Clean up
    client.post("/api/brew/kill")


def test_acquire_brew_twice(client):
    """Test that acquiring twice returns already acquired."""
    response = client.post("/api/brew/acquire")
    assert response.status_code == 200
    assert "brew_id" in response.json()

    response = client.post("/api/brew/acquire")
    assert response.status_code == 200
    assert response.json()["status"] == "valve already acquired"

    # Clean up
    client.post("/api/brew/kill")


def test_valve_forward(client):
    """Test stepping valve forward during a brew."""
    response = client.post("/api/brew/start")
    brew_id = response.json()["brew_id"]

    response = client.post(f"/api/brew/valve/forward?brew_id={brew_id}")
    assert response.status_code == 200
    assert "stepped forward" in response.json()["status"]

    client.post("/api/brew/kill")


def test_valve_backward(client):
    """Test stepping valve backward during a brew."""
    response = client.post("/api/brew/start")
    brew_id = response.json()["brew_id"]

    response = client.post(f"/api/brew/valve/backward?brew_id={brew_id}")
    assert response.status_code == 200
    assert "stepped backward" in response.json()["status"]

    client.post("/api/brew/kill")


def test_valve_forward_wrong_brew_id(client):
    """Test that valve forward with wrong brew_id fails."""
    response = client.post("/api/brew/start")
    assert response.status_code == 200

    response = client.post("/api/brew/valve/forward?brew_id=wrong-id")
    assert response.status_code == 422

    client.post("/api/brew/kill")


def test_valve_backward_wrong_brew_id(client):
    """Test that valve backward with wrong brew_id fails."""
    response = client.post("/api/brew/start")
    assert response.status_code == 200

    response = client.post("/api/brew/valve/backward?brew_id=wrong-id")
    assert response.status_code == 422

    client.post("/api/brew/kill")


def test_start_brew_with_custom_params(client):
    """Test starting a brew with custom parameters."""
    response = client.post("/api/brew/start", json={
        "target_flow_rate": 0.1,
        "target_weight": 2000,
        "vessel_weight": 300,
        "scale_interval": 1.0,
        "valve_interval": 60,
        "epsilon": 0.01,
        "strategy": "default",
        "strategy_params": {},
    })
    assert response.status_code == 200
    assert response.json()["status"] == "started"

    client.post("/api/brew/kill")


def test_start_brew_with_pid_strategy(client):
    """Test starting a brew with PID strategy."""
    response = client.post("/api/brew/start", json={
        "target_flow_rate": 0.05,
        "target_weight": 1337,
        "vessel_weight": 229,
        "scale_interval": 0.5,
        "valve_interval": 90,
        "epsilon": 0.008,
        "strategy": "pid",
        "strategy_params": {"kp": 2.0, "ki": 0.2, "kd": 0.1},
    })
    assert response.status_code == 200
    assert response.json()["status"] == "started"

    client.post("/api/brew/kill")


def test_pause_without_brew(client):
    """Test pausing when no brew is in progress."""
    response = client.post("/api/brew/pause")
    assert response.status_code == 400


def test_resume_without_brew(client):
    """Test resuming when no brew is in progress."""
    response = client.post("/api/brew/resume")
    assert response.status_code == 400


def test_flow_rate_no_brew(client):
    """Test flow rate endpoint when no brew is in progress."""
    response = client.get("/api/brew/flow_rate")
    assert response.status_code == 200
    data = response.json()
    assert data["brew_id"] is None


def test_stop_wrong_brew_id(client):
    """Test stopping with wrong brew_id."""
    response = client.post("/api/brew/start")
    assert response.status_code == 200

    response = client.post("/api/brew/stop?brew_id=wrong-id")
    assert response.status_code == 422

    client.post("/api/brew/kill")


def test_brew_lifecycle_start_pause_resume_kill(client):
    """Test full lifecycle: start -> pause -> resume -> kill."""
    # Start
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    brew_id = response.json()["brew_id"]

    # Pause
    response = client.post("/api/brew/pause")
    assert response.status_code == 200
    assert response.json()["brew_state"] == "paused"

    # Check status while paused
    response = client.get("/api/brew/status")
    assert response.status_code == 200

    # Resume
    response = client.post("/api/brew/resume")
    assert response.status_code == 200
    assert response.json()["brew_state"] == "brewing"

    # Kill
    response = client.post("/api/brew/kill")
    assert response.status_code == 200
    assert response.json()["brew_id"] == brew_id


def test_start_brew_default_no_body(client):
    """Test starting a brew with no request body uses defaults."""
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert "brew_id" in response.json()

    client.post("/api/brew/kill")


def test_release_brew(client):
    """Test the release endpoint."""
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    brew_id = response.json()["brew_id"]

    response = client.post(f"/api/brew/release?brew_id={brew_id}")
    assert response.status_code == 200
    assert "released" in response.json()["status"]
