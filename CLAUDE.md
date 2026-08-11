# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make dev              # docker compose build && up — hardware:8001, api:8000, frontend:5173
make test             # backend + frontend
make testBackend      # cd backend && pytest tests
make testFrontend     # cd frontend && npm run test:run
```

Single test / focused runs:

```bash
cd backend && pytest tests/api/test_server.py::test_name     # pytest.ini sets pythonpath=src, testpaths=tests
cd frontend && npx vitest run src/components/brew/validators.test.ts
cd frontend && npm run lint && npm run build                 # eslint; build is tsc -b + vite build
```

Running a service outside Docker (from `backend/`, with `PYTHONPATH=src`):

```bash
BREWCTL_MODE=api      fastapi dev src/brewctl/main.py --port 8000
BREWCTL_MODE=hardware fastapi dev src/brewctl/main.py --port 8001
```

## Architecture

Two FastAPI apps from one Python package plus a React/Vite frontend. `brewctl/main.py` is the single
entrypoint: it reads `BREWCTL_MODE` (`api` | `hardware`) and imports the corresponding `app`. Both
containers build from the same `backend/Dockerfile`; mode is set per-service in `docker-compose.yml`.

- **`brewctl/core/`** — shared across both modes: `model.py` (Pydantic/enums: `BrewState`,
  `ValveCommand`, `BrewStrategyType`, `Brew`, `BrewStatus`), `config.py` (shared env vars),
  `scale.py` / `valve.py` (`AbstractScale`, `AbstractValve` + `MockScale`, `MockValve`), `log.py`.
- **`brewctl/hardware/`** — runs on the Pi, owns the physical devices. `create_scale()` /
  `create_valve()` pick `LunarScale`/`MotorKitValve` when `BREWCTL_IS_PROD=true`, mocks otherwise.
  Exposes `/api/valve/*`, `/api/scale/*` and SSE streams `/sse/valve/status`, `/sse/scale/status`.
  Has a watchdog (deadman switch): valve command endpoints and `POST /api/valve/heartbeat`
  call `feed_watchdog()`; if nothing feeds it for `WATCHDOG_TIMEOUT_SECONDS`
  (`BREWCTL_WATCHDOG_TIMEOUT_SECONDS`, default 10s) while the valve is off its start
  position, it closes the valve. Unrelated traffic (`/health`, SSE, `/api/valve/status`)
  deliberately does *not* feed it. Because strategy intervals can exceed the timeout,
  `api/server.py`'s `sleep_with_heartbeat()` chunks every brew-loop sleep and pings
  `valve.heartbeat()` every `HEARTBEAT_INTERVAL_SECONDS` (3s) — a plain `asyncio.sleep`
  in the brew loop will get the valve shut mid-brew.
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
  not `is_stale()`, otherwise falls back to InfluxDB derivative queries; calls `strategy.step()` and
  applies the returned `ValveCommand` + sleep interval. `STOP` completes the brew, returns the valve
  to start, and releases it.

State is global mutable module state, not a session store — one brew at a time. Tests reset it via
the `client`/`reset_globals` fixtures in `backend/tests/api/conftest.py`.

### Strategies

`AbstractBrewStrategy.step(flow_rate, current_weight) -> (ValveCommand, interval_seconds)`. Concrete
strategies live in `api/strategies/` and self-register into `BREW_STRATEGY_REGISTRY` via the
`@register_strategy(BrewStrategyType.X)` decorator; `create_brew_strategy()` builds them through
`from_params(strategy_params, base_params)`. `api/brew_strategy.py` is a re-export shim — importing
it is what triggers registration of every strategy, so import from there rather than the submodules.

Adding a strategy requires three coordinated edits: the `BrewStrategyType` enum in `core/model.py`,
the new class + `register_strategy` + re-export in `api/brew_strategy.py`, and the `STRATEGIES` array
in `frontend/src/components/brew/constants.ts` (its `StrategyType` union must match the enum values).

### Frontend

React 18 + Chakra UI + Vite. Real-time updates come from SSE (`useBrewStatus` subscribes to
`/sse/brew/status`, `useConnectionStatus` to `/sse/health`); WebSocket endpoints (`/ws/brew/status`,
`/ws/health`) still exist on the backend as an older path. URLs are derived in
`components/brew/constants.ts` by string-rewriting the API URL — changing the API base path affects
SSE/WS URLs too.

## Gotchas

- **Env var prefix mismatch**: `vite.config.ts` sets `envPrefix: 'COLDBREW_FRONTEND_API_URL'` and the
  frontend reads `import.meta.env.COLDBREW_FRONTEND_API_URL`, but compose/Makefile pass
  `BREWCTL_FRONTEND_API_URL`. Legacy `COLDBREW_*` naming survives in a few build paths.
- `make build-prod-image` references `unified-docker-compose.yml`, which is no longer in the tree.
- `README.md` predates the api/hardware split: its file paths (`brewctl/server.py`,
  `brewctl/pi/`) and endpoint table are partly stale — trust the source.
- Config modules use `import *` chains (`core.config` → `api.config` → `model` → `server`), and
  values are read at import time, so env changes require a process restart, and tests that need
  different config must patch the module attribute.
- `api/config.py` appends `-dev` to `BREWCTL_INFLUXDB_BUCKET` unless `BREWCTL_IS_PROD=true`.
- Pi-only deps (`bleak`, `RPi.GPIO`, Adafruit MotorKit) are in `requirements/pi.txt` and are not
  installed by the Dockerfile (`base.txt` only) — production hardware imports are done lazily inside
  `create_scale()`/`create_valve()` to keep dev machines working.
