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

- Docker and Docker Compose (development, and the NAS in production)
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

| | Runs | Where | How |
|---|---|---|---|
| **Hardware service** | `BREWCTL_MODE=hardware` | Raspberry Pi | Bare metal, systemd |
| **API + frontend** | `BREWCTL_MODE=api` | TrueNAS | Docker Compose |

The Pi owns the physical devices; the api holds the brewing logic and serves the
built frontend at `/app`, so the UI and the API are same-origin.

---

## Deployment

### Hardware service (Raspberry Pi, bare metal)

The Pi is a Pi Zero 2 W with 416 MB of RAM and no Docker. Deployment is a git
push to a bare repo, whose `post-receive` hook refreshes the venv and restarts
the unit.

First-time setup, on the Pi:

```bash
git clone <this repo> ~/coldbrewer          # or push to ~/coldbrewer.git
cp deploy/pi/post-receive ~/coldbrewer.git/hooks/ && chmod +x ~/coldbrewer.git/hooks/post-receive
~/coldbrewer/deploy/pi/install.sh
sudoedit /etc/brewctl/hardware.env          # set BREWCTL_SCALE_MAC_ADDRESS
sudo systemctl restart brewctl-hardware
```

`install.sh` creates the venv from `requirements/hardware.txt`, verifies the
device libraries import, installs `brewctl-hardware.service`, and disables the
old `coldbrew-backend`/`coldbrew-frontend` units.

Thereafter, `make deploy-pi` (a `git push`) is the whole deploy.

**Always confirm it is driving real hardware.** `BREWCTL_IS_PROD` defaults to
false, and when it is not exactly `true` the service starts happily on
`MockScale`/`MockValve` — `/health` reports healthy and nothing physical moves:

```bash
journalctl -u brewctl-hardware | grep -iE 'production|mock'
# want: "Initializing production [ac lunar] scale" / "Initializing production valve"
```

### API + frontend (TrueNAS, Docker)

```bash
cp deploy/nas/.env.example deploy/nas/.env   # set the Influx token and the Pi's IP
docker compose -f deploy/nas/docker-compose.yml up -d --build
```

UI at `http://<nas>:8000/app`, API at `http://<nas>:8000/api`.

Address the Pi by **IP**, not `coldbrewer.local` — mDNS does not resolve inside a
container. Give the Pi a DHCP reservation.

---

## API Endpoints

### Brew Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/brew/start` | Start a new brew |
| POST | `/api/brew/stop?brew_id={id}` | Stop (graceful) |
| POST | `/api/brew/pause` | Pause current brew |
| POST | `/api/brew/resume` | Resume paused brew |
| POST | `/api/brew/kill` | Force kill brew |
| GET | `/api/brew/status` | Get current brew status |

### Scale & Flow

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/scale` | Get scale status (weight, battery) |
| GET | `/api/brew/flow_rate` | Get current flow rate |

### Valve Control (Advanced)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/brew/acquire` | Acquire valve (raw) |
| POST | `/api/brew/release?brew_id={id}` | Release valve (raw) |
| POST | `/api/brew/valve/forward?brew_id={id}` | Step forward |
| POST | `/api/brew/valve/backward?brew_id={id}` | Step backward |

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
| `BREWCTL_WATCHDOG_TIMEOUT_SECONDS` | `10.0` | Deadman switch: close the valve if no valve command or heartbeat arrives in this long |

**API service only** (the NAS — `deploy/nas/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `BREWCTL_HARDWARE_URL` | - | The Pi's address, e.g. `http://192.168.0.224:8000`. Use an IP, not mDNS |
| `BREWCTL_INFLUXDB_URL` | - | InfluxDB URL. Unset disables time series |
| `BREWCTL_INFLUXDB_TOKEN` | - | InfluxDB auth token |
| `BREWCTL_INFLUXDB_ORG` | - | InfluxDB organization |
| `BREWCTL_INFLUXDB_BUCKET` | `coldbrew` | Bucket name. `-dev` is appended unless `BREWCTL_IS_PROD=true` |
| `BREWCTL_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated origins. Only matters when the UI is not served by the api |

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

| File | Coverage |
|------|----------|
| `test_brew_api.py` | API endpoints, pause/resume, status |
| `test_brew_strategy.py` | Strategy logic, valve commands |
| `test_model.py` | Pydantic models, validation |
| `test_scale.py` | Scale abstraction, MockScale |
| `test_valve.py` | Valve abstraction, MockValve |

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
│   │   └── api/               # Runs on the NAS; no direct hardware access
│   │       ├── server.py      # Brew endpoints, SSE/WS, serves the UI at /app
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
│   ├── pi/                    # systemd unit, env file, install.sh, git hook
│   └── nas/                   # docker compose for api + frontend
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
