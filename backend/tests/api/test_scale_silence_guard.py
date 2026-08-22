"""
The open-loop pour guard: a scale that goes silent mid-brew must fail the brew
and return the valve, because the strategy cannot act on a None flow (NOOP)
and cannot STOP on a None weight -- the valve would freeze wherever it sits,
likely open, pouring unattended.

Drives collect_scale_data_task directly (see test_brew_pause.py for why
TestClient does not reproduce task-level behavior). The silence clock is
faked with a scriptable monotonic() so window boundaries are deterministic.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from brewctl.core.model import Brew, BrewState, BrewStrategyType


@pytest.fixture
def server(client):
    """`client` is what imports api.server under the HttpValve/HttpScale patches."""
    import brewctl.api.server as server_module

    return server_module


class FakeClock:
    """Scriptable time.monotonic: pops queued readings, holds the last one."""

    def __init__(self, readings):
        self.readings = list(readings)

    def monotonic(self):
        if len(self.readings) > 1:
            return self.readings.pop(0)
        return self.readings[0]


def _brewing():
    return Brew(
        id="test-brew",
        status=BrewState.BREWING,
        time_started=datetime.now(timezone.utc),
        target_weight=1000,
        vessel_weight=200,
        strategy=BrewStrategyType.DEFAULT,
    )


def _silent_scale():
    return SimpleNamespace(weight=None, battery_pct=None)


async def _run_briefly(coro_fn, seconds=0.05):
    task = asyncio.create_task(coro_fn())
    await asyncio.sleep(seconds)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_sustained_silence_fails_the_brew_and_returns_the_valve(
    server, monkeypatch
):
    brew = _brewing()
    monkeypatch.setattr(server, "cur_brew", brew)
    monkeypatch.setattr(server, "get_scale_status", lambda: _silent_scale())
    valve = MagicMock()
    monkeypatch.setattr(server, "valve", valve)
    # Tiny-but-positive: trips once at least this much wall time has passed.
    # (Exactly 0 would mean "guard disabled" -- see the next test.)
    monkeypatch.setattr(server, "BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS", 0.001)

    asyncio.run(
        _run_briefly(lambda: server.collect_scale_data_task(brew.id, 0.001))
    )

    assert brew.status == BrewState.ERROR
    assert "silent" in (brew.error_message or "")
    valve.return_to_start.assert_called()


def test_a_single_silent_read_inside_the_window_is_tolerated(server, monkeypatch):
    """Patience: quiet ticks inside the window must not fail an otherwise
    healthy brew."""
    brew = _brewing()
    monkeypatch.setattr(server, "cur_brew", brew)
    monkeypatch.setattr(server, "get_scale_status", lambda: _silent_scale())
    valve = MagicMock()
    monkeypatch.setattr(server, "valve", valve)
    monkeypatch.setattr(server, "BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS", 3600)

    asyncio.run(
        _run_briefly(lambda: server.collect_scale_data_task(brew.id, 0.02))
    )

    assert brew.status == BrewState.BREWING
    valve.return_to_start.assert_not_called()


def test_a_real_reading_resets_the_silence_clock(server, monkeypatch):
    """
    Silence -> real reading -> silence: the window restarts from the real
    reading. Clock script (threshold 10):
      it1 t=100 silent -> window opens
      it2 t=104 real   -> clock resets (and ERROR recovers if any)
      it3 t=106 silent -> 0s into new window: tolerated
      it4 t=109 silent -> 3s: tolerated
      it5 t=112 silent -> 6s: tolerated
      it6 t=120 silent -> 14s: TRIP
    Without the reset, it3 (104 -> 106 relative to 104) would look small but
    it4 (9s from 100) and it5 (12s from 100) would already have tripped.
    """
    brew = _brewing()
    monkeypatch.setattr(server, "cur_brew", brew)
    valve = MagicMock()
    monkeypatch.setattr(server, "valve", valve)
    monkeypatch.setattr(server, "BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS", 10)

    clock = FakeClock([100, 104, 106, 109, 112, 120])
    fake_time = SimpleNamespace(monotonic=clock.monotonic)
    monkeypatch.setattr(server, "time", fake_time)

    readings = iter([
        _silent_scale(),
        SimpleNamespace(weight=36.0, battery_pct=80),
        _silent_scale(),
        _silent_scale(),
        _silent_scale(),
        _silent_scale(),
    ])

    def _scale_state():
        return next(readings, _silent_scale())

    monkeypatch.setattr(server, "get_scale_status", _scale_state)

    asyncio.run(
        _run_briefly(lambda: server.collect_scale_data_task(brew.id, 0.001))
    )

    assert brew.status == BrewState.ERROR
    # Exactly one trip: the guard must stay latched (status ERROR) instead of
    # re-triggering on every subsequent silent tick.
    valve.return_to_start.assert_called_once()


def test_zero_threshold_disables_the_guard(server, monkeypatch):
    """0 is documented as 'guard disabled', not 'trip instantly'."""
    brew = _brewing()
    monkeypatch.setattr(server, "cur_brew", brew)
    monkeypatch.setattr(server, "get_scale_status", lambda: _silent_scale())
    valve = MagicMock()
    monkeypatch.setattr(server, "valve", valve)
    monkeypatch.setattr(server, "BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS", 0)

    asyncio.run(
        _run_briefly(lambda: server.collect_scale_data_task(brew.id, 0.02))
    )

    assert brew.status == BrewState.BREWING
    valve.return_to_start.assert_not_called()


def test_silence_during_a_pause_does_not_fail_the_brew(server, monkeypatch):
    """Paused brews are not pouring; the guard only protects active pours."""
    brew = _brewing()
    brew.status = BrewState.PAUSED
    monkeypatch.setattr(server, "cur_brew", brew)
    monkeypatch.setattr(server, "get_scale_status", lambda: _silent_scale())
    valve = MagicMock()
    monkeypatch.setattr(server, "valve", valve)
    monkeypatch.setattr(server, "BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS", 0)

    asyncio.run(
        _run_briefly(lambda: server.collect_scale_data_task(brew.id, 0.02))
    )

    assert brew.status == BrewState.PAUSED
    valve.return_to_start.assert_not_called()
