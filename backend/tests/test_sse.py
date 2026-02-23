"""
Tests for SSE (Server-Sent Events) endpoints.
Tests the /sse/brew/status and /sse/health endpoints.

Note: Full streaming tests require running the server separately since the 
TestClient has issues with infinite SSE streams. These tests verify 
endpoint registration and underlying data functions.
"""
import json
import pytest


def test_sse_brew_status_endpoint_registered(client):
    """Test that the SSE brew status endpoint is registered."""
    from brewserver.server import app
    
    # Check route exists
    routes = [route.path for route in app.routes]
    assert "/sse/brew/status" in routes


def test_sse_health_endpoint_registered(client):
    """Test that the SSE health endpoint is registered."""
    from brewserver.server import app
    
    # Check route exists
    routes = [route.path for route in app.routes]
    assert "/sse/health" in routes


def test_sse_brew_status_no_brew_data(client):
    """Test that brew status returns correct data structure when no brew is in progress."""
    import asyncio
    from brewserver.server import brew_status
    
    # Run the async function
    result = asyncio.run(brew_status())
    assert result["status"] == "no brew in progress"
    assert result["brew_state"] == "idle"


def test_sse_health_data_structure(client):
    """Test that health returns correct data structure."""
    from brewserver.server import get_component_health
    
    # Call the function (it's not async)
    result = get_component_health()
    assert "scale" in result
    assert "valve" in result
    assert "influxdb" in result


def test_sse_brew_status_with_active_brew(client):
    """Test that brew status returns correct data when brew is active."""
    # Start a brew first
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    brew_id = response.json()["brew_id"]

    try:
        import asyncio
        from brewserver.server import brew_status
        
        # Run the async function
        result = asyncio.run(brew_status())
        assert result["brew_id"] == brew_id
        assert result["brew_state"] in ("brewing", "paused")
    finally:
        # Clean up
        client.post("/api/brew/kill")
