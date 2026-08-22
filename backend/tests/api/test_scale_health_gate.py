"""
Tests for refusing a brew against a scale that is connected but not reporting.

The Lunar can sit in a state where pyacaia still says connected -- the flag is
set when BLE notifications are subscribed, before any packet arrives, and is
never cleared if the notification thread dies -- while every read returns None.
A brew started there drives the valve with no feedback at all, which is worse
than not brewing.

Only the hardware service can tell the difference, so the api reads its verdict
rather than computing one: an HttpScale constructed seconds ago has never seen a
reading, and locally that is indistinguishable from a dead scale.
"""

import pytest


@pytest.fixture
def server(client):
    """`client` is what imports api.server under the HttpValve/HttpScale patches."""
    import brewctl.api.server as server_module

    return server_module


def test_brew_refused_when_scale_is_connected_but_silent(
    client, server, mock_scale, monkeypatch
):
    monkeypatch.setattr(server, "scale", mock_scale)
    mock_scale.is_healthy.return_value = False
    mock_scale.last_weight_age_seconds.return_value = 42.0

    response = client.post("/api/brew/start")

    assert response.status_code == 409
    detail = response.json()["detail"]
    # Distinguishable from the other 409s (already brewing, version mismatch).
    assert detail["code"] == "scale_unhealthy"
    assert detail["last_weight_age_seconds"] == 42.0


def test_unknown_verdict_does_not_block(client, server, mock_scale, monkeypatch):
    """A Pi on contract v1 sends no `healthy` field. Unknown must mean allow.

    Blocking on a missing field would refuse every brew against a Pi that simply
    has not been pushed to yet -- and the Pi lagging is the expected state here,
    not an edge case.
    """
    monkeypatch.setattr(server, "scale", mock_scale)
    mock_scale.is_healthy.return_value = None

    response = client.post("/api/brew/start")

    assert response.status_code == 200


def test_scale_without_the_method_does_not_block(
    client, server, mock_scale, monkeypatch
):
    """Not every AbstractScale implementation reports a verdict."""
    monkeypatch.setattr(server, "scale", mock_scale)
    del mock_scale.is_healthy

    response = client.post("/api/brew/start")

    assert response.status_code == 200


def test_healthy_scale_starts_normally(client, server, mock_scale, monkeypatch):
    monkeypatch.setattr(server, "scale", mock_scale)

    response = client.post("/api/brew/start")

    assert response.status_code == 200


def test_dry_run_is_exempt(client, server, mock_scale, monkeypatch):
    """A dry run swaps in a SimulatedScale; there is no Pi to be unhealthy."""
    monkeypatch.setattr(server, "scale", mock_scale)
    mock_scale.is_healthy.return_value = False

    response = client.post(
        "/api/brew/start",
        json={"target_weight": 100.0, "vessel_weight": 10.0, "dry_run": True},
    )

    assert response.status_code == 200


def test_health_does_not_double_count_one_fault(client, server, mock_scale, monkeypatch):
    """
    "not connected" and "connected but silent" are the same fault seen twice.
    Counting both would push a silent scale plus a down valve from DEGRADED to
    UNHEALTHY, which apply.sh refuses to deploy against.
    """
    monkeypatch.setattr(server, "scale", mock_scale)
    mock_scale.connected = False
    mock_scale.is_healthy.return_value = False

    data = client.get("/api/health").json()

    assert data["scale"]["connected"] is False
    assert data["status"] != "unhealthy"


def test_health_reports_a_silent_scale(client, server, mock_scale, monkeypatch):
    monkeypatch.setattr(server, "scale", mock_scale)
    mock_scale.is_healthy.return_value = False

    data = client.get("/api/health").json()

    assert data["scale"]["connected"] is True
    assert data["scale"]["healthy"] is False
    assert data["status"] == "degraded"
