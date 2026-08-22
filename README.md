# Brewctl

A precision cold brew coffee system with real-time flow rate control, built on a Raspberry Pi with a React frontend.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Design Goals](#design-goals)
- [Architecture Diagram](#architecture-diagram)
- [Quick Start](#quick-start)
- [API Endpoints](#api-endpoints)
- [Configuration](#configuration)
- [Testing Guidelines](#testing-guidelines)
- [Hardware Setup](#hardware-setup)
- [Development](#development)

---

## Architecture Overview

The Brewctl system consists of three main components, split into a microservices architecture:

### Backend (Python/FastAPI) - API Service
The API service runs on a Raspberry Pi (or development machine) and provides:
- **REST API** - HTTP endpoints for brew control (start, stop, pause, resume, kill)
- **Time Series Storage** - Writes metrics to InfluxDB for flow rate calculation
- **Brew Strategy Engine** - Pluggable strategies for controlling the brewing process
- **Hardware Abstraction** - Uses HTTP clients to send commands to the Hardware service

### Backend (Python/FastAPI) - Hardware Service
The Hardware service runs directly on the device connected to the hardware:
- **Scale Integration** - Reads weight from Acaia Lunar scale via Bluetooth
- **Valve Control** - Controls stepper motor valve via Adafruit MotorKit

### Frontend (React/TypeScript)
The web-based user interface provides:
- **Real-time Status** - Polls backend for current brew state, weight, and flow rate
- **Brew Controls** - Start, pause, resume, and cancel brews
- **Visual Feedback** - Animated flip cards showing brew progress

### Infrastructure
- **InfluxDB** - Time-series database for storing weight readings and calculating flow rates
- **Docker/Docker Compose** - Containerized deployment for development and production

---

## Design Goals

### 1. Hardware Abstraction
All hardware components (scale, valve) are accessed through abstract interfaces. This enables:
- Easy mocking for testing
- Swapping hardware implementations without changing business logic
- Clear separation of concerns

```python
# AbstractScale defines the interface
class AbstractScale(ABC):
    @property
    @abstractmethod
    def connected(self) -> bool: pass
    
    @abstractmethod
    def get_weight(self) -> float: pass

# Two implementations:
# - LunarScale: Real Acaia scale via Bluetooth
# - MockScale: For testing and development
```

### 2. Production/Development Modes
The system runs in two modes based on the `BREWCTL_IS_PROD` environment variable:

| Mode | Scale | Valve | InfluxDB Bucket |
|------|-------|-------|-----------------|
| Development | MockScale | MockValve | brewctl-dev |
| Production | LunarScale | MotorKitValve | brewctl |

### 3. Real-time Monitoring
- Scale is polled every 0.5 seconds (configurable)
- Weight data is written to InfluxDB
- Flow rate is calculated from InfluxDB using aggregate rate queries
- Frontend polls for status every 2 seconds

### 4. Pluggable Brewing Strategies
The `AbstractBrewStrategy` interface allows custom brewing algorithms:

```python
class AbstractBrewStrategy(ABC):
    @abstractmethod
    def step(self, flow_rate: Optional[float], current_weight: Optional[float]) -> Tuple[ValveCommand, int]:
        pass
```

The `DefaultBrewStrategy` adjusts the valve to maintain a target flow rate:
- **Flow too slow** → Step valve forward (open more)
- **Flow too fast** → Step valve backward (close more)
- **At target** → Hold position

### 5. Fail-safe Operations
- **Pause/Resume** - Gracefully pause and resume brewing
- **Kill** - Forcefully stop and reset the system
- **Error handling** - System tracks error states for debugging

---

## Architecture Diagram

```mermaid
graph TD
    %% Frontend Layer
    subgraph Frontend [User Interface]
        UI[React/TypeScript Frontend<br/>Vite]
    end

    %% API Layer
    subgraph APILayer [API Service (FastAPI - Port 8000)]
        BrewServer[API Server]
        BrewStrategy[Brew Strategy Engine]
        TimeSeries[Time Series / Influx Client]
        HttpAbstractions[HTTP Hardware Clients]
        
        BrewServer --> BrewStrategy
        BrewServer --> TimeSeries
        BrewServer --> HttpAbstractions
    end

    %% Hardware Layer
    subgraph HardwareLayer [Hardware Service (FastAPI - Port 8001)]
        HWServer[Hardware API Server]
        subgraph Drivers [Hardware Drivers]
            LunarScale[LunarScale Bluetooth]
            MotorValve[MotorKit Valve I2C]
        end
        HWServer --> Drivers
    end

    %% Infrastructure Layer
    subgraph Infra [Infrastructure]
        InfluxDB[(InfluxDB)]
    end

    %% Physical Hardware
    subgraph Physical [Physical Devices]
        Scale[Acaia Lunar Scale]
        Motor[Stepper Motor]
    end

    %% Connections
    UI -- "REST API (Polls Status)" --> BrewServer
    HttpAbstractions -- "HTTP REST" --> HWServer
    TimeSeries -- "Read/Write" --> InfluxDB
    
    LunarScale -- "Bluetooth LE" --> Scale
    MotorValve -- "I2C" --> Motor
```

### Data Flow

```
1. User clicks "Start Brew"
   └─> Frontend calls POST /api/brew/start

2. API Service creates brew task and starts:
   ├─> collect_scale_data_task (every 0.5s)
   │   └─> HW Service GET /scale ──> InfluxDB.write()
   │
   └─> brew_step_task (every N seconds)
       ├─> InfluxDB.get_current_flow_rate()
       ├─> DefaultBrewStrategy.step()
       └─> HW Service POST /valve/step_forward/backward
```

---

## Quick Start

### Prerequisites

- Docker and Docker Compose (development, and the control host in production)
- For production, a Raspberry Pi with:
  - Bluetooth adapter
  - Acaia Lunar scale
  - Adafruit MotorKit with stepper motor

### Development Mode

```bash
make dev
```

All three services run locally, with the hardware service in mock mode
(`BREWCTL_IS_PROD=false` selects `MockScale`/`MockValve`), so no physical hardware
is needed:

- **Frontend**: http://localhost:5173 (vite dev server)
- **API**: http://localhost:8000
- **Hardware**: http://localhost:8001

InfluxDB is not part of the compose stack; point `BREWCTL_INFLUXDB_URL` at an
existing instance in `.env`, or leave it unset to run without time series.

### Production: two hosts

Production is split across two machines. See [Deployment](#deployment).

| | Runs | Manifests | Where today | How |
|---|---|---|---|---|
| **Device** | `BREWCTL_MODE=hardware` | `deploy/device/` | Raspberry Pi, `coldbrewer.local` | Bare metal, systemd |
| **Control** | `BREWCTL_MODE=api` + bundled frontend | `deploy/control/` | TrueNAS, `catacombs` | Docker, custom app |

The device owns the physical hardware; control holds the brewing logic and serves
the built frontend at `/app`, so the UI and the API are same-origin.

The deploy directories are named for those roles, not for the boxes: the control
service is not tied to a NAS, and only the device deploy depends on its host being
a Pi. The `BREWCTL_MODE` values are a separate, unchanged vocabulary — `control`
runs mode `api`, `device` runs mode `hardware`.

---

## Deployment

### Hardware service (Raspberry Pi, bare metal)

The Pi is a Pi Zero 2 W with 416 MB of RAM and no Docker. Deployment is a git
push to a bare repo, whose `post-receive` hook refreshes the venv and restarts
the unit.

OS prerequisites, none of which `install.sh` installs: `git`, `python3-venv`,
`python3-dev`, `libglib2.0-dev` (bluepy builds against it), a running `bluez`,
I²C enabled through `raspi-config`, and the service user in the `i2c`,
`bluetooth`, and `sudo` groups. `install.sh` hard-fails unless `pyacaia`,
`adafruit_motorkit`, and `adafruit_motor` all import, so a missing one surfaces
at install time rather than as silent mock mode later.

Check them all at once first — `deploy/device/preflight.sh` surveys the box read-only
(installs nothing, restarts nothing, safe to run mid-brew) and prints the `apt`
line for whatever is missing. It exits non-zero if anything would actually block
the install, so it works as a gate.

Before the Pi has the code, pipe it over stdin rather than copying it there:

```bash
ssh tomas@coldbrewer.local 'bash -s' < deploy/device/preflight.sh   # from a checkout
~/coldbrewer/deploy/device/preflight.sh                             # on the Pi, once it has the tree
```

First-time setup, on the Pi, **in this order**:

```bash
git clone <this repo> ~/coldbrewer      # seeds the work tree for the first install
~/coldbrewer/deploy/device/install.sh   # unit + /etc/brewctl/hardware.env + sudoers

git init --bare ~/coldbrewer.git
git -C ~/coldbrewer.git symbolic-ref HEAD refs/heads/master
cp ~/coldbrewer/deploy/device/post-receive ~/coldbrewer.git/hooks/
cp ~/coldbrewer/deploy/device/pre-receive ~/coldbrewer.git/hooks/
chmod +x ~/coldbrewer.git/hooks/post-receive ~/coldbrewer.git/hooks/pre-receive
git -C ~/coldbrewer.git config receive.advertisePushOptions true

sudoedit /etc/brewctl/hardware.env           # confirm BREWCTL_SCALE_MAC_ADDRESS
sudo systemctl restart brewctl-hardware
```

The order is load-bearing. The hook ends in `install.sh --deps-only`, which
restarts the unit with `sudo -n` — that needs the sudoers rule only a *full*
`install.sh` writes. Install the hook first and the very first `make deploy-device`
fails.

`post-receive` checks out **the ref you pushed** and moves the bare repo's `HEAD`
to follow, so `make deploy-device` from a new branch deploys that branch and says so.
`git -C ~/coldbrewer.git symbolic-ref HEAD` is therefore a record of what is
deployed, not a setting you have to keep in sync. Push exactly one branch: a push
carrying several is refused unless one of them is the branch already deployed,
and tag-only pushes and branch deletions deploy nothing.

This used to be a bare `checkout -f`, which checked out `HEAD` no matter what you
pushed. Switching branches then meant the push succeeded, the refs really did
update, and the Pi restarted on the *old* branch's code — with every later deploy
reporting success too. The `symbolic-ref` line in the setup block above still
seeds `HEAD` for the very first push, which happens before any hook has run.

`install.sh` creates the venv from `requirements/hardware.txt`, verifies the
device libraries import, installs `brewctl-hardware.service`, and disables the
old `coldbrew-backend`/`coldbrew-frontend` units. It never overwrites an existing
`/etc/brewctl/hardware.env`.

Thereafter, `make deploy-device` (a `git push`) is the whole deploy. Changes to the
unit, the env file, or sudoers still need a full `install.sh` run on the Pi —
`--deps-only` deliberately does not touch `/etc`.

**A deploy is refused while a brew is running.** `pre-receive` asks the api for
`brew_state` and rejects the push on `brewing`, `paused`, or `error`. It is
`pre-receive` rather than `post-receive` so that nothing moves on a refusal:
`post-receive` runs after the refs are updated and after its own `checkout -f`,
so failing there would leave the tree deployed and the service still running the
old code. It fails *open* when the api is genuinely absent (connection refused,
unresolvable host) so a crashlooping api cannot block the deploy that fixes it,
and *closed* on a timeout — a slow api is a running api and may be mid-brew.

The override is `make deploy-device FORCE=1`, which pushes `-o brewctl-force`.
Reach for it knowing what it costs: valve position lives only in the hardware
process (`MotorKitValve.breadcrumbs`), so the restart wipes it,
`return_to_start()` becomes a no-op, and a valve left open stays open while
`get_position()` — and therefore the UI — reports it closed. Stopping the brew
first is almost always the right move.

Both hooks are installed by hand; `install.sh` does not manage them. An existing
Pi needs the three `pre-receive` lines from the setup block above run once, or
its deploys stay ungated — `deploy/device/preflight.sh` reports whether they are.

**Always confirm it is driving real hardware.** `BREWCTL_IS_PROD` defaults to
false, and when it is not exactly `true` the service starts happily on
`MockScale`/`MockValve` — `/health` reports healthy and nothing physical moves:

```bash
journalctl -u brewctl-hardware | grep -iE 'production|mock'
# want: "Initializing production [ac lunar] scale" / "Initializing production valve"
```

### Control service (TrueNAS custom app)

`PUT /api/v2.0/app/id/{name}` takes a custom app's whole compose config as
`custom_compose_config_string`, so `deploy/control/apply.sh` posts one file with one
substitution made and nothing else:

- `deploy/control/app.yaml` — the *shape* of the deployment (ports, env, secrets,
  healthcheck), with an `@IMAGE@` placeholder. Changes rarely.
- `deploy/control/image.tag` — the one pinned image reference. **This file is the deploy.**

Publishing and promoting are separate:

```bash
git tag v1.2.3 && git push forgejo v1.2.3    # CI tests, builds, publishes. Deploys nothing.
# then put the published reference in deploy/control/image.tag and push -- that is the deploy
```

Git therefore records what is running, and rollback is `git revert` of the bump —
which works only while that image is still loaded on the control host, since there is no
registry to re-pull from. Apply by hand with:

```bash
./deploy/control/apply.sh deploy/control/app.yaml --render   # preview, no network
TRUENAS_URL=https://<truenas-host> TRUENAS_API_KEY=... make deploy-control
```

`apply.sh` refuses to apply an unrendered manifest or a placeholder tag. For an
emergency rollback to an image already on the box, `--image REF` bypasses
`image.tag` — the box is then running something git does not record, so follow it
with a real commit.

UI at `http://<control-host>:8000/app`, API at `http://<control-host>:8000/api`.

One-time bootstrap, in order:

1. Set the repo config in Forgejo — `vars.DEPLOY_USER`, `vars.DEPLOY_HOST`,
   `vars.TRUENAS_URL`, `vars.BREWCTL_API_URL`, `secrets.DEPLOY_SSH_KEY`,
   `secrets.DEPLOY_KNOWN_HOSTS`, `secrets.TRUENAS_API_KEY` (APPS_WRITE). The
   deploy user must be in the `docker` group on the control host; check with
   `ssh -o BatchMode=yes $DEPLOY_USER@$DEPLOY_HOST 'docker images && command -v gunzip'`.
2. Put the InfluxDB token at the `secrets:` path in `app.yaml`, non-empty and
   `root:root 0400`. The api reads it via `BREWCTL_INFLUXDB_TOKEN_FILE` and
   refuses to start without it, so it never appears in the manifest or in
   `docker inspect`. Confirm the org and bucket exist and that the token can write
   to them — a bad token yields `degraded`, not a failure.
3. Push to `forgejo` and let CI publish, then confirm the image reached the box:
   `ssh $DEPLOY_USER@$DEPLOY_HOST docker images catacombs/brewctl`. With
   `pull_policy: never` there is nothing to fall back on.
4. Create the app once in the **Custom App** UI — `PUT` is update, not create.
   Paste the output of `apply.sh --render --image <the published ref>`, and name
   the app `brewctl` (that name is the id the TrueNAS API addresses; override
   with `TRUENAS_APP` if it is ever named something else).
5. Put the same reference in `image.tag` and push **to `master`** — the deploy
   workflow only triggers there. That commit is what makes git the record.

Address the Pi by **IP**, not `coldbrewer.local` — mDNS does not resolve inside a
container. Give the Pi a DHCP reservation. The same caveat applies to
`BREWCTL_INFLUXDB_URL`: a `.local` name only works there if it is real DNS, so
check it resolves from *inside* a container on the control host.

`apply.sh` refuses to deploy while a brew is `brewing`, `paused`, or `error` (all
three still drive the valve), since a redeploy restarts the api and destroys the
in-process brew. It fails *open* if the api is refusing connections — otherwise a
crashlooping api could never be fixed — but fails *closed* on a timeout, because a
slow api is a running api. `--force` overrides.

---

## API Endpoints

Generated from the FastAPI OpenAPI schemas by `backend/scripts/gen_endpoint_docs.py`
(`make docs`). `backend/tests/test_readme_endpoints.py` fails if these tables drift from the code, so
edit the route, not the table.

Note the prefix difference between the services: the api service namespaces everything under
`/api`, the hardware service does not.

<!-- BEGIN GENERATED ENDPOINTS -->

<!-- Generated by backend/scripts/gen_endpoint_docs.py -- do not edit by hand. -->

### API service

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/brew/flow_rate` | Read the current flow rate from the time series. |
| POST | `/api/brew/kill` | Forcefully kill the current brew. |
| POST | `/api/brew/nudge/close` | Move valve one step closed, bypassing strategy (with rate limiting). |
| POST | `/api/brew/nudge/open` | Move valve one step open, bypassing strategy (with rate limiting). |
| POST | `/api/brew/pause` | Pause the current brew. |
| POST | `/api/brew/resume` | Resume a paused brew. |
| POST | `/api/brew/start` | Start a brew with the given brew ID. |
| GET | `/api/brew/status` | Gets the current brew status. |
| POST | `/api/brew/stop` | Gracefully stop the current brew. |
| POST | `/api/brew/strategy` | Swap the running brew's control strategy without stopping the brew. |
| GET | `/api/brew/{brew_id}/quality` | Get quality metrics for a completed brew. |
| GET | `/api/health` | Health check endpoint that reports the status of all critical system components. |
| GET | `/api/scale` | Read Scale |
| GET | `/api/scale/status` | Get Scale Status Endpoint |
| GET | `/api/valve/position` | Get Valve Position |
| GET | `/metrics` | Prometheus metrics for the api service. |

#### API service — event streams

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sse/brew/status` | SSE endpoint for real-time brew status updates. |
| GET | `/sse/health` | SSE endpoint for real-time health status updates. |

### Hardware service

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Root |
| POST | `/api/scale/connect` | Connect Scale |
| POST | `/api/scale/disconnect` | Disconnect Scale |
| GET | `/api/scale/status` | Get Scale Status |
| POST | `/api/valve/heartbeat` | Keepalive for the watchdog. A controller holding the valve open must call this |
| POST | `/api/valve/nudge/close` | Nudge Close |
| POST | `/api/valve/nudge/open` | Nudge Open |
| GET | `/api/valve/position` | Get Position |
| POST | `/api/valve/release` | Release |
| POST | `/api/valve/return_to_start` | Return To Start |
| GET | `/api/valve/status` | Get Status |
| GET | `/health` | Health |
| GET | `/metrics` | Prometheus metrics for the hardware service. |

#### Hardware service — event streams

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sse/scale/status` | SSE endpoint for real-time scale status updates. |
| GET | `/sse/valve/status` | SSE endpoint for real-time valve status updates. |

<!-- END GENERATED ENDPOINTS -->

---

## Configuration

### Environment Variables

Values are read at import time, so changes require a process restart.

**Both services**

| Variable | Default | Description |
|----------|---------|-------------|
| `BREWCTL_MODE` | `api` | `api` or `hardware`. Selects the app in `main.py` |
| `BREWCTL_IS_PROD` | `false` | Production mode. On the hardware service, anything other than `true` selects `MockScale`/`MockValve` |
| `BREWCTL_TARGET_FLOW_RATE` | `0.05` | Target flow rate (g/s) |
| `BREWCTL_TARGET_WEIGHT_GRAMS` | `1337` | Target brew weight (g) |
| `BREWCTL_EPSILON` | `0.008` | Flow rate tolerance |
| `BREWCTL_VALVE_INTERVAL_SECONDS` | `90` | Valve check interval |
| `BREWCTL_SCALE_READ_INTERVAL` | `0.5` | Scale polling interval |

**Hardware service only** (the Pi — `/etc/brewctl/hardware.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `BREWCTL_SCALE_MAC_ADDRESS` | - | Bluetooth MAC of the Lunar scale |
| `BREWCTL_VALVE_MOTOR_NUMBER` | `1` | MotorKit stepper driving the valve (1 or 2) |
| `BREWCTL_WATCHDOG_TIMEOUT_SECONDS` | `10.0` | Deadman switch, fast tier: used while heartbeats are arriving |
| `BREWCTL_WATCHDOG_BACKSTOP_SECONDS` | `300.0` | Deadman switch, slow tier: used when no heartbeat has been seen recently. Must exceed `BREWCTL_VALVE_INTERVAL_SECONDS` with margin |
| `BREWCTL_SCALE_MAX_WEIGHT_AGE_SECONDS` | `10.0` | A connected scale with no reading this recent is reported unhealthy and reconnected |
| `BREWCTL_SCALE_MONITOR_INTERVAL_SECONDS` | `5.0` | How often that is checked. Also connects the scale at startup |
| `BREWCTL_HARDWARE_LOG_LEVEL` | `INFO` | Applied to `pyacaia`/`bluepy`. `DEBUG` surfaces pyacaia's `Heartbeat failed`, the only evidence of why a scale went silent |

The watchdog closes the valve if nothing feeds it within the *effective* timeout:

```
effective = BREWCTL_WATCHDOG_TIMEOUT_SECONDS   if a heartbeat arrived within the backstop
            BREWCTL_WATCHDOG_BACKSTOP_SECONDS  otherwise
```

Two tiers because the api can be older than the Pi. An api without heartbeats only
contacts the hardware when it moves the valve — up to `BREWCTL_VALVE_INTERVAL_SECONDS`
apart — so holding it to the 10s timer would close the valve ~10s into every brew.
The timeout is derived rather than stored as an armed flag, so the valve is never
unguarded and a rollback decays back to the slow tier on its own.

**Control service only** (`deploy/control/app.yaml`)

| Variable | Default | Description |
|----------|---------|-------------|
| `BREWCTL_HARDWARE_URL` | - | The Pi's address, Use an IP, not mDNS |
| `BREWCTL_INFLUXDB_URL` | - | InfluxDB URL. Unset disables time series |
| `BREWCTL_INFLUXDB_TOKEN` | - | InfluxDB auth token. Prefer the `_FILE` form below |
| `BREWCTL_INFLUXDB_TOKEN_FILE` | - | Path to a file holding the token, e.g. `/run/secrets/influxdb_token`. Takes precedence, and **raises at startup** if set but unreadable rather than silently using an empty token |
| `BREWCTL_INFLUXDB_ORG` | - | InfluxDB organization |
| `BREWCTL_INFLUXDB_BUCKET` | `coldbrew` | Bucket name. `-dev` is appended unless `BREWCTL_IS_PROD=true` |
| `BREWCTL_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated origins. Set it to empty in production — the api serves the UI same-origin, so the dev default would otherwise be added to production origins |

Any `BREWCTL_*` variable can be supplied as `<VAR>_FILE` pointing at a file; see
`backend/src/brewctl/core/secrets.py`.

**Frontend** (build time)

Vite's `envPrefix` is `BREWCTL_FRONTEND_`, deliberately narrower than `BREWCTL_` —
anything matching the prefix in the build environment lands in the client bundle,
and `BREWCTL_INFLUXDB_TOKEN` must never get there.

| Variable | Default | Description |
|----------|---------|-------------|
| `BREWCTL_FRONTEND_API_URL` | `${window.location.origin}/api` | Dev-time override. Leave unset in production, where the api serves the bundle same-origin |
| `BREWCTL_FRONTEND_IS_PROD` | `false` | Cosmetic; drives the page title and the header flag |

---

## Testing Guidelines

### Running Tests

```bash
# Run all tests
make test

# Run backend tests only
make testBackend

# Run frontend tests only
make testFrontend
```

### Backend Testing

The backend uses **pytest** with FastAPI's `TestClient`. Tests are located in `backend/tests/`.

#### Test Fixtures (`conftest.py`)

```python
@pytest.fixture
def mock_scale():
    """Mock scale for testing."""
    scale = MagicMock()
    scale.connected = True
    scale.get_weight.return_value = 100.0
    scale.get_battery_percentage.return_value = 75
    return scale

@pytest.fixture
def mock_valve():
    """Mock valve for testing."""
    valve = MagicMock()
    # ... mock methods

@pytest.fixture
def mock_time_series():
    """Mock time series for testing."""
    ts = MagicMock()
    ts.get_current_flow_rate.return_value = 5.0
    # ... mock methods

@pytest.fixture
def client(mock_scale, mock_valve, mock_time_series):
    """TestClient with all dependencies mocked."""
    # Patches module-level objects and creates TestClient
```

#### Example Test

```python
def test_brew_pause_resume(client):
    """Test pausing and resuming a brew."""
    # Start a brew
    response = client.post("/api/brew/start")
    assert response.status_code == 200
    
    # Pause the brew
    response = client.post("/api/brew/pause")
    assert response.status_code == 200
    assert response.json()["status"] == "paused"
    
    # Resume the brew
    response = client.post("/api/brew/resume")
    assert response.status_code == 200
    
    # Clean up
    response = client.post("/api/brew/kill")
```

#### Test Files

Tests are split by the code they cover, each directory with its own `conftest.py`:

| Directory | Fixture | Coverage |
|-----------|---------|----------|
| `tests/core/` | — | Pydantic models, `MockScale`/`MockValve`, secrets indirection |
| `tests/api/` | `client` | Brew endpoints, pause/resume, strategies, health, SSE, flow-rate maths |
| `tests/hardware/` | `hardware_client` | Device endpoints, valve watchdog, scale MAC config, production imports |

`tests/api/conftest.py` patches `HttpScale`/`HttpValve` as *classes*, but `api/server.py`
instantiates them at import time — so a test module with a top-level `import brewctl.api.server`
binds the real classes and breaks unrelated tests with 503s. Import the module inside a fixture that
depends on `client`.

### Frontend Testing

The frontend uses **Vitest** for unit testing.

#### Running Frontend Tests

```bash
cd frontend
npm run test:run
```

#### Test Files

| File | Coverage |
|------|----------|
| `validators.test.ts` | Input validation logic |

#### Example Test

```typescript
import { validateTargetWeight, validateFlowRate } from './validators';

describe('validators', () => {
  describe('validateTargetWeight', () => {
    it('should accept valid weight', () => {
      const result = validateTargetWeight('1000');
      expect(result.valid).toBe(true);
    });
    
    it('should reject negative values', () => {
      const result = validateTargetWeight('-50');
      expect(result.valid).toBe(false);
    });
  });
});
```

### Testing Best Practices

1. **Always mock hardware** - Never test against real scale/valve in unit tests
2. **Use fixtures** - Reuse mock objects via pytest fixtures
3. **Test state transitions** - Verify brew goes through correct states
4. **Clean up after tests** - Use `yield` fixtures or `@pytest.fixture(autouse=True)` for cleanup
5. **Test edge cases** - Null flow rate, scale disconnection, concurrent requests

---

## Hardware Setup

### Production Hardware

| Component | Model | Interface |
|-----------|-------|-----------|
| Scale | Acaia Lunar | Bluetooth LE |
| Motor Controller | Adafruit MotorKit | I2C/USB |
| Stepper Motor | - | Connected to MotorKit |
| Single Board Computer | Raspberry Pi | - |

### Wiring (MotorKit)

```
MotorKit (I2C address 0x60)
├── SCL → RPi SCL
├── SDA → RPi SDA
├── VIN → 12V power supply
├── Stepper Motor (M1/M2)
```

### Bluetooth Setup

1. Enable Bluetooth on Raspberry Pi:
   ```bash
   sudo bluetoothctl
   scan on
   ```

2. Find Lunar scale MAC address (e.g., `XX:XX:XX:XX:XX:XX`)

3. Set environment variable:
   ```bash
   export BREWCTL_SCALE_MAC_ADDRESS="XX:XX:XX:XX:XX:XX"
   ```

---

## Development

### Project Structure

```
brewctl/
├── backend/
│   ├── src/brewctl/
│   │   ├── main.py            # Entrypoint; dispatches on BREWCTL_MODE
│   │   ├── core/              # Shared by both modes
│   │   │   ├── model.py       # Pydantic models & enums
│   │   │   ├── scale.py       # AbstractScale + MockScale
│   │   │   ├── valve.py       # AbstractValve + MockValve
│   │   │   ├── config.py      # Shared configuration
│   │   │   └── log.py
│   │   ├── hardware/          # Runs on the Pi; owns the devices
│   │   │   ├── server.py      # Device endpoints, SSE, valve watchdog
│   │   │   ├── LunarScale.py  # Acaia Lunar over BLE
│   │   │   └── MotorKitValve.py  # Stepper over I2C
│   │   └── api/               # Runs on the control host; no direct hardware access
│   │       ├── server.py      # Brew endpoints, SSE, serves the UI at /app
│   │       ├── http_scale.py  # AbstractScale over the hardware service's SSE
│   │       ├── http_valve.py  # AbstractValve over HTTP + SSE
│   │       ├── strategies/    # Brewing strategies (self-registering)
│   │       └── time_series.py # InfluxDB integration
│   ├── requirements/          # base / hardware / api / dev
│   └── tests/
│
├── frontend/
│   ├── src/components/        # React components (brew/, theme/)
│   └── package.json
│
├── deploy/
│   ├── device/                # systemd unit, env file, install.sh, git hooks
│   └── control/               # app manifest, apply.sh, pinned image tag
│
├── Dockerfile                 # Production api image (bundles the frontend)
├── docker-compose.yml         # Local dev, all three services
├── Makefile
└── README.md
```

### Running Backend Directly

Both modes share one entrypoint, `src/brewctl/main.py`, selected by `BREWCTL_MODE`.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt        # api deps + pytest
export PYTHONPATH=src

# API service (mocks the hardware service if it is not running)
BREWCTL_MODE=api      fastapi dev src/brewctl/main.py --port 8000

# Hardware service, mock devices
BREWCTL_MODE=hardware fastapi dev src/brewctl/main.py --port 8001

# Hardware service, real devices -- only works on the Pi, and needs the
# device libraries: pip install -r requirements/hardware.txt
BREWCTL_MODE=hardware BREWCTL_IS_PROD=true BREWCTL_SCALE_MAC_ADDRESS=XX:XX:XX:XX:XX:XX \
  fastapi dev src/brewctl/main.py --port 8001
```

### Running Frontend Directly

```bash
cd frontend
npm install
npm run dev
```

---

## License

MIT
