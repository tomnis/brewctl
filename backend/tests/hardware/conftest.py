import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def hardware_mock_scale():
    """Mock scale for hardware server tests."""
    scale = MagicMock()
    scale.connected = True
    scale.get_weight.return_value = 100.0
    scale.get_units.return_value = "g"
    scale.get_battery_percentage.return_value = 75
    scale.connect.return_value = None
    scale.disconnect.return_value = None
    # Must be real values, not bare MagicMocks: _read_scale_status puts these in
    # the payload, and json.dumps in the SSE generator would raise on a MagicMock.
    scale.is_weight_stale.return_value = False
    scale.last_weight_age_seconds.return_value = 0.1
    scale.healthy.return_value = True
    return scale


@pytest.fixture
def hardware_mock_valve():
    """Mock valve for hardware server tests."""
    valve = MagicMock()
    valve.get_position.return_value = 0
    valve.step_forward.return_value = None
    valve.step_backward.return_value = None
    valve.return_to_start.return_value = None
    valve.release.return_value = None
    return valve


@pytest.fixture
def hardware_client(hardware_mock_scale, hardware_mock_valve):
    """
    Create a TestClient with mocked hardware dependencies.
    Patches create_scale and create_valve factory functions.
    """
    import brewctl.hardware.server as hw_server

    hw_server._nudge_last_call_time = 0.0
    # The lifespan starts scale_monitor. Push its interval out of reach so a slow
    # test never has it reconnect the mock out from under an assertion.
    original_interval = hw_server.SCALE_MONITOR_INTERVAL_SECONDS
    hw_server.SCALE_MONITOR_INTERVAL_SECONDS = 3600.0

    with (
        patch("brewctl.hardware.server.create_scale", return_value=hardware_mock_scale),
        patch("brewctl.hardware.server.create_valve", return_value=hardware_mock_valve),
    ):
        from brewctl.hardware.server import app

        with TestClient(app) as test_client:
            yield test_client

    hw_server.SCALE_MONITOR_INTERVAL_SECONDS = original_interval
    hw_server.scale = None
    hw_server.valve = None


@pytest.fixture(autouse=True)
def reset_prometheus_metrics():
    """See tests/api/conftest.py -- metrics are process-global."""
    from brewctl.core import metrics

    metrics.reset_metrics()
    yield
