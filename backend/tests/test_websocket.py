"""
Tests for WebSocket endpoints.
"""
import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import time


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


def test_websocket_heartbeat_configuration():
    """Test that heartbeat configuration is loaded from environment or defaults."""
    from brewserver.server import WS_HEARTBEAT_INTERVAL, WS_PONG_TIMEOUT
    
    # Check defaults are reasonable
    assert WS_HEARTBEAT_INTERVAL > 0
    assert WS_PONG_TIMEOUT > 0
    assert WS_PONG_TIMEOUT < WS_HEARTBEAT_INTERVAL


def test_connection_manager_tracks_metadata():
    """Test that ConnectionManager tracks connection metadata for heartbeat."""
    from brewserver.server import ConnectionManager
    import asyncio
    
    # Create manager and verify initial state
    manager = ConnectionManager()
    assert len(manager.get_connections()) == 0
    
    # Check stale connections returns empty list initially
    stale = manager.check_stale_connections()
    assert len(stale) == 0


def test_connection_manager_handles_pong():
    """Test that ConnectionManager properly handles pong responses."""
    from brewserver.server import ConnectionManager
    from fastapi import WebSocket
    from unittest.mock import MagicMock
    
    manager = ConnectionManager()
    
    # Create a mock websocket
    mock_ws = MagicMock(spec=WebSocket)
    
    # Simulate connection with metadata
    asyncio.run(manager.connect(mock_ws))
    
    # Verify connection tracked with metadata
    assert len(manager.get_connections()) == 1
    
    # Verify handle_pong doesn't error
    manager.handle_pong(mock_ws)
    
    # Verify pong was processed (awaiting_pong should be False)
    assert manager.active_connections[mock_ws]["awaiting_pong"] == False
    
    # Cleanup
    manager.disconnect(mock_ws)


def test_connection_manager_stale_detection():
    """Test that ConnectionManager detects stale connections."""
    from brewserver.server import ConnectionManager, WS_PONG_TIMEOUT
    from fastapi import WebSocket
    from unittest.mock import MagicMock
    import time
    
    manager = ConnectionManager()
    
    # Create a mock websocket
    mock_ws = MagicMock(spec=WebSocket)
    
    # Manually add connection with old timestamp (simulating waiting for pong)
    manager.active_connections[mock_ws] = {
        "last_ping": time.time() - WS_PONG_TIMEOUT - 1,  # Past timeout
        "awaiting_pong": True
    }
    
    # Check stale connections
    stale = manager.check_stale_connections()
    assert len(stale) == 1
    assert mock_ws in stale
    
    # Cleanup
    manager.disconnect(mock_ws)
