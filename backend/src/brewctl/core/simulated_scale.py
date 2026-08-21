"""A scale whose weight responds to the valve, for dry-run brews.

`MockScale` adds a random increment on a background thread regardless of what the
valve is doing, so a brew loop driven by it never reacts to its own commands --
fine for unit tests, useless for exercising a strategy end to end.

This one derives weight from valve position, and does it lazily on read rather
than on a timer: a dry run compresses the brew loop's sleeps by `time_scale`, and
a thread ticking in wall-clock time would fall out of step with it.
"""

import random
import time

from brewctl.core.log import logger
from brewctl.core.scale import AbstractScale
from brewctl.core.valve import AbstractValve

# Valve steps from closed to fully open. MockValve counts raw steps with no upper
# bound, so this is what "fully open" means for the flow model, not a hardware limit.
MAX_OPEN_STEPS = 40

# Flow with the valve fully open, grams/second. A 1337 g target at ~0.05 g/s (the
# configured default flow rate) is a multi-hour brew, which is the point of the
# time scaling.
MAX_FLOW_GPS = 0.15

# Fraction of the current flow added as read-to-read noise, so flow-rate
# calculations see something less than a perfect ramp.
NOISE_FRACTION = 0.05


class SimulatedScale(AbstractScale):
    """Weight accumulates at a rate set by how far open the valve is."""

    def __init__(self, valve: AbstractValve, time_scale: float = 1.0):
        self._valve = valve
        self._time_scale = max(time_scale, 1.0)
        self._connected = False
        self._weight = 0.0
        self._units = "grams"
        self._battery_percentage = 100
        self._last_read = time.monotonic()

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self):
        logger.info(
            f"[Simulated] Scale connecting (time_scale={self._time_scale}x)."
        )
        self._connected = True
        self._last_read = time.monotonic()

    def disconnect(self):
        logger.info("[Simulated] Scale resetting weight, disconnecting.")
        self._connected = False
        self._weight = 0.0

    def flow_for_position(self, position: int) -> float:
        """Grams/second at a given valve position, in simulated time."""
        # Clamp the raw position: MockValve.step_backward can drive it negative,
        # and its get_position() takes a modulo, which would wrap a
        # nudged-closed valve around to wide open.
        open_steps = min(max(position, 0), MAX_OPEN_STEPS)
        return (open_steps / MAX_OPEN_STEPS) * MAX_FLOW_GPS

    def get_weight(self) -> float:
        now = time.monotonic()
        elapsed = now - self._last_read
        self._last_read = now

        # A disconnected scale reads whatever disconnect() left, and does not
        # keep filling: the brew loop calls disconnect() when a brew completes,
        # and a weight that carried on climbing afterwards would look like a leak.
        if not self._connected:
            return self._weight

        position = getattr(self._valve, "position", self._valve.get_position())
        flow = self.flow_for_position(position)
        delta = elapsed * self._time_scale * flow
        if delta > 0:
            delta += delta * random.uniform(-NOISE_FRACTION, NOISE_FRACTION)
        self._weight += delta
        return self._weight

    def get_units(self) -> str:
        return self._units

    def get_battery_percentage(self) -> int:
        return self._battery_percentage
