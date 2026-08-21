"""
Tests for scale-MAC validation in `hardware/config.py`.

install.sh copies deploy/pi/hardware.env.example verbatim to
/etc/brewctl/hardware.env on a fresh install, so the placeholder MAC in that file
can reach a running service unedited. create_scale() gates on BREWCTL_IS_PROD
alone, so an unedited MAC would build a LunarScale that can never connect: the
service starts, /health reports on a scale that was never going to work, and the
cause is buried in a BLE timeout. Fail at import instead, like api/config.py does
for the InfluxDB token.

Config is read at import time into module globals, so these reload the module
under a patched environment and reload it once more afterwards.
"""

import importlib

import pytest

import brewctl.hardware.config as config


@pytest.fixture
def reload_config(monkeypatch):
    """Reload hardware.config under a patched env, restoring it afterwards."""
    yield lambda: importlib.reload(config)

    monkeypatch.undo()
    importlib.reload(config)


def test_placeholder_mac_raises_in_prod(monkeypatch, reload_config):
    monkeypatch.setenv("BREWCTL_IS_PROD", "true")
    monkeypatch.setenv(
        "BREWCTL_SCALE_MAC_ADDRESS", config.BREWCTL_SCALE_MAC_PLACEHOLDER
    )

    with pytest.raises(ValueError, match="BREWCTL_SCALE_MAC_ADDRESS"):
        reload_config()


def test_missing_mac_raises_in_prod(monkeypatch, reload_config):
    monkeypatch.setenv("BREWCTL_IS_PROD", "true")
    monkeypatch.delenv("BREWCTL_SCALE_MAC_ADDRESS", raising=False)

    with pytest.raises(ValueError, match="BREWCTL_SCALE_MAC_ADDRESS"):
        reload_config()


def test_real_mac_is_accepted_in_prod(monkeypatch, reload_config):
    monkeypatch.setenv("BREWCTL_IS_PROD", "true")
    monkeypatch.setenv("BREWCTL_SCALE_MAC_ADDRESS", "11:22:33:44:55:66")

    reloaded = reload_config()

    assert reloaded.BREWCTL_SCALE_MAC_ADDRESS == "11:22:33:44:55:66"


def test_placeholder_is_treated_as_unset_off_prod(monkeypatch, reload_config):
    # Off prod nothing raises -- the placeholder just means "no scale", which
    # create_scale() already answers with MockScale.
    monkeypatch.setenv("BREWCTL_IS_PROD", "false")
    monkeypatch.setenv(
        "BREWCTL_SCALE_MAC_ADDRESS", config.BREWCTL_SCALE_MAC_PLACEHOLDER
    )

    reloaded = reload_config()

    assert reloaded.BREWCTL_SCALE_MAC_ADDRESS == ""


def test_placeholder_match_ignores_case_and_whitespace(monkeypatch, reload_config):
    monkeypatch.setenv("BREWCTL_IS_PROD", "false")
    monkeypatch.setenv("BREWCTL_SCALE_MAC_ADDRESS", "  aa:bb:cc:dd:ee:ff  ")

    reloaded = reload_config()

    assert reloaded.BREWCTL_SCALE_MAC_ADDRESS == ""
