# 8. Small wins

Independent, individually small changes. Each is a few hours at most. Roughly ordered by value.

---

## 8.1 Auto-tare / vessel weight detection

`StartBrewRequest.vessel_weight` is typed by hand every brew in `StartBrew.tsx`, and getting it
wrong silently corrupts the target — the brew stops at the wrong point.

The scale already knows. Add `GET /api/scale` (it exists) usage to the start form: read the current
weight when the form opens, prefill `vessel_weight`, show it as "measured: 412 g" with an override.
Optionally a "tare" button that calls the scale's tare, if `AbstractScale` gains one —
`LunarScale.py` should be checked for whether pyacaia exposes tare.

Guard: if the scale is disconnected or reads zero, fall back to the config default and say so.

---

## 8.2 Prometheus metrics

Add `GET /metrics` to both services via `prometheus-client`. Almost all the values already exist as
local variables; they just are not exported.

Api service:

- `brewctl_flow_rate_grams_per_second{brew_id}` gauge
- `brewctl_flow_rate_error` gauge — the single most useful line on a dashboard
- `brewctl_valve_position` gauge
- `brewctl_valve_commands_total{command}` counter
- `brewctl_brews_total{outcome}` counter
- `brewctl_scale_data_age_seconds` gauge (see spec #5)
- `brewctl_influx_write_failures_total` counter

Hardware service:

- `brewctl_watchdog_trips_total` counter
- `brewctl_scale_connected` gauge
- `brewctl_sse_clients` gauge

Pairs well with the InfluxDB instance already in the stack. Cheap, and it makes every other spec
here easier to evaluate after the fact.

---

## 8.3 Accelerated dry-run mode

`MockScale` and `MockValve` exist and are used throughout the tests, but there is no way to exercise
a full brew from the UI without real hardware and real hours.

Add a dry-run flag on `StartBrewRequest`: use mocks regardless of `BREWCTL_IS_PROD`, and apply a
time-scale factor to every sleep interval in the brew loop (`sleep_with_heartbeat` is the single
choke point, so this is a one-line multiplier). A `MockScale` that increases weight according to
valve position — rather than returning a fixed value — makes the whole loop behave plausibly.

Value: demoing the UI, reproducing bugs, testing the frontend against a moving brew, and validating
strategy changes end to end in seconds. Overlaps with spec #2 but is far cheaper and stands alone.

Keep the brew record flagged as a dry run (spec #1) so simulated brews never pollute the history
statistics.

---

## 8.4 Live strategy switching

Currently changing strategy means stopping and restarting the brew, which returns the valve to
start and throws away the operating point.

`AbstractBrewStrategy.step()` is stateless in its signature — state lives inside the instance. So
`POST /api/brew/strategy { strategy, strategy_params }` can construct a new strategy and swap the
reference the brew task holds. Caveats:

- The new strategy starts with no internal state — a PID integrator at zero, a Kalman filter
  unconverged. Seed what can be seeded: current valve position as the operating point, current flow
  rate as the initial estimate. Add an optional `warm_start(valve_position, flow_rate)` hook to
  `AbstractBrewStrategy` with a no-op default.
- Record the switch on the brew record, otherwise the quality score attributes the whole brew to
  whichever strategy happened to be last.

Genuinely useful with the simulator (#2): find a better strategy mid-brew and apply it without
losing the batch.

---

## 8.5 Env prefix cleanup

`frontend/vite.config.ts` sets `envPrefix: 'COLDBREW_FRONTEND_API_URL'` and the frontend reads
`import.meta.env.COLDBREW_FRONTEND_API_URL`, while compose and the Makefile pass
`BREWCTL_FRONTEND_API_URL`. Legacy `COLDBREW_*` naming survives in a few build paths. Documented as
a gotcha in `CLAUDE.md`, which is not the same as fixed.

`vite.config.ts` is already modified on this branch, so this is the moment. Standardise on
`BREWCTL_` everywhere, delete the `COLDBREW_` references, and update `vite-env.d.ts`.

While in there: `brew/constants.ts` derives the SSE and WebSocket URLs by string-rewriting the API
URL. Replace with an explicit URL builder — spec #6 needs to append query parameters to those URLs
and string rewriting will not survive that.

---

## 8.6 Documentation debt

- `README.md` predates the api/hardware split: file paths (`brewctl/server.py`, `brewctl/pi/`) and
  the endpoint table are stale. Regenerate the endpoint table from the FastAPI OpenAPI schema so it
  cannot drift again.
- `make build-prod-image` references `unified-docker-compose.yml`, which is no longer in the tree.
  Either restore the target against the current compose files or delete it.
- The old `requirements/backend.txt` and `pi.txt` are deleted on this branch in favour of
  `api.txt` / `hardware.txt` / `dev.txt`; make sure `CLAUDE.md`'s gotcha section, which still names
  `requirements/pi.txt`, is updated when this branch merges.

---

## 8.7 Retire the WebSocket endpoints

`/ws/brew/status` and `/ws/health` still exist alongside the SSE endpoints that replaced them, and
`websockets` is pinned in `api.txt` specifically to serve them. Nothing in the frontend uses them.
Confirm no external consumer, then delete both endpoints and the pin — the api service is running a
Pi-adjacent stack where a dependency that serves nothing is worth removing.
