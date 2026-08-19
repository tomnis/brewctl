"""
Tests for `<VAR>_FILE` secret indirection.

The failure path matters more than the happy one: a missing secret mount that
silently yields an empty token surfaces as an opaque InfluxDB 401 on the first
write, potentially hours into a brew.
"""

import pytest

from brewctl.core.secrets import SecretConfigError, read_secret


def test_reads_from_environment_when_no_file(monkeypatch):
    monkeypatch.setenv("BREWCTL_TEST_SECRET", "from-env")
    monkeypatch.delenv("BREWCTL_TEST_SECRET_FILE", raising=False)

    assert read_secret("BREWCTL_TEST_SECRET") == "from-env"


def test_default_when_unset(monkeypatch):
    monkeypatch.delenv("BREWCTL_TEST_SECRET", raising=False)
    monkeypatch.delenv("BREWCTL_TEST_SECRET_FILE", raising=False)

    assert read_secret("BREWCTL_TEST_SECRET", "fallback") == "fallback"


def test_file_takes_precedence_over_environment(monkeypatch, tmp_path):
    secret = tmp_path / "token"
    secret.write_text("from-file\n")
    monkeypatch.setenv("BREWCTL_TEST_SECRET", "from-env")
    monkeypatch.setenv("BREWCTL_TEST_SECRET_FILE", str(secret))

    # Trailing newline stripped -- editors add one, and it would corrupt a token.
    assert read_secret("BREWCTL_TEST_SECRET") == "from-file"


def test_missing_file_raises_rather_than_falling_back(monkeypatch, tmp_path):
    monkeypatch.setenv("BREWCTL_TEST_SECRET", "from-env")
    monkeypatch.setenv("BREWCTL_TEST_SECRET_FILE", str(tmp_path / "nope"))

    with pytest.raises(SecretConfigError, match="could not be read"):
        read_secret("BREWCTL_TEST_SECRET")


def test_empty_file_raises(monkeypatch, tmp_path):
    secret = tmp_path / "token"
    secret.write_text("")
    monkeypatch.setenv("BREWCTL_TEST_SECRET_FILE", str(secret))

    with pytest.raises(SecretConfigError, match="empty"):
        read_secret("BREWCTL_TEST_SECRET")
