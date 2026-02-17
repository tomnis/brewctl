# Cold Brewer

A precision cold brew coffee brewing system with real-time flow rate control, built on a Raspberry Pi with a React frontend.

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

The Cold Brewer system consists of three main components:

### Backend (Python/FastAPI)
The backend runs on a Raspberry Pi and provides:
- **REST API** - HTTP endpoints for brew control (start, stop, pause, resume, kill)
- **Scale Integration** - Reads weight from Acaia Lunar scale via Bluetooth
- **Valve Control** - Controls stepper motor valve via Adafruit MotorKit
- **Time Series Storage** - Writes metrics to InfluxDB for flow rate calculation
- **Brew Strategy Engine** - Pluggable strategies for controlling the brewing process

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
The system runs in two modes based on the `COLDBREW_IS_PROD` environment variable:

| Mode | Scale | Valve | InfluxDB Bucket |
|------|-------|-------|-----------------|
| Development | MockScale | MockValve | coldbrew-dev |
| Production | LunarScale | MotorKitValve | coldbrew |

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

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User Interface                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         React Frontend (Vite)                           ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ ││
│  │  │   Header    │  │     Brew    │  │    Footer    │  │   Theme    │ ││
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ ││
│  │                                                                          ││
│  │  ┌────────────────────────────────────────────────────────────────────┐ ││
│  │  │                    BrewContext (State Management)                  │ ││
│  │  │  • useBrewPolling() - polls /api/brew/status every 2 seconds       │ ││
│  │  │  • BrewProvider - manages brew state and actions                   │ ││
│  │  └────────────────────────────────────────────────────────────────────┘ ││
│  └───────────────────────────────┬─────────────────────────────────────────┘│
└───────────────────────────────────┼──────────────────────────────────────────┘
                                    │ HTTP JSON API
                                    │ (CORS enabled)
┌───────────────────────────────────┼──────────────────────────────────────────┐
│                         Backend (FastAPI)                                    │
│  ┌───────────────────────────────┴─────────────────────────────────────────┐│
│  │                         BrewServer                                        ││
│  │                                                                           ││
│  │  ┌─────────────────────────────────────────────────────────────────────┐ ││
│  │  │                     API Endpoints                                   │ ││
│  │  │  POST /api/brew/start    - Start a new brew                        │ ││
│  │  │  POST /api/brew/stop     - Stop (graceful)                         │ ││
│  │  │  POST /api/brew/pause    - Pause brew                               │ ││
│  │  │  POST /api/brew/resume   - Resume paused brew                       │ ││
│  │  │  POST /api/brew/kill     - Force stop                               │ ││
│  │  │  GET  /api/brew/status  - Get current brew status                  │ ││
│  │  │  GET  /api/scale        - Get scale reading                        │ ││
│  │  │  GET  /api/brew/flow_rate - Get calculated flow rate               │ ││
│  │  └─────────────────────────────────────────────────────────────────────┘ ││
│  │                                                                           ││
│  │  ┌─────────────────────────┐  ┌─────────────────────────────────────┐  ││
│  │  │   Async Brew Tasks      │  │      Brew Strategy Engine           │  ││
│  │  │                         │  │                                     │  ││
│  │  │ • collect_scale_data   │  │  AbstractBrewStrategy               │  ││
│  │  │   (polls every 0.5s)    │  │       └── DefaultBrewStrategy      │  ││
│  │  │                         │  │         • step()                    │  ││
│  │  │ • brew_step_task        │  │         • target_flow_rate         │  ││
│  │  │   (controls valve)      │  │         • epsilon (tolerance)       │  ││
│  │  └─────────────────────────┘  └─────────────────────────────────────┘  ││
│  └───────────────────────────────┬─────────────────────────────────────────┘│
└───────────────────────────────────┼──────────────────────────────────────────┘
                                    │
           ┌────────────────────────┼────────────────────────┐
           ▼                        ▼                        ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────────┐
│       Scale         │  │       Valve         │  │    InfluxDB            │
│   (AbstractScale)   │  │   (AbstractValve)   │  │  (TimeSeries)          │
├─────────────────────┤  ├─────────────────────┤  ├─────────────────────────┤
│                     │  │                     │  │                         │
│  ┌───────────────┐  │  │  ┌───────────────┐  │  │  • write_scale_data()  │
│  │  LunarScale   │  │  │  │ MotorKitValve │  │  │  • get_current_weight()│
│  │  (Bluetooth)  │  │  │  │  (I2C/USB)    │  │  │  • get_current_flow_   │
│  └───────────────┘  │  │  └───────────────┘  │  │    rate() (aggregate   │
│                     │  │                     │  │    rate query)          │
│  ┌───────────────┐  │  │  ┌───────────────┐  │  │                         │
│  │  MockScale    │  │  │  │   MockValve   │  │  └─────────────────────────┘
│  │  (Testing)    │  │  │  │  (Testing)    │  │
│  └───────────────┘  │  │  └───────────────┘  │
└─────────────────────┘  └─────────────────────┘
           │                    │
           ▼                    ▼
