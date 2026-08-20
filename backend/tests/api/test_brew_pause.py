"""
Pause must actually pause.

Both background tasks used to write `cur_brew.status = BrewState.BREWING`
unconditionally after a successful step -- the scale loop runs while PAUSED (so
the weight series has no gap), and the step loop has awaits during which a pause
can land. Either one silently resumed a paused brew, after which the valve kept
being driven.

These drive the task coroutines directly. Going through TestClient does not
reproduce it: the background tasks are not scheduled reliably between requests,
so such a test passes even with the bug reinstated.
"""

import asyncio
from datetime import datetime, timezone

import pytest

from brewctl.core.model import Brew, BrewState, BrewStrategyType, ValveCommand


@pytest.fixture
def server(client):
    """`client` is what imports api.server under the HttpValve/HttpScale patches."""
    import brewctl.api.server as server_module

    return server_module


def _paused_brew():
    return Brew(
        id="test-brew",
        status=BrewState.PAUSED,
        time_started=datetime.now(timezone.utc),
        target_weight=1000,
        vessel_weight=200,
        strategy=BrewStrategyType.DEFAULT,
    )


async def _run_briefly(coro_fn, seconds=0.05):
    task = asyncio.create_task(coro_fn())
    await asyncio.sleep(seconds)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_scale_loop_does_not_resume_a_paused_brew(server, monkeypatch):
    brew = _paused_brew()
    monkeypatch.setattr(server, "cur_brew", brew)

    asyncio.run(
        _run_briefly(lambda: server.collect_scale_data_task(brew.id, 0.001))
    )

    assert brew.status == BrewState.PAUSED


def test_scale_loop_still_recovers_from_error(server, monkeypatch):
    """The ERROR -> BREWING recovery this code exists for must still work."""
    brew = _paused_brew()
    brew.status = BrewState.ERROR
    monkeypatch.setattr(server, "cur_brew", brew)

    asyncio.run(
        _run_briefly(lambda: server.collect_scale_data_task(brew.id, 0.001))
    )

    assert brew.status == BrewState.BREWING


def test_step_loop_does_not_resume_a_paused_brew(server, monkeypatch):
    """
    A pause landing during brew_step_task's awaits must survive the assignment
    that follows them.
    """
    brew = _paused_brew()
    brew.status = BrewState.BREWING
    monkeypatch.setattr(server, "cur_brew", brew)

    class PausingStrategy:
        """Pauses the brew mid-step, mimicking a request arriving during an await."""

        valve_interval = 0.001

        def step(self, flow_rate, weight):
            brew.status = BrewState.PAUSED
            return (ValveCommand.FORWARD, 0.001)

    asyncio.run(
        _run_briefly(lambda: server.brew_step_task(brew.id, PausingStrategy()))
    )

    assert brew.status == BrewState.PAUSED
