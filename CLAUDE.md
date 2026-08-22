# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make dev              # docker compose build && up — hardware:8001, api:8000, frontend:5173
make prod-local       # the production image + mock hardware; UI at :8000/app
make test             # backend + frontend
make testBackend      # cd backend && pytest tests
make testFrontend     # cd frontend && npm run test:run
make lint             # cd frontend && npm run lint (no backend linter is wired up)
make build-prod-image # docker build -t brewctl-api:local .
make deploy-device    # git push coldbrewer <branch> — the ONLY way the Pi updates
make deploy-control   # deploy/control/apply.sh applies deploy/control/app.yaml to TrueNAS
```

Single test / focused runs:

```bash
cd backend && pytest tests/api/test_server.py::test_name     # pytest.ini sets pythonpath=src, testpaths=tests
cd backend && pytest tests/hardware -k watchdog
cd frontend && npx vitest run src/components/brew/validators.test.ts
cd frontend && npm run build                                 # tsc -b + vite build
```

Running a service outside Docker (from `backend/`, with `PYTHONPATH=src`):

```bash
BREWCTL_MODE=api      fastapi dev src/brewctl/main.py --port 8000
BREWCTL_MODE=hardware fastapi dev src/brewctl/main.py --port 8001
```

## Architecture

Two FastAPI apps from one Python package plus a React/Vite frontend. `brewctl/main.py` is the single
entrypoint: it reads `BREWCTL_MODE` (`api` | `hardware`) and imports the corresponding `app`.

**Production is split across two hosts.** Deploy manifests are named for the *role* each host
plays, not the box it currently is: `deploy/device/` and `deploy/control/`. That is a separate
vocabulary from `BREWCTL_MODE` — **device** runs mode `hardware`, **control** runs mode `api`
plus the bundled frontend. The device service runs *bare metal* on `coldbrewer.local` (Pi Zero
2 W, arm64, 416 MB RAM, **no Docker**) under systemd. Control runs in Docker as a TrueNAS custom
app on `catacombs` and serves the built frontend at `/app`, so the UI is same-origin with the
API. Locally, `docker-compose.yml` still runs all three from `backend/Dockerfile` with the
hardware service in mock mode.

Requirements are split per deployment target: `base.txt` (shared) → `hardware.txt` (Pi devices:
pyacaia/bluepy, Adafruit MotorKit) and `api.txt` (influxdb-client, httpx); `dev.txt` is api + pytest
and deliberately excludes `hardware.txt`, whose `bluepy`/`RPi.GPIO` will not build off-Pi.

- **`brewctl/core/`** — shared across both modes: `model.py` (Pydantic/enums: `BrewState`,
  `ValveCommand`, `BrewStrategyType`, `Brew`, `BrewStatus`), `config.py` (shared env vars),
  `scale.py` / `valve.py` (`AbstractScale`, `AbstractValve` + `MockScale`, `MockValve`),
  `contract.py` (api↔hardware wire version), `secrets.py`, `log.py`.
- **`brewctl/hardware/`** — runs on the Pi, owns the physical devices. `create_scale()` /
  `create_valve()` pick `LunarScale`/`MotorKitValve` when `BREWCTL_IS_PROD=true`, mocks otherwise.
  Exposes `/api/valve/*`, `/api/scale/*`, `/health` (no `/api` prefix here, unlike the api service)
  and SSE streams `/sse/valve/status`, `/sse/scale/status`. Has a watchdog (deadman switch) with a
  **two-tier derived timeout** — see `effective_watchdog_timeout()`:

  ```
  effective = WATCHDOG_TIMEOUT_SECONDS   (10s)  if a heartbeat arrived within BACKSTOP
              WATCHDOG_BACKSTOP_SECONDS  (300s) otherwise
  ```

  Valve command endpoints and `POST /api/valve/heartbeat` call `feed_watchdog()`; only the
  heartbeat also calls `record_heartbeat()`. Unrelated traffic (`/health`, SSE,
  `/api/valve/status`) deliberately does *not* feed it. The two tiers exist because the api
  may be older than the hardware: an api without heartbeats only contacts the Pi when it
  moves the valve (up to `BREWCTL_VALVE_INTERVAL_SECONDS`, 90s apart), and holding it to the
  10s timer would close the valve ~10s into every brew. There is no armed/disarmed flag —
  the valve is never unguarded, which is why "arm on first heartbeat" was rejected (a valve
  nudged open from the UI never produces one).

  `api/server.py`'s `sleep_with_heartbeat()` chunks every brew-loop sleep and pings
  `valve.heartbeat()` every `HEARTBEAT_INTERVAL_SECONDS` (3s) — a plain `asyncio.sleep` in
  the brew loop drops the valve to the slow tier.
- **`brewctl/api/`** — business logic, no direct hardware access. `HttpScale`/`HttpValve` implement
  the core abstract interfaces by *subscribing to the hardware service's SSE streams on a background
  thread* and caching values; `connect()` starts the listener, reads are served from cache. Writes
  weight to InfluxDB (`time_series.py`) and serves the frontend.

### Brew execution

`POST /api/brew/start` sets the module-global `cur_brew: Brew | None` in `api/server.py` and spawns
two asyncio tasks, each looping while `brew_id == cur_brew.id` (that comparison is how stop/kill
terminates them — setting `cur_brew = None` or a new id ends the loop):

- `collect_scale_data_task` — every `scale_interval` (0.5s): read scale → `time_series.write_scale_data()`
  and `weight_buffer.add_reading()`.
- `brew_step_task` — computes flow rate from the in-process `WeightBuffer` when it `is_ready()` and
  not `is_stale()` (2s), otherwise falls back to InfluxDB derivative queries; calls `strategy.step()`
  and applies the returned `ValveCommand` + sleep interval. `STOP` completes the brew, returns the
  valve to start, and releases it.

State is global mutable module state, not a session store — one brew at a time. Tests reset it via
the `client`/`reset_globals` fixtures in `backend/tests/api/conftest.py`.

### Dry-run brews

`POST /api/brew/start` with `dry_run: true` runs a brew against simulated hardware regardless of
`BREWCTL_IS_PROD`, on a clock compressed by `time_scale` (default 60x). Three pieces have to agree:

- `api/server.py` swaps the module globals `scale`/`valve` for `SimulatedScale` + `MockValve` and
  sets `_time_scale`. `_restore_hardware()` hands them back and **must** run on every exit path
  (completion, stop, kill, the already-brewing 409) — a leaked dry run would leave the next *real*
  brew driving a mock while reporting healthy. The hardware version check is skipped for dry runs;
  `MockValve` has no `hardware_api_version`, so `check_hardware_compatibility()` would 409 them all.
- `core/simulated_scale.py` derives weight from valve position (`flow_for_position()`), lazily on
  read rather than on a thread, and fills `_time_scale` times faster.
- `sleep_with_heartbeat()` divides by `_time_scale`, and `_simulated_flow()` divides *measured* flow
  by it. Both are needed: `WeightBuffer` measures in wall-clock seconds, so without the second one
  the strategy sees 60x its target and shuts the valve on the first step.

Sim points are tagged `dry_run="true"` in InfluxDB. The "real" predicate is
`(not exists r.dry_run or r.dry_run == "false")` — points written before this feature carry no tag,
so a bare `== "false"` would hide all pre-existing history (`api/time_series.py:dry_run_filter`).

### Live strategy switching

`POST /api/brew/strategy` swaps the running brew's strategy in place — the valve stays where it is,
which is the whole point (stop/start returns it to start and discards the operating point). Three
module globals in `api/server.py` back it:

- `cur_strategy` — the loop re-reads it every iteration, so `brew_step_task` takes no `strategy`
  parameter. Tests that drive the loop must set the global, not pass an argument.
- `cur_base_params` — `target_flow_rate` / `valve_interval` / `scale_interval` / `epsilon` come from
  `StartBrewRequest` and are **not** stored on `Brew`, so without this a swapped-in strategy would
  silently fall back to config defaults and brew to a different target.
- `strategy_switch_event` — cuts short the in-flight `sleep_with_heartbeat` (up to 90s). It is
  created inside `brew_step_task`, not `start_brew`: an `asyncio.Event` waiter is only woken by a
  `set()` on its own loop, and tests run the task under their own `asyncio.run`.

**The event is cleared at the top of the brew loop, never inside `sleep_with_heartbeat`.** A switch
usually lands while the loop is in `strategy.step()` or a valve call, not while sleeping; clearing on
the wake path would leave it set, and the next sleep would return instantly — two valve commands back
to back instead of a `valve_interval` apart. `STRATEGY_SWITCH_MIN_INTERVAL_SECONDS` (429) is the
hard bound on that. `AbstractBrewStrategy.warm_start(valve_position, flow_rate)` seeds the new
instance (no-op by default); `prev_timestamp` is the field that matters, since a constructor-era one
yields a huge first `dt`. A swapped-in strategy's `scale_interval` is inert — `collect_scale_data_task`
is not restarted.

### Strategies

`AbstractBrewStrategy.step(flow_rate, current_weight) -> (ValveCommand, interval_seconds)`. Concrete
strategies live in `api/strategies/` (one class per file, `PascalCase.py`) and self-register into
`BREW_STRATEGY_REGISTRY` via the `@register_strategy(BrewStrategyType.X)` decorator;
`create_brew_strategy()` builds them through `from_params(strategy_params, base_params)`. The
registry and base class themselves live in `strategies/DefaultBrewStrategy.py`.
`api/brew_strategy.py` is a re-export shim — importing it is what triggers registration of every
strategy, so import from there rather than from the submodules.

`step()` is **not** called on the event loop. `brew_step_task` routes it through
`run_step_with_heartbeat()`, which runs it via `asyncio.to_thread` while a ticker feeds the hardware
watchdog -- otherwise an `AIBrewStrategy` blocking on an LLM call would freeze the whole api process
and let the watchdog close the valve mid-step. Two consequences: `step()` must be sync and must not
touch the running loop (`asyncio.get_running_loop()` raises in there), and because the call can now
take seconds, `brew_step_task` re-checks `cur_brew.id` and `strategy_switch_event` after it returns
and discards the command if the brew ended or the strategy changed meanwhile.

Adding a strategy touches four places, all of which must agree:

1. `BrewStrategyType` in `core/model.py` (the enum *value* is the wire id).
2. The new class file in `api/strategies/` with `@register_strategy(...)`.
3. `api/strategies/__init__.py` **and** `api/brew_strategy.py` re-exports.
4. The `STRATEGIES` array in `frontend/src/components/brew/constants.ts`, whose `StrategyType`
   union must match the enum values; each `params` entry becomes a form field posted as
   `strategy_params`.

### Frontend

React 18 + Chakra UI v3 + Vite + Recharts. Real-time updates come from SSE (`useBrewStatus`
subscribes to `/sse/brew/status`, `useConnectionStatus` to `/sse/health`). The older
`/ws/brew/status` and `/ws/health` endpoints were removed; the `BREWCTL_WS_*_PUSH_INTERVAL` env
vars survive under those names and now pace the SSE streams. All service URLs are built by
`serviceUrl(path, params?)` in `components/brew/constants.ts`, which strips the trailing `/api`
segment off the API URL with the `URL` API and appends query parameters — add new endpoints through
it rather than by string-rewriting `apiUrl`.

### CI/CD (Forgejo, `.forgejo/workflows/`)

**Building is not deploying.** `build.yml` runs tests, builds the root `Dockerfile`, smoke-tests the
image (`/api/health` and `/app/`), and streams it onto the control host with `docker save | ssh docker load`
— there is no registry, so the deployed reference is a registry-less local tag
(`catacombs/brewctl:sha-<short12>`). Every branch publishes an image; it just sits on the daemon.

The manifest is split in two: `deploy/control/app.yaml` is the *shape* of the deployment and carries an
`@IMAGE@` placeholder, while `deploy/control/image.tag` holds the one pinned reference and is the whole
promotion. `apply.sh` substitutes one into the other before the PUT and refuses to apply if `@IMAGE@`
survives or the tag is still `REPLACE_ME`; `--render` prints the result without touching the network,
and `--image REF` overrides the file for an emergency rollback (leaving the box diverged from git).

`deploy.yml` runs only on master pushes touching `deploy/control/{image.tag,app.yaml,apply.sh}`;
`build.yml` has a matching `paths-ignore: deploy/**`, so a promotion does not also rebuild. So
**deploying is a one-line commit to `image.tag`**, and rollback is `git revert` (valid while the old
image is still loaded). `apply.sh` refuses to redeploy while a brew is active, and fails open if the
api is unreachable.

Forgejo is the CI origin — push directly to the `forgejo` remote; a pull mirror from GitHub would
not trigger runs.

## Gotchas

- **`BREWCTL_IS_PROD` failing silently is the worst failure mode in this repo.** Anything other than
  the exact string `true` makes the hardware service run `MockScale`/`MockValve`: it starts cleanly,
  `/health` reports healthy, and no physical device moves. After any config change on the Pi, check
  `journalctl -u brewctl-hardware | grep -iE 'production|mock'`.
- **A `connected` scale is not a working scale.** pyacaia sets `connected` when the BLE
  notification subscription is set up -- before any weight packet arrives -- and never clears it if
  the thread pumping notifications dies. `AcaiaScale.weight` starts `None` and is only ever set by a
  packet, so `connected=True` + `weight=None` is a sticky state that used to persist until the
  hardware service restarted. `AbstractScale` therefore tracks `note_weight()` /
  `is_weight_stale()` / `healthy()`, `scale_monitor()` in `hardware/server.py` reconnects a scale
  that fails that check (rebuilding the `AcaiaScale` is what re-sends the one-shot notification
  request), and it is also the only thing that connects the scale at startup. Staleness is judged
  **only on the Pi** -- `HttpScale` mirrors the `healthy` field off SSE rather than computing its
  own, since a freshly built `HttpScale` has never seen a reading and would look identical to a dead
  scale. `start_brew` 409s `scale_unhealthy` on an explicit `False`; `None` (a v1 Pi, or a dry run's
  `SimulatedScale`) means unknown and allows the brew. `LunarScale.disconnect()` must not null
  `self.scale` -- it did, and every later read raised `AttributeError` instead of reporting a
  disconnected scale, leaving nothing able to drive recovery.

- **The Pi never self-updates.** It changes only when someone runs `make deploy-device` (a push to the
  `coldbrewer` remote, whose `post-receive` hook runs `deploy/device/install.sh --deps-only` and restarts
  the unit; unit/env/sudoers changes need a full `install.sh` run on the Pi). The control host deploys
  automatically, so the Pi can lag indefinitely. `core/contract.py`'s `HARDWARE_API_VERSION` is what
  catches it: the api refuses to *start a brew* against an older Pi (409 with
  `detail.code == "hardware_version_mismatch"`) while still serving the UI. Bump that version for any
  api↔hardware contract change — CI emits a warning when `contract.py` changes.
- **Never write `cur_brew.status = BrewState.BREWING` unconditionally** in the background tasks. Both
  loops did, which silently un-paused a paused brew and resumed driving the valve — the scale loop
  runs while `PAUSED`, and the step loop has awaits during which a pause can land. Only recover from
  `ERROR`. Covered by `tests/api/test_brew_pause.py`.
- `/` is a **307 redirect to `/app/`** and nothing else — container healthchecks and proxy probes must
  still target `/api/health`. A redirect is not a health signal: a probe that follows it reports the
  static bundle's availability, not the api's. (Before that redirect existed, `/` was a permanent 404,
  which is what made probing it obviously wrong; now it fails quietly instead.)
- Secrets support `<VAR>_FILE` indirection via `core/secrets.py` (used for `BREWCTL_INFLUXDB_TOKEN`).
  It **raises** when the file is set but unreadable rather than falling back to an empty value, which
  would otherwise surface as an opaque InfluxDB 401 hours into a brew. `api/config.py` also raises at
  import if `BREWCTL_IS_PROD=true` with no token.
- **Vite `envPrefix` is `BREWCTL_FRONTEND_`, not `BREWCTL_`** — anything matching the prefix in the
  build environment is inlined into the client bundle, and `BREWCTL_INFLUXDB_TOKEN` shares the
  `BREWCTL_` namespace. Never widen it. Only `BREWCTL_FRONTEND_API_URL` and
  `BREWCTL_FRONTEND_IS_PROD` are exposed; both are declared in `src/vite-env.d.ts`.
- The frontend's API URL defaults to `${window.location.origin}/api` and `vite.config.ts` uses a
  relative `base: "/app/"` — production needs no URL configuration. Set `BREWCTL_FRONTEND_API_URL`
  only in dev, where vite (:5173) and the api (:8000) are different origins.
- Config modules use `import *` chains (`core.config` → `api.config` → `model` → `server`), and
  values are read at import time, so env changes require a process restart, and tests that need
  different config must patch the module attribute.
- `api/config.py` appends `-dev` to `BREWCTL_INFLUXDB_BUCKET` unless `BREWCTL_IS_PROD=true`.
- `BREWCTL_HARDWARE_URL` **raises** at import when `BREWCTL_IS_PROD=true` and it is unset or blank;
  off-prod it falls back to `http://localhost:8001` so tests and `fastapi dev` need no environment.
  `api/server.py` builds `HttpScale`/`HttpValve` at import time, so a `None` there used to surface as
  `AttributeError: 'NoneType' object has no attribute 'rstrip'`. Covered by `tests/api/test_config.py`.
- Hardware device deps (`bluepy`, `RPi.GPIO`, Adafruit MotorKit) are in `requirements/hardware.txt`
  and install only on the Pi — production hardware imports are done lazily inside
  `create_scale()`/`create_valve()` to keep dev machines working.
- `tests/api/conftest.py` patches `HttpScale`/`HttpValve` as *classes*, but `api/server.py`
  instantiates them at import time. A test module with a top-level `import brewctl.api.server` binds
  the real classes and breaks ~12 unrelated tests with 503s — import the module inside a fixture that
  depends on `client`. The `client` fixture also rebinds `server.scale`/`server.valve`/`_real_scale`/
  `_real_valve` to the current test's mocks on every use (not just at first import), so no test
  inherits another's fixture-mock mutations and filtered runs (`pytest -k ...`) are order-independent.
  Corollary: lifespan startup's `connect()`/heartbeat now land on the *test's* mock — fixtures that
  count calls on it must `reset_mock()` first (`test_heartbeat.py::heartbeat_valve`).
- Tests are split `tests/core`, `tests/api`, `tests/hardware`, each with its own `conftest.py`
  (`client` for the api app, `hardware_client` for the hardware app).
- README's endpoint tables are **generated** — `make docs` runs
  `backend/scripts/gen_endpoint_docs.py`, which renders both apps' OpenAPI schemas between the
  `<!-- BEGIN/END GENERATED ENDPOINTS -->` markers. `backend/tests/test_readme_endpoints.py` runs it
  with `--check` (in a subprocess, since importing `api.server` in-process would bind the real
  `HttpScale`/`HttpValve`), so adding a route without regenerating fails the suite. Route docstrings
  are the table's Description column — the first line is what shows up.