┌─────────────────────┐  ┌─────────────────────┐
│   Acaia Lunar       │  │   Adafruit         │
│   Scale            │  │   MotorKit         │
│   (Bluetooth LE)   │  │   (Stepper Motor)  │
└─────────────────────┘  └─────────────────────┘
```

### Data Flow

```
1. User clicks "Start Brew"
   └─> Frontend calls POST /api/brew/start

2. Backend creates brew task and starts:
   ├─> collect_scale_data_task (every 0.5s)
   │   └─> scale.get_weight() ──> InfluxDB.write()
   │
   └─> brew_step_task (every N seconds)
       ├─> InfluxDB.get_current_flow_rate()
       ├─> DefaultBrewStrategy.step()
       └─> valve.step_forward/backward()

3. Frontend polls GET /api/brew/status (every 2s)
   └─> Returns: weight, flow_rate, state, time_remaining
```

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- For production: Raspberry Pi with:
  - Bluetooth adapter
  - Acaia Lunar scale
  - Adafruit MotorKit with stepper motor

### Development Mode

```bash
# Clone the repository
git clone git@github.com:tomnis/coldbrewer.git
cd coldbrewer

# Start all services (backend, frontend, influxdb)
make dev
```

Services will be available at:
- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **InfluxDB**: http://localhost:8086

### Production Mode

```bash
# Set required environment variables
export COLDBREW_INFLUXDB_URL="http://influxdb:8086"
export COLDBREW_INFLUXDB_TOKEN="your-token"
export COLDBREW_INFLUXDB_ORG="your-org"
export COLDBREW_SCALE_MAC_ADDRESS="XX:XX:XX:XX:XX:XX"
export COLDBREW_FRONTEND_API_URL="http://backend:8000/api"

# Build and run
make build-prod-image
```

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

| Variable | Default | Description |
|----------|---------|-------------|
| `COLDBREW_IS_PROD` | `false` | Production mode flag |
| `COLDBREW_SCALE_MAC_ADDRESS` | - | Bluetooth MAC of Lunar scale |
| `COLDBREW_INFLUXDB_URL` | required | InfluxDB URL |
| `COLDBREW_INFLUXDB_TOKEN` | required | InfluxDB auth token |
| `COLDBREW_INFLUXDB_ORG` | required | InfluxDB organization |
| `COLDBREW_INFLUXDB_BUCKET` | `coldbrew` | InfluxDB bucket name |
| `COLDBREW_TARGET_FLOW_RATE` | `0.05` | Target flow rate (g/s) |
| `COLDBREW_TARGET_WEIGHT_GRAMS` | `1337` | Target brew weight (g) |
| `COLDBREW_EPSILON` | `0.008` | Flow rate tolerance |
| `COLDBREW_VALVE_INTERVAL_SECONDS` | `60` | Valve check interval |
| `COLDBREW_SCALE_READ_INTERVAL` | `0.5` | Scale polling interval |

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
   export COLDBREW_SCALE_MAC_ADDRESS="XX:XX:XX:XX:XX:XX"
   ```

---

## Development

### Project Structure

```
coldbrewer/
├── backend/
│   ├── src/
│   │   ├── brewserver/        # Main application
│   │   │   ├── server.py      # FastAPI app & endpoints
│   │   │   ├── model.py       # Pydantic models
│   │   │   ├── scale.py       # AbstractScale + MockScale
│   │   │   ├── valve.py       # AbstractValve + MockValve
│   │   │   ├── time_series.py # InfluxDB integration
│   │   │   ├── brew_strategy.py # Brewing strategies
│   │   │   ├── config.py      # Configuration
│   │   │   └── pi/            # Hardware implementations
│   │   │       ├── LunarScale.py
│   │   │       └── MotorKitValve.py
│   │   └── appserver/         # Standalone client (optional)
│   └── tests/                 # Backend tests
│
├── frontend/
│   ├── src/
│   │   ├── components/        # React components
│   │   │   ├── brew/          # Brew-related components
│   │   │   └── theme/         # Theme context
│   │   └── App.tsx            # Main app
│   └── package.json
│
├── docker-compose.yml         # Dev environment
├── unified-docker-compose.yml # Production
├── Makefile                   # Build commands
└── README.md
```

### Running Backend Directly

```bash
cd backend
source bin/activate  # if using venv
pip install -r requirements/base.txt

# Development (uses mocks)
fastapi dev src/brewserver/server.py --host 0.0.0.0 --port 8000

# Production (uses real hardware)
COLDBREW_IS_PROD=true COLDBREW_SCALE_MAC_ADDRESS=... \
  COLDBREW_INFLUXDB_URL=... fastapi dev src/brewserver/server.py
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
