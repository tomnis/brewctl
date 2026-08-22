"""
Tests for required-config validation in `api/config.py`.

Config is read at import time into module globals, so these reload the module
under a patched environment and reload it once more afterwards to leave the
process-wide values as the rest of the suite expects.

The value being protected is the error *message*. An unset BREWCTL_HARDWARE_URL
used to reach HttpScale as None and die with
`AttributeError: 'NoneType' object has no attribute 'rstrip'`, which names
neither the variable nor the fix.
"""

import importlib

import pytest

import brewctl.api.config as config


@pytest.fixture
def reload_config(monkeypatch):
    """Reload api.config under a patched env, restoring it afterwards."""
    # Prod also demands an InfluxDB token; supply one so these tests fail on the
    # hardware URL check rather than tripping over an unrelated one.
    monkeypatch.setenv("BREWCTL_INFLUXDB_TOKEN", "test-token")
    monkeypatch.delenv("BREWCTL_INFLUXDB_TOKEN_FILE", raising=False)

    yield lambda: importlib.reload(config)

    monkeypatch.undo()
    importlib.reload(config)


def test_missing_hardware_url_raises_in_prod(monkeypatch, reload_config):
    monkeypatch.setenv("BREWCTL_IS_PROD", "true")
    monkeypatch.delenv("BREWCTL_HARDWARE_URL", raising=False)

    with pytest.raises(ValueError, match="BREWCTL_HARDWARE_URL"):
        reload_config()


def test_blank_hardware_url_raises_in_prod(monkeypatch, reload_config):
    # An env var set to "" or whitespace is what a half-filled deployment
    # manifest produces, and it is as broken as an unset one.
    monkeypatch.setenv("BREWCTL_IS_PROD", "true")
    monkeypatch.setenv("BREWCTL_HARDWARE_URL", "   ")

    with pytest.raises(ValueError, match="BREWCTL_HARDWARE_URL"):
        reload_config()


def test_missing_hardware_url_defaults_off_prod(monkeypatch, reload_config):
    # Not prod: fall back rather than raise, so the test suite and a bare
    # `fastapi dev` run without any environment at all.
    monkeypatch.setenv("BREWCTL_IS_PROD", "false")
    monkeypatch.delenv("BREWCTL_HARDWARE_URL", raising=False)

    reloaded = reload_config()

    assert reloaded.BREWCTL_HARDWARE_URL == reloaded.BREWCTL_HARDWARE_DEFAULT_URL


def test_hardware_url_used_when_set(monkeypatch, reload_config):
    monkeypatch.setenv("BREWCTL_IS_PROD", "true")
    monkeypatch.setenv("BREWCTL_HARDWARE_URL", "http://device.internal:8000")

    reloaded = reload_config()

    assert reloaded.BREWCTL_HARDWARE_URL == "http://device.internal:8000"
