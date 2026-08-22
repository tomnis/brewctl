"""
Serialization and hygiene tests for LunarScale's connect path.

These need pyacaia/bluepy importable, which off-Pi dev machines deliberately
do not have (requirements/dev.txt excludes hardware.txt) -- they skip there
and run on the Pi.

The failure being locked in: two overlapping connects (scale_monitor tick vs
POST /api/scale/connect from start_brew) race for the scale's single BLE slot;
the loser leaks its bluepy-helper with a live HCI link, and that link blocks
every later attempt. The _connect_lock makes the loser wait instead.
"""

import threading

import pytest

pytest.importorskip("pyacaia")
pytest.importorskip("bluepy")

import brewctl.hardware.LunarScale as ls_module  # noqa: E402
from brewctl.hardware.LunarScale import LunarScale  # noqa: E402


@pytest.fixture
def lunar(monkeypatch):
    """A LunarScale whose AcaiaScale is a controllable fake."""
    state = {
        "active": 0,
        "max_active": 0,
        "connects": 0,
        "disconnects": 0,
        "sweeps": 0,
    }
    release = threading.Event()

    class FakeAcaia:
        connected = False

        def __init__(self, mac):
            pass

        def connect(self):
            state["connects"] += 1
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            release.wait(timeout=2.0)
            state["active"] -= 1
            return True

        def disconnect(self):
            state["disconnects"] += 1

    monkeypatch.setattr(ls_module, "AcaiaScale", FakeAcaia)
    monkeypatch.setattr(
        ls_module,
        "kill_orphaned_helpers",
        lambda: state.update(sweeps=state["sweeps"] + 1),
    )
    scale = LunarScale(
        "AA:BB:CC:DD:EE:FF", max_retries=2, base_delay=0.01, max_delay=0.02
    )
    return scale, state, release


def test_overlapping_connects_are_serialized(lunar):
    """Two racing connects must never both be inside connect() at once."""
    scale, state, release = lunar
    errors = []

    def _worker():
        try:
            scale.connect()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    t1 = threading.Thread(target=_worker)
    t1.start()
    # Let t1 take the lock and block inside its connect.
    t1.join(timeout=0.5)
    t2 = threading.Thread(target=_worker)
    t2.start()
    t2.join(timeout=0.5)

    # Both workers have been started; only one may have made it into connect().
    assert state["max_active"] == 1

    release.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert not errors
    assert state["connects"] == 2
    assert state["max_active"] == 1


def test_failed_attempt_sweeps_orphaned_helpers(lunar, monkeypatch):
    """
    Tonight's leak: a failed connect left its bluepy-helper alive holding a
    half-established HCI link. The failure path must best-effort disconnect
    AND sweep orphans, every attempt.
    """

    class Boom:
        connected = False

        def __init__(self, mac):
            pass

        def connect(self):
            raise RuntimeError("Failed to connect to peripheral")

        def disconnect(self):
            state["disconnects"] += 1

    scale, state, release = lunar
    monkeypatch.setattr(ls_module, "AcaiaScale", Boom)

    ok = scale.reconnect_with_backoff()

    assert ok is False
    # max_retries=2 -> one best-effort disconnect plus one sweep per attempt.
    assert state["disconnects"] == 2
    assert state["sweeps"] == 2


def test_successful_connect_does_not_sweep(lunar):
    """The sweep exists for failures; a healthy connect must not touch it."""
    scale, state, release = lunar

    workers = [threading.Thread(target=scale.connect) for _ in range(2)]
    for w in workers:
        w.start()
    release.set()
    for w in workers:
        w.join(timeout=2.0)

    assert state["connects"] == 2
    assert state["sweeps"] == 0
