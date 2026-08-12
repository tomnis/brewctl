# 2. Strategy replay and simulation

## Problem

There are six strategies in `backend/src/brewctl/api/strategies/` — default, PID, Kalman+PID,
Smith predictor, adaptive gain scheduling, and MPC. The only way to compare them is to run a real
brew, which takes hours and a vessel of coffee. So the tuning loop is: guess gains, wait, guess
again. Nobody does that more than twice, which means the advanced strategies are largely untested
against the simple ones.

`tests/api/test_advanced_strategies.py` already drives `strategy.step()` directly. The gap between
that and a usable simulator is a plant model and a scoring harness.

## Design

Two tiers. Build tier 1 first; it is cheap and immediately useful.

### Tier 1 — trace replay

Take a recorded brew (weight series from InfluxDB, or from the history table once spec #1 lands)
and replay the *observed flow rate sequence* through a strategy, ignoring the strategy's valve
commands. This does not simulate control — it answers a narrower question: given the same
disturbances, what would this strategy have commanded, and how jumpy is it? Useful for spotting
strategies that thrash the valve or wind up their integrator, without needing any plant model.

Output: command sequence, valve position trace, and the existing `brew_quality` metrics computed
against the replayed flow.

### Tier 2 — closed-loop simulation

Needs a plant model: valve position to flow rate, plus dynamics.

```
flow_ss(position)      steady-state flow at a given valve position (from spec #3's calibration curve)
tau                    first-order time constant of the flow response
dead_time              transport delay between valve move and flow change at the scale
noise_sigma            scale noise, g
drift                  slow flow decline as head pressure drops with vessel level
```

Model:

```
flow(t) = first_order(flow_ss(position(t - dead_time)), tau) + N(0, noise_sigma) + drift(weight)
weight(t+dt) = weight(t) + flow(t) * dt
```

Fit `flow_ss`, `tau`, and `dead_time` from recorded brews by least squares; ship a hand-tuned
default set so the simulator works before any calibration data exists. Head-pressure drift matters
for cold brew specifically — flow falls off as the reservoir empties, and that is exactly the
disturbance the adaptive and MPC strategies claim to handle.

The simulation loop mirrors `brew_step_task` in `api/server.py`: call `strategy.step(flow_rate,
current_weight)`, apply the returned `ValveCommand` to the model position, advance simulated time
by the returned interval. Run in virtual time — no `asyncio.sleep`, so an eight-hour brew
simulates in milliseconds.

Care is needed to keep the simulated loop honest: it must feed the strategy a flow rate derived
the same way the real system does (windowed derivative over the `WeightBuffer`), not the model's
true instantaneous flow. Otherwise the simulator hands the strategy a cleaner signal than reality
and every strategy looks good.

### API

```
POST /api/simulate
  { strategy, strategy_params, base_params, plant?, duration_limit_seconds? }
  -> { trace: [{t, weight, flow_rate, valve_position, command}], quality: BrewQualityMetrics }

POST /api/simulate/compare
  { strategies: [{strategy, strategy_params}], base_params, plant?, seed }
  -> [{ strategy, quality, trace }]

POST /api/simulate/fit-plant
  { brew_ids: [...] }  -> plant parameters + fit residual
```

`compare` runs every strategy against the same seeded noise sequence, which is the whole point —
comparing across different random draws is meaningless at these signal-to-noise ratios.

### Frontend

A "Simulate" tab: pick strategies, tweak parameters, run, see traces overlaid with the target flow
line and the resulting scores in a table. This turns strategy tuning from a multi-hour physical
experiment into an interactive one.

Also worth surfacing on the live brew view: run the simulator with current parameters at brew start
and draw the predicted trace as a ghost line behind the live one. Divergence between predicted and
actual is a good early signal of a clog or a scale problem.

## Files touched

- new `backend/src/brewctl/api/simulation/plant.py` — the model and its fitting
- new `backend/src/brewctl/api/simulation/runner.py` — virtual-time loop
- new `backend/src/brewctl/api/routes/simulate.py`
- `backend/src/brewctl/api/server.py` — factor the step/apply logic out of `brew_step_task` so the
  simulator and the real loop share one implementation rather than drifting apart. This is the
  riskiest part of the change and should be done as its own commit with the existing brew tests
  green before and after.
- new `frontend/src/components/simulate/`

## Testing

- Plant model unit tests: step response reaches steady state, dead time delays it correctly.
- Determinism: same seed, same trace, byte for byte.
- Regression harness: a scored run of all six strategies against a fixed plant and seed, with the
  scores committed as a baseline. A strategy edit that drops the score fails CI. This is the real
  payoff — it makes strategy work testable.

## Open questions

- Should the plant model live in the api service or a separate offline tool? In the api service, so
  the frontend can use it and so plant fitting can read the history database directly.
- MPC in particular may be slow enough that a long simulated brew is not instant. Measure before
  optimising; virtual time already removes the dominant cost.

## Depends on

Better with #1 (history) for real traces to replay and fit against, and #3 (calibration) for a
grounded `flow_ss`. Tier 1 needs neither and can start now against raw InfluxDB queries.
