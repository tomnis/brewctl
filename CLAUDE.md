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
make deploy-pi        # git push coldbrewer <branch> — the ONLY way the Pi updates
make deploy-nas       # deploy/nas/apply.sh applies deploy/nas/app.yaml to TrueNAS
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

**Production is split across two hosts.** The hardware service runs *bare metal* on
`coldbrewer.local` (Pi Zero 2 W, arm64, 416 MB RAM, **no Docker**) under systemd — see `deploy/pi/`.
The api runs in Docker on the TrueNAS box and serves the built frontend at `/app`, so the UI is
same-origin with the API — see `deploy/nas/`. Locally, `docker-compose.yml` still runs all three from
`backend/Dockerfile` with the hardware service in mock mode.

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

### Strategies

`AbstractBrewStrategy.step(flow_rate, current_weight) -> (ValveCommand, interval_seconds)`. Concrete
strategies live in `api/strategies/` (one class per file, `PascalCase.py`) and self-register into
`BREW_STRATEGY_REGISTRY` via the `@register_strategy(BrewStrategyType.X)` decorator;
`create_brew_strategy()` builds them through `from_params(strategy_params, base_params)`. The
registry and base class themselves live in `strategies/DefaultBrewStrategy.py`.
`api/brew_strategy.py` is a re-export shim — importing it is what triggers registration of every
strategy, so import from there rather than from the submodules.

Adding a strategy touches four places, all of which must agree:

1. `BrewStrategyType` in `core/model.py` (the enum *value* is the wire id).
2. The new class file in `api/strategies/` with `@register_strategy(...)`.
3. `api/strategies/__init__.py` **and** `api/brew_strategy.py` re-exports.
4. The `STRATEGIES` array in `frontend/src/components/brew/constants.ts`, whose `StrategyType`
   union must match the enum values; each `params` entry becomes a form field posted as
   `strategy_params`.

### Frontend

React 18 + Chakra UI v3 + Vite + Recharts. Real-time updates come from SSE (`useBrewStatus`
subscribes to `/sse/brew/status`, `useConnectionStatus` to `/sse/health`); WebSocket endpoints
(`/ws/brew/status`, `/ws/health`) still exist on the backend as an older path. URLs are derived in
`components/brew/constants.ts` by string-rewriting the API URL — changing the API base path affects
SSE/WS URLs too.

### CI/CD (Forgejo, `.forgejo/workflows/`)

**Building is not deploying.** `build.yml` runs tests, builds the root `Dockerfile`, smoke-tests the
image (`/api/health` and `/app/`), and streams it onto the NAS with `docker save | ssh docker load`
— there is no registry, so `deploy/nas/app.yaml` pins registry-less local tags
(`tomas/brewctl:sha-<short12>`). Every branch publishes an image; it just sits on the daemon.
`deploy.yml` runs only on master pushes that touch `deploy/nas/app.yaml` or `apply.sh`, and applies
the manifest via the TrueNAS API. So **deploying is a one-line commit bumping the image tag**, and
rollback is `git revert` (valid while the old image is still loaded). `apply.sh` refuses to redeploy
while a brew is active, and fails open if the api is unreachable.

Forgejo is the CI origin — push directly to the `forgejo` remote; a pull mirror from GitHub would
not trigger runs.

## Gotchas

- **`BREWCTL_IS_PROD` failing silently is the worst failure mode in this repo.** Anything other than
  the exact string `true` makes the hardware service run `MockScale`/`MockValve`: it starts cleanly,
  `/health` reports healthy, and no physical device moves. After any config change on the Pi, check
  `journalctl -u brewctl-hardware | grep -iE 'production|mock'`.
- **The Pi never self-updates.** It changes only when someone runs `make deploy-pi` (a push to the
  `coldbrewer` remote, whose `post-receive` hook runs `deploy/pi/install.sh --deps-only` and restarts
  the unit; unit/env/sudoers changes need a full `install.sh` run on the Pi). The NAS deploys
  automatically, so the Pi can lag indefinitely. `core/contract.py`'s `HARDWARE_API_VERSION` is what
  catches it: the api refuses to *start a brew* against an older Pi (409 with
  `detail.code == "hardware_version_mismatch"`) while still serving the UI. Bump that version for any
  api↔hardware contract change — CI emits a warning when `contract.py` changes.
- **Never write `cur_brew.status = BrewState.BREWING` unconditionally** in the background tasks. Both
  loops did, which silently un-paused a paused brew and resumed driving the valve — the scale loop
  runs while `PAUSED`, and the step loop has awaits during which a pause can land. Only recover from
  `ERROR`. Covered by `tests/api/test_brew_pause.py`.
- The api has **no `/` route** (only `/api/*`, `/sse/*`, `/ws/*` and the `/app/{path}` catchall), so
  container healthchecks must probe `/api/health`. Probing `/` is a permanent 404.
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
  depends on `client`.
- Tests are split `tests/core`, `tests/api`, `tests/hardware`, each with its own `conftest.py`
  (`client` for the api app, `hardware_client` for the hardware app). README's "Testing Guidelines"
  section still lists the pre-split flat filenames (e.g. `test_brew_api.py`) and is stale there.
