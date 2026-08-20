"""
Tests for the api <-> hardware version handshake.

The Pi is deployed by hand and never self-updates, so it can lag the api
indefinitely. These cover the case that makes routine: someone promotes the NAS
and forgets to push to the Pi.
"""

import pytest

from brewctl.core.contract import HARDWARE_API_VERSION, MIN_HARDWARE_API_VERSION


@pytest.fixture
def server(client):
    """`client` is what imports api.server under the HttpValve/HttpScale patches."""
    import brewctl.api.server as server_module

    return server_module


def test_current_hardware_is_compatible(server, mock_valve):
    mock_valve.hardware_api_version = HARDWARE_API_VERSION

    compat = server.check_hardware_compatibility()

    assert compat["compatible"] is True
    assert compat["hardware_api_version"] == HARDWARE_API_VERSION


def test_old_hardware_is_incompatible(server, mock_valve, monkeypatch):
    monkeypatch.setattr(server, "valve", mock_valve)
    mock_valve.hardware_api_version = MIN_HARDWARE_API_VERSION - 1

    compat = server.check_hardware_compatibility()

    assert compat["compatible"] is False
    assert compat["reason"] == "hardware too old"


def test_unreached_hardware_is_incompatible(server, mock_valve, monkeypatch):
    """
    Unknown is treated as incompatible on purpose: better to refuse than to start
    a brew we may not be able to control.
    """
    monkeypatch.setattr(server, "valve", mock_valve)
    mock_valve.hardware_api_version = None

    compat = server.check_hardware_compatibility()

    assert compat["compatible"] is False
    assert compat["hardware_api_version"] is None


def test_non_integer_version_is_incompatible(server, mock_valve, monkeypatch):
    """A malformed response must not blow up the comparison."""
    monkeypatch.setattr(server, "valve", mock_valve)
    mock_valve.hardware_api_version = "banana"

    compat = server.check_hardware_compatibility()

    assert compat["compatible"] is False


def test_brew_start_refused_on_version_mismatch(client, server, mock_valve, monkeypatch):
    monkeypatch.setattr(server, "valve", mock_valve)
    mock_valve.hardware_api_version = MIN_HARDWARE_API_VERSION - 1

    response = client.post("/api/brew/start")

    assert response.status_code == 409
    detail = response.json()["detail"]
    # Distinguishable from the other 409 (a brew already running), which the
    # frontend has to tell apart.
    assert detail["code"] == "hardware_version_mismatch"
    assert "deploy-pi" in detail["message"]


def test_app_stays_up_on_version_mismatch(client, server, mock_valve, monkeypatch):
    """
    Never refuse to boot or take the UI down -- that is where you would find out
    what is wrong. Only brew *start* is blocked.

    (The /app route serves build/index.html, which only exists in a built image,
    so assert the route is registered rather than fetching it here.)
    """
    monkeypatch.setattr(server, "valve", mock_valve)
    mock_valve.hardware_api_version = MIN_HARDWARE_API_VERSION - 1

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/brew/status").status_code == 200
    assert any(getattr(r, "path", "") == "/app/{full_path:path}" for r in server.app.routes)


def test_health_reports_mismatch(client, server, mock_valve, monkeypatch):
    monkeypatch.setattr(server, "valve", mock_valve)
    mock_valve.hardware_api_version = MIN_HARDWARE_API_VERSION - 1

    body = client.get("/api/health").json()

    assert body["hardware"]["compatible"] is False
    assert body["status"] != "healthy"
