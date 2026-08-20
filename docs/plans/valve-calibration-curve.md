# 3. Valve calibration curve and feedforward control

## Problem

`AbstractValve` (in `backend/src/brewctl/core/valve.py`) exposes `step_forward`, `step_backward`,
`return_to_start`, and `get_position` — 200 steps per revolution. Strategies emit `ValveCommand`
values (`FORWARD`, `BACKWARD`, `NOOP`, `STOP`) and nothing anywhere knows what flow rate a given
position produces.

That means every strategy is a pure integrator hunting blind for the operating point. At brew
start it has no idea whether the answer is step 5 or step 60, so it walks there one step at a time
while the flow error stays large. The Smith predictor and the adaptive gain scheduler exist in part
to compensate for that hunting — but the cheapest fix is to know the answer in advance.

## Design

### Calibration routine

A new endpoint that runs a staircase test and records the result:

1. Return the valve to start, then confirm zero flow.
2. Step to position *p*, wait `settle_seconds` (long enough to clear dead time plus a few time
   constants — start at 30s), then measure mean flow over `measure_seconds` (say 20s) from the
   scale.
3. Repeat for a position sweep. Coarse first (every 10 steps until flow exceeds some multiple of
   the target), then a fine pass around the region that brackets typical target flow rates.
4. Store the (position, flow) pairs plus water temperature and reservoir level if available.

The whole run takes tens of minutes and consumes a vessel of water, so it is a deliberate,
user-triggered operation with a progress stream — not something that runs automatically.

Important: flow at a given position depends on head pressure, so a curve measured with a full
reservoir does not hold at the end of a brew. Record the reservoir weight alongside each point and
either (a) fit a two-variable surface `flow(position, head)`, or (b) calibrate at one reference
level and treat head as a correction factor. Start with (b); (a) is a refinement once there is data.

### Storage

Table `calibrations`: id, device_id (for spec #6), created_at, points JSON, fitted coefficients,
reference head weight, notes, and an `active` flag. Keep history — comparing today's curve against
last month's is how a clog gets detected.

### Fit

A monotone piecewise-linear interpolation over the measured points is enough and is robust; avoid
polynomial fits, which will oscillate. Expose both directions:

```
flow_at(position, head) -> float
position_for(target_flow, head) -> int      # inverse, via the same interpolation
```

Reject non-monotone data at fit time with a clear error — that means the test was disturbed and the
run should be repeated.

### Use in control

Add feedforward to the base strategy machinery. At brew start, seed the valve at
`position_for(target_flow_rate, current_head)` in one move rather than stepping from zero. The
strategies then only correct the residual, which is exactly the regime PID gains are easy to tune
for. The `step()` signature does not need to change — the seeding happens in `brew_step_task`
before the loop, and periodic head-based re-seeding can be folded in as a bias term.

Optionally extend the interface with a `step_to(position)` on `AbstractValve` so the seek is one
call rather than N `step_forward` calls over the network. `MotorKitValve` can implement it as a
tight local loop, which is much faster and puts less traffic through the watchdog path.

### Clog and drift detection

Once a curve exists, the system can compare observed flow against `flow_at(position, head)` during
a brew. A sustained shortfall beyond some tolerance means a partial clog, a scale problem, or an
empty reservoir. Surface it as a `BrewErrorResponse` with category `HARDWARE`, severity `WARNING`,
and a recovery suggestion — the model classes for this already exist in `core/model.py` and are
underused.

## API

```
POST /api/calibration/start   { device_id?, positions?, settle_seconds, measure_seconds }
GET  /sse/calibration/status  progress stream: current position, flow so far, points collected
POST /api/calibration/abort
GET  /api/calibration         list
GET  /api/calibration/active
POST /api/calibration/{id}/activate
```

Calibration must take the same exclusion lock as a brew — the "a brew is already in progress"
check in `start_brew` needs to become a general "the hardware is busy" check.

## Files touched

- `backend/src/brewctl/core/valve.py` — optional `step_to`, default implemented via repeated steps
- `backend/src/brewctl/hardware/MotorKitValve.py` — native `step_to`
- `backend/src/brewctl/api/http_valve.py` — proxy `step_to`
- `backend/src/brewctl/hardware/server.py` — `POST /api/valve/step_to`; must feed the watchdog
- new `backend/src/brewctl/api/calibration.py` — routine, fit, lookup
- `backend/src/brewctl/api/server.py` — feedforward seeding in `brew_step_task`, busy lock
- new `frontend/src/components/calibration/` — run the routine, plot the curve, compare runs

## Testing

- Fit and inverse round-trip on synthetic monotone data.
- Non-monotone input is rejected.
- Calibration routine driven end to end against `MockScale`/`MockValve` with a synthetic plant
  (reuse the model from spec #2) and short settle times.
- A brew with a calibration active reaches target flow in measurably fewer steps than without —
  assert on step count, using the simulator.

## Open questions

- Is the valve's mechanical zero repeatable across power cycles? `return_to_start` assumes yes.
  If it is not, calibration is meaningless between sessions and a homing switch is needed first.
  **Verify this on the hardware before building anything else here.**
- Water temperature affects viscosity and therefore flow. Probably second-order for cold brew, but
  record it if a sensor is ever available.

## Depends on

Nothing hard. Pairs naturally with #2 (the curve is the simulator's plant) and #1 (somewhere to
store curves).
