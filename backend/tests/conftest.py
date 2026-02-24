import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Add src to path so we can import brewctl
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def mock_scale():
    """Mock scale for testing."""
    scale = MagicMock()
    scale.connected = True
    scale.get_weight.return_value = 100.0
    scale.get_battery_percentage.return_value = 75
    scale.get_units.return_value = "g"
    scale.disconnect.return_value = None
    return scale


@pytest.fixture
def mock_valve():
    """Mock valve for testing."""
    valve = MagicMock()
    valve.step_forward.return_value = None
    valve.step_backward.return_value = None
    valve.return_to_start.return_value = None
    valve.release.return_value = None
    return valve


@pytest.fixture
def mock_time_series():
    """Mock time series for testing."""
    from datetime import datetime, timezone
    ts = MagicMock()
    ts.get_current_flow_rate.return_value = 5.0
    ts.get_current_weight.return_value = 100.0
    ts.write_scale_data.return_value = None
    # Mock methods that return lists/tuples to avoid MagicMock format errors
    # Return sample data so calculations work properly
    now = datetime.now(timezone.utc)
    ts.get_recent_weight_readings.return_value = [
        (now, 100.0),
        (now, 101.0),
        (now, 102.0),
    ]
    ts.calculate_flow_rate_from_derivatives.return_value = 5.0
    return ts


@pytest.fixture
def client(mock_scale, mock_valve, mock_time_series):
    """
    Create a TestClient with mocked dependencies.
    This patches the module-level variables in brewctl.server.
    """
    # Patch the module-level objects before importing app
    with patch("brewctl.server.create_scale", return_value=mock_scale), \
         patch("brewctl.server.create_valve", return_value=mock_valve), \
         patch("brewctl.server.create_time_series", return_value=mock_time_series), \
         patch("brewctl.server.scale", mock_scale), \
         patch("brewctl.server.valve", mock_valve), \
         patch("brewctl.server.time_series", mock_time_series):

        # Import app after patching
        from brewctl.server import app

        # Create client and yield
        with TestClient(app) as test_client:
            yield test_client

    # Reset global state after each test
    import brewctl.server as server_module
    server_module.cur_brew = None


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset global state before each test."""
    import brewctl.server as server_module
    server_module.cur_brew = None
    yield
    # Cleanup after test
    server_module.cur_brew = None
