"""
Tests for WebSocket endpoints.
"""
import pytest
from fastapi.testclient import TestClient


def test_websocket_connection_no_brew(client):
    """Test that WebSocket connection is accepted and sends status when no brew."""
    with client.websocket_connect("/ws/brew/status") as websocket:
        # Should receive at least one message
        data = websocket.receive_json()
        assert "brew_state" in data
        assert data["brew_state"] == "idle"


def test_websocket_sends_status_fields(client):
    """Test that WebSocket sends proper status fields."""
    with client.websocket_connect("/ws/brew/status") as websocket:
        data = websocket.receive_json()
        # Should have brew_state field
        assert "brew_state" in data
        # Should have status field
        assert "status" in data


def test_websocket_with_active_brew(client):
    """Test WebSocket sends status during an active brew."""
    # Start a brew first
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    brew_id = response.json()["brew_id"]
    
    with client.websocket_connect("/ws/brew/status") as websocket:
        # Get messages until we find our brew_id
        data = None
        for _ in range(10):
            data = websocket.receive_json()
            if data.get("brew_id") == brew_id:
                break
        
        # Verify we got the correct brew_id
        assert data is not None
        assert data["brew_id"] == brew_id
        assert data["brew_state"] == "brewing"
    
    # Clean up
    client.post("/api/brew/kill")


def test_websocket_receives_multiple_updates(client):
    """Test that WebSocket receives multiple status updates."""
    # Start a brew
    client.post("/api/brew/start")
    
    with client.websocket_connect("/ws/brew/status") as websocket:
        # Get multiple messages
        messages = []
        for _ in range(3):
            data = websocket.receive_json()
            messages.append(data)
        
        # Should have received messages with brew_state
        assert len(messages) == 3
        for msg in messages:
            assert "brew_state" in msg
    
    # Clean up
    client.post("/api/brew/kill")


def test_websocket_pause_status(client):
    """Test WebSocket shows paused status correctly."""
    # Start a brew
    client.post("/api/brew/start")
    
    # Pause it
    client.post("/api/brew/pause")
    
    with client.websocket_connect("/ws/brew/status") as websocket:
        # Look for paused state
        found_paused = False
        for _ in range(10):
            data = websocket.receive_json()
            if data.get("brew_state") == "paused":
                found_paused = True
                break
        
        assert found_paused, "Should receive paused state"
    
    # Clean up
    client.post("/api/brew/kill")


def test_websocket_no_brew_in_progress(client):
    """Test WebSocket shows no brew in progress when no brew exists."""
    # Make sure no brew is running
    client.post("/api/brew/kill")
    
    with client.websocket_connect("/ws/brew/status") as websocket:
        data = websocket.receive_json()
        # Should show no brew in progress
        assert data.get("status") == "no brew in progress"
        assert data.get("brew_state") == "idle"
