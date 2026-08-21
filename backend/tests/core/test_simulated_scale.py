import time

from brewctl.core.simulated_scale import MAX_FLOW_GPS, MAX_OPEN_STEPS, SimulatedScale
from brewctl.core.valve import MockValve


def make_scale(time_scale=1.0):
    valve = MockValve()
    scale = SimulatedScale(valve, time_scale=time_scale)
    scale.connect()
    return valve, scale


def test_closed_valve_produces_no_weight():
    _, scale = make_scale()
    scale.get_weight()
    time.sleep(0.05)
    assert scale.get_weight() == 0.0


def test_weight_rises_while_valve_is_open():
    valve, scale = make_scale(time_scale=1000.0)
    for _ in range(MAX_OPEN_STEPS):
        valve.step_forward()

    scale.get_weight()
    time.sleep(0.05)
    assert scale.get_weight() > 0.0


def test_flow_scales_with_valve_position():
    _, scale = make_scale()
    assert scale.flow_for_position(0) == 0.0
    assert scale.flow_for_position(MAX_OPEN_STEPS) == MAX_FLOW_GPS
    half = scale.flow_for_position(MAX_OPEN_STEPS // 2)
    assert 0 < half < MAX_FLOW_GPS


def test_position_is_clamped_at_both_ends():
    _, scale = make_scale()
    # MockValve.step_backward drives position negative, and its get_position()
    # takes a modulo -- a nudged-closed valve must not wrap around to wide open.
    assert scale.flow_for_position(-5) == 0.0
    assert scale.flow_for_position(MAX_OPEN_STEPS * 10) == MAX_FLOW_GPS


def test_time_scale_multiplies_accumulated_weight():
    slow_valve, slow = make_scale(time_scale=1.0)
    fast_valve, fast = make_scale(time_scale=100.0)
    for _ in range(MAX_OPEN_STEPS):
        slow_valve.step_forward()
        fast_valve.step_forward()

    slow.get_weight()
    fast.get_weight()
    time.sleep(0.05)
    # Noise is a few percent, so 100x separates the two well clear of it.
    assert fast.get_weight() > slow.get_weight() * 10


def test_time_scale_never_slows_below_real_time():
    _, scale = make_scale(time_scale=0.1)
    assert scale._time_scale == 1.0


def test_disconnect_resets_weight():
    valve, scale = make_scale(time_scale=1000.0)
    for _ in range(MAX_OPEN_STEPS):
        valve.step_forward()
    scale.get_weight()
    time.sleep(0.05)
    scale.get_weight()

    scale.disconnect()
    assert scale.connected is False
    assert scale.get_weight() == 0.0
