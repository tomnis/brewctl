"""
Tests for brew API endpoints.
Migrated from backend/src/api/test_server.py
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
    # Machine-readable code: brew-in-progress and hardware-version-mismatch both
    # return 409, and the frontend has to tell them apart.
    assert response.json()["detail"]["code"] == "brew_in_progress"

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


def _server(client):
    """The patched server module. client must be requested first so HttpScale and
    HttpValve are mocked before the import binds them."""
    import brewctl.api.server as server_module

    return server_module


def test_vessel_weight_defaults_to_config_when_omitted(client):
    """Switching vessels must be an env var change, not a code change.

    The frontend deliberately does not send vessel_weight, so an omitted field has to
    resolve to BREWCTL_VESSEL_WEIGHT_GRAMS. Note the default is baked into the pydantic
    field when core.model is imported, so the env var only takes effect on restart --
    which is why this asserts the chain rather than patching a module attribute.
    """
    from brewctl.core.config import BREWCTL_VESSEL_WEIGHT_GRAMS
    from brewctl.core.model import StartBrewRequest

    # model_fields, not StartBrewRequest(): the model carries a stray @dataclass
    # decorator, whose __init__ demands every field positionally.
    assert (
        StartBrewRequest.model_fields["vessel_weight"].default
        == BREWCTL_VESSEL_WEIGHT_GRAMS
    )

    server = _server(client)
    response = client.post("/api/brew/start", json={"target_weight": 1000})
    assert response.status_code == 200
    assert server.cur_brew.vessel_weight == BREWCTL_VESSEL_WEIGHT_GRAMS



def test_explicit_vessel_weight_still_wins(client):
    """API callers can still override per brew."""
    server = _server(client)

    response = client.post(
        "/api/brew/start", json={"target_weight": 1000, "vessel_weight": 412}
    )
    assert response.status_code == 200
    assert server.cur_brew.vessel_weight == 412


def test_brew_status_exposes_vessel_weight(client):
    """The UI cannot show progress against coffee without it."""
    response = client.post(
        "/api/brew/start", json={"target_weight": 1000, "vessel_weight": 412}
    )
    assert response.status_code == 200

    response = client.get("/api/brew/status")
    assert response.status_code == 200
    assert response.json()["vessel_weight"] == 412
