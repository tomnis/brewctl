"""
Tests for brew API endpoints.
Migrated from backend/src/brewserver/test_server.py
"""
import time


def test_brew_kill(client):
    """Test killing an active brew."""
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert 'brew_id' in response.json()

    # Try to start another brew while one is in progress
    response = client.post("/api/brew/start")
    assert response.status_code == 409
    assert response.json()["detail"] == "A brew is already in progress"

    # Kill the brew
    response = client.post("/api/brew/kill")
    assert response.status_code == 200
    assert response.json()["status"] == "killed"
    assert 'brew_id' in response.json()

    # Try to kill again when no brew is in progress
    response = client.post("/api/brew/kill")
    assert response.status_code == 404
    assert response.json() == {"detail": "no brew in progress"}


def test_brew_stop(client):
    """Test stopping a brew."""
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    brew_id = response.json()['brew_id']

    # Stop the brew
    endpoint = f"/api/brew/stop?brew_id={brew_id}"
    response = client.post(endpoint)
    assert response.status_code == 200

    # Try to stop again
    response = client.post(endpoint)
    assert response.status_code == 422

    # Try to stop without brew_id
    response = client.post("/api/brew/stop")
    assert response.status_code == 422


def test_flow_rate(client):
    """Test flow rate endpoint."""
    response = client.post("/api/brew/start")
    assert response.status_code == 200

    time.sleep(1)

    response = client.get("/api/brew/flow_rate")
    assert response.status_code == 200
    assert "flow_rate" in response.json()

    response = client.get("/api/brew/status")
    res = response.json()
    assert float(res["current_flow_rate"])
    assert float(res["current_weight"])

    response = client.post("/api/brew/kill")
    assert response.status_code == 200


def test_brew_pause_resume(client):
    """Test pausing and resuming a brew."""
    # Start a brew
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    assert response.json()["status"] == "started"

    # Pause the brew
    response = client.post("/api/brew/pause")
    assert response.status_code == 200
    assert response.json()["status"] == "paused"

    # Try to pause again (should say already paused)
    response = client.post("/api/brew/pause")
    assert response.status_code == 200
    assert response.json()["status"] == "already paused"

    # Resume the brew
    response = client.post("/api/brew/resume")
    assert response.status_code == 200
    assert response.json()["status"] == "resumed"

    # Try to resume again (should say already brewing)
    response = client.post("/api/brew/resume")
    assert response.status_code == 200
    assert response.json()["status"] == "already brewing"

    # Clean up
    response = client.post("/api/brew/kill")
    assert response.status_code == 200


def test_brew_status_no_brew(client):
    """Test brew status when no brew is in progress."""
    response = client.get("/api/brew/status")
    assert response.status_code == 200
    res = response.json()
    assert res["status"] == "no brew in progress"


def test_brew_status_with_active_brew(client):
    """Test brew status with an active brew."""
    # Start a brew
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    brew_id = response.json()["brew_id"]

    # Get status
    response = client.get("/api/brew/status")
    assert response.status_code == 200
    res = response.json()
    assert "brew_id" in res
    assert res["brew_id"] == brew_id

    # Clean up
    response = client.post("/api/brew/kill")
    assert response.status_code == 200
