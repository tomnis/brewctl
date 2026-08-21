import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


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
    """Mock valve for testing. Emulates an up-to-date hardware service."""
    from brewctl.core.contract import HARDWARE_API_VERSION

    valve = MagicMock()
    valve.step_forward.return_value = None
    valve.step_backward.return_value = None
    valve.return_to_start.return_value = None
    valve.release.return_value = None
    valve.heartbeat.return_value = {"hardware_api_version": HARDWARE_API_VERSION}
    # Must be a real int: check_hardware_compatibility refuses to start a brew
    # against anything it cannot read a version from, and a bare MagicMock
    # attribute is not an int.
    valve.hardware_api_version = HARDWARE_API_VERSION
    return valve


@pytest.fixture
def mock_time_series():
    """Mock time series for testing."""
    from datetime import datetime, timezone

    ts = MagicMock()
    ts.get_current_flow_rate.return_value = 5.0
    ts.get_current_weight.return_value = 100.0
    ts.write_scale_data.return_value = None
    now = datetime.now(timezone.utc)
    ts.get_recent_weight_readings.return_value = [
        (now, 100.0),
        (now, 101.0),
        (now, 102.0),
    ]
    ts.calculate_flow_rate_from_derivatives.return_value = 5.0
    ts.write_strategy_switch.return_value = None
    return ts


@pytest.fixture
def client(mock_scale, mock_valve, mock_time_series):
    """
    Create a TestClient with mocked dependencies.
    This patches the HttpScale and HttpValve classes before importing the server module.
    """
    with (
        patch("brewctl.api.http_scale.HttpScale", return_value=mock_scale),
        patch("brewctl.api.http_valve.HttpValve", return_value=mock_valve),
        patch("brewctl.api.server.time_series", mock_time_series),
    ):
        from brewctl.api.server import app

        with TestClient(app) as test_client:
            yield test_client

    import brewctl.api.server as server_module

    _reset_server_globals(server_module)


def _reset_server_globals(server_module):
    """Clear every piece of brew state the module keeps.

    strategy_switch_event especially: it is created on whichever loop ran the brew
    task, so a leftover one makes the *next* test's sleep wait on a dead loop.
    """
    server_module.cur_brew = None
    server_module.cur_strategy = None
    server_module.cur_base_params = None
    server_module.strategy_switch_event = None
    server_module._last_strategy_switch_at = None


@pytest.fixture
def reset_globals():
    """Reset global state before each test."""
    import brewctl.api.server as server_module

    _reset_server_globals(server_module)
    yield
    _reset_server_globals(server_module)


@pytest.fixture(autouse=True)
def reset_prometheus_metrics():
    """Metrics are process-global like every other module global here.

    Autouse rather than hung off `client`: plenty of tests take `reset_globals`
    alone, and a counter that carried over would make delta assertions lie.
    """
    from brewctl.core import metrics

    metrics.reset_metrics()
    yield
