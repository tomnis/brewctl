import asyncio
import uuid
import time
import os
import json
import traceback
from typing import AsyncGenerator

from contextlib import asynccontextmanager
from fastapi import (
    FastAPI,
    Query,
    HTTPException,
    status,
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import field_validator
from typing import Annotated

from brewctl.core.log import logger
from brewctl.core.config import BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS
from brewctl.core.contract import HARDWARE_API_VERSION, MIN_HARDWARE_API_VERSION
from brewctl.core.config import *
from brewctl.core import metrics as brew_metrics
from brewctl.api.config import *
from brewctl.core.model import *
from brewctl.api.http_scale import HttpScale
from brewctl.api.brew_strategy import create_brew_strategy
from brewctl.core.model import (
    Brew,
    BrewState,
    StartBrewResponse,
    BrewCommandResponse,
    FlowRateResponse,
    HealthStatus,
    HealthResponse,
    StrategySwitch,
    SwitchStrategyRequest,
)

from brewctl.api.http_valve import HttpValve
from brewctl.core.simulated_scale import SimulatedScale
from brewctl.core.valve import MockValve
from brewctl.api.time_series import AbstractTimeSeries
from brewctl.api.time_series import InfluxDBTimeSeries
from brewctl.api.weight_buffer import WeightBuffer
from brewctl.api.brew_quality import compute_quality_score, get_score_grade
from datetime import datetime, timezone

from brewctl.api.config import BREWCTL_HARDWARE_URL

# Single instance of current brew instead of separate id and state
cur_brew: Brew | None = None

# The strategy the brew loop is driving. A module global rather than a local of
# brew_step_task so POST /api/brew/strategy can swap it mid-brew; the loop re-reads
# it every iteration.
cur_strategy = None

# The base params the current brew was started with. target_flow_rate, valve_interval,
# scale_interval and epsilon come from StartBrewRequest and are NOT stored on Brew, so
# without this a swapped-in strategy would silently fall back to the config defaults and
# brew to a different target than the operator asked for.
cur_base_params: dict | None = None

# Set by a strategy switch to cut short the brew loop's in-flight sleep, which is
# otherwise up to BREWCTL_VALVE_INTERVAL_SECONDS long. Created inside brew_step_task:
# an asyncio.Event waiter is only woken by a set() on the same loop, and the tests
# drive brew_step_task under their own asyncio.run.
strategy_switch_event: asyncio.Event | None = None

_strategy_switch_lock = asyncio.Lock()

# Floor on how often the strategy may be swapped. Every switch wakes the brew loop
# straight into a valve command, so an unbounded switch rate is an unbounded valve
# command rate.
STRATEGY_SWITCH_MIN_INTERVAL_SECONDS = 10.0

# How long start_brew waits for the first scale SSE frame before judging the
# scale's health. Three hardware ticks (SCALE_SSE_INTERVAL is 2s there), so a
# slow first frame does not read as a dead scale.
SCALE_FIRST_FRAME_TIMEOUT_SECONDS = 6.0
_last_strategy_switch_at: float | None = None


def create_time_series() -> InfluxDBTimeSeries:
    logger.info("Initializing InfluxDB time series...")

    ts: AbstractTimeSeries = InfluxDBTimeSeries(
        url=BREWCTL_INFLUXDB_URL,
        token=BREWCTL_INFLUXDB_TOKEN,
        org=BREWCTL_INFLUXDB_ORG,
        bucket=BREWCTL_INFLUXDB_BUCKET,
    )
    return ts


scale = HttpScale(BREWCTL_HARDWARE_URL)
time_series: AbstractTimeSeries = create_time_series()
weight_buffer: WeightBuffer = WeightBuffer(BREWCTL_SCALE_BUFFER_SIZE)

# Valve instance - HttpValve proxies to hardware server
valve = HttpValve(BREWCTL_HARDWARE_URL)

# The real hardware clients, kept aside so a dry run can borrow the `scale` and
# `valve` globals and hand them back. Nothing else may reassign these.
_real_scale = scale
_real_valve = valve

# Divides every brew-loop sleep. 1.0 outside a dry run -- a real brew's timing is
# dictated by the physical system.
_time_scale: float = 1.0


def _install_dry_run_hardware(time_scale: float) -> None:
    """Point the module globals at simulated devices for a dry run."""
    global scale, valve, _time_scale

    valve = MockValve()
    scale = SimulatedScale(valve, time_scale=time_scale)
    scale.connect()
    _time_scale = max(time_scale, 1.0)
    logger.info(f"Dry run: simulated scale and valve installed, {_time_scale}x time scale")


def _simulated_flow(flow_rate):
    """Convert a wall-clock flow rate into the brew's own clock.

    A dry run compresses the loop's sleeps by `_time_scale` and SimulatedScale
    fills `_time_scale` times faster to match, so every *duration* the loop
    measures is still wall-clock and reads `_time_scale` times too fast. Left
    uncorrected the strategy sees 60x its target flow and closes the valve on the
    first step, which is exactly what the first end-to-end dry run did.

    A no-op for real brews, where `_time_scale` is 1.0.
    """
    if flow_rate is None:
        return None
    return flow_rate / _time_scale


def _restore_hardware() -> None:
    """Hand the globals back to the real hardware clients.

    Load-bearing: a dry run that is never restored leaves the *next* real brew
    driving a MockValve while reporting healthy -- the same silent-mock failure
    mode BREWCTL_IS_PROD has. Every path that ends a brew calls this, and it is a
    no-op when no dry run was installed.
    """
    global scale, valve, _time_scale

    if scale is not _real_scale or valve is not _real_valve:
        logger.info("Dry run over: restoring real hardware clients")
    scale = _real_scale
    valve = _real_valve
    _time_scale = 1.0


def _clear_strategy_state() -> None:
    """Drop the swappable strategy state when a brew ends.

    Deliberately does not touch cur_brew: the STOP path keeps the COMPLETED record
    for /api/brew/status.
    """
    global cur_strategy, cur_base_params, strategy_switch_event, _last_strategy_switch_at

    cur_strategy = None
    cur_base_params = None
    strategy_switch_event = None
    _last_strategy_switch_at = None
    brew_metrics.clear_brew_metrics()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Try our best to manage the scale connection, but restart is finicky
    We don't need to eagerly connect to the scale here, just make sure we disconnect on shutdown
    """
    logger.info("Starting SSE listeners...")
    valve.connect()

    # Log the hardware contract state at startup. Deliberately non-fatal: the Pi is
    # often powered off, and refusing to boot would take the UI down with it -- the
    # UI is exactly where you would find out what is wrong. Enforcement happens at
    # brew start instead.
    try:
        await asyncio.to_thread(valve.heartbeat)
    except Exception as e:
        logger.warning(f"Could not reach hardware service at startup: {e}")
    compat = check_hardware_compatibility()
    if compat["compatible"]:
        logger.info(
            f"Hardware contract OK: v{compat['hardware_api_version']} "
            f"(api requires v{MIN_HARDWARE_API_VERSION})"
        )
    else:
        logger.warning(
            f"Hardware contract MISMATCH: hardware reports "
            f"v{compat['hardware_api_version']}, api requires v{MIN_HARDWARE_API_VERSION} "
            f"({compat['reason']}). Brews will be refused until the Pi is updated."
        )

    logger.info("lifespan: server startup complete, yielding control")
    yield
    if scale is not None:
        scale.disconnect()
    if valve is not None:
        valve.disconnect()
    logger.info("Shutting down, disconnected scale and valve...")


"""
Main place for backend logic. Webserver handles incoming requests acting as a "proxy" of sorts for both the scale and valve (hardware).
Prefer to use start/end endpoints as those are the simplest.
Acquire/release endpoints can be used for clients to implement their own fine-grained brewing logic.

Kill endpoints are also provided to forcefully kill an in-progress brew. 
"""
app = FastAPI(lifespan=lifespan)

# In production the api serves the frontend itself at /app, so requests are
# same-origin and CORS never comes into play. This list only matters for local
# development, where vite runs on :5173 and the api on :8000.
#
# Entries must be *origins* (scheme://host:port, no path). The previous list
# included BREWCTL_FRONTEND_API_URL -- an API endpoint ending in /api, which can
# never match an Origin header -- and a schemeless "localhost:5173".
origins = list(
    dict.fromkeys(o.strip() for o in BREWCTL_CORS_ORIGINS + [BREWCTL_FRONTEND_ORIGIN] if o and o.strip())
)
logger.info(f"CORS allow_origins = {origins}")


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_scale_status() -> ScaleStatus:
    """
    Reads status from the scale. Used for both a specific endpoint, and polling+writing scale data as part of the event loop.
    """
    # Read-only: never connect from here. This is on the /api/health path, and
    # HttpScale.connect() makes a blocking 10s POST to the Pi, which then blocks
    # attempting BLE. With the scale powered off that meant:
    #
    #   - /api/health taking up to 10s, longer than the container healthcheck's
    #     5s timeout, so a perfectly healthy api was reported unhealthy;
    #   - collect_scale_data_task (every 0.5s during a brew) making that blocking
    #     call from inside the event loop, stalling brew_step_task and the valve
    #     heartbeat with it.
    #
    # Connecting belongs to the two places that actually want the device:
    # start_brew(), which uses reconnect_with_backoff() and fails with a 503, and
    # the Pi itself, which owns physical reconnection (BREWCTL_SCALE_RECONNECT_*).
    global scale
    if scale is None:
        scale = HttpScale(BREWCTL_HARDWARE_URL)

    if scale.connected:
        weight = scale.get_weight()
        battery_pct = scale.get_battery_percentage()
        units = scale.get_units()
        return ScaleStatus(
            connected=True, weight=weight, units=units, battery_pct=battery_pct
        )
    else:
        return ScaleStatus(connected=False, weight=None, units=None, battery_pct=None)


def get_influxdb_health() -> dict:
    """
    Report InfluxDB connectivity for the health endpoints.

    InfluxDB is a non-fatal dependency: a brew runs off the in-process WeightBuffer and
    only falls back to Influx derivative queries. This must never hang -- see the short
    health_timeout on InfluxDBTimeSeries.
    """
    try:
        # ping() returns False on failure rather than raising, so the return value is
        # the signal; the except is only for the other failure modes (bad config, etc).
        if time_series.healthcheck():
            return {"connected": True, "error": None}
        return {"connected": False, "error": "influxdb ping failed"}
    except Exception as e:
        logger.error(f"Error checking InfluxDB health: {e}")
        return {"connected": False, "error": str(e)}


def scale_health_verdict() -> bool | None:
    """The hardware service's scale-health verdict, or None when there is none.

    None means "unknown, do not block": a Pi on hardware contract v1 does not send
    the field, and the simulated scale installed for a dry run has no opinion. Only
    an explicit False is a real "connected but not streaming".
    """
    checker = getattr(scale, "is_healthy", None)
    if checker is None:
        return None
    try:
        return checker()
    except Exception as e:
        logger.error(f"Error reading scale health: {e}")
        return None


def get_component_health() -> dict:
    """
    Get health status of all components (scale, valve, influxdb).
    Returns a dict suitable for SSE broadcast.
    """
    # Check scale status
    scale_health = {
        "connected": False,
        "healthy": None,
        "battery_pct": None,
        "weight": None,
        "units": None,
    }
    try:
        scale_status = get_scale_status()
        scale_health = {
            "connected": scale_status.connected,
            "healthy": scale_health_verdict(),
            "battery_pct": scale_status.battery_pct,
            "weight": scale_status.weight,
            "units": scale_status.units,
        }
    except Exception as e:
        traceback.print_exc()
        logger.error(BREWCTL_HARDWARE_URL)
        logger.error(f"Error checking scale health: {e}")

    # Check valve availability
    valve_health = {"available": False, "position": None}
    try:
        # Use cached values from SSE listener (no HTTP call needed)
        valve_health = {"available": valve.available, "position": valve.get_position()}
    except Exception as e:
        logger.error(BREWCTL_HARDWARE_URL)
        logger.error(f"Error checking valve health: {e}")

    # Check InfluxDB connectivity
    influxdb_health = get_influxdb_health()

    return {
        "scale": scale_health,
        "valve": valve_health,
        "influxdb": influxdb_health,
    }


@app.get("/api/scale")
def read_scale():
    return get_scale_status()


@app.get("/api/scale/status")
def get_scale_status_endpoint():
    return {
        "connected": scale.connected,
        "weight": scale.get_weight() if scale.connected else None,
        "units": scale.get_units() if scale.connected else None,
        "battery_pct": scale.get_battery_percentage() if scale.connected else None,
    }


@app.get("/api/valve/position")
def get_valve_position():
    return {"position": valve.get_position()}


def _scrape_valve_position():
    """Valve position for /metrics, without touching the network.

    HttpValve.get_position() falls back to a blocking HTTP call when its SSE
    cache is empty, and a scrape runs on the event loop -- cached_position()
    returns None instead. Reads the module global so a dry run's MockValve is
    reported while it is installed.
    """
    return valve.cached_position() if valve is not None else None


brew_metrics.set_scale_age_source(weight_buffer.age_seconds)
brew_metrics.set_valve_position_source(_scrape_valve_position)


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus metrics for the api service."""
    return brew_metrics.metrics_response()


@app.get("/api/health")
def health_check():
    """
    Health check endpoint that reports the status of all critical system components.
    Useful for load balancers, monitoring systems, and Docker healthchecks.
    """
    global cur_brew

    # Check scale status
    scale_health = {"connected": False, "healthy": None, "battery_pct": None}
    try:
        scale_status = get_scale_status()
        scale_health = {
            "connected": scale_status.connected,
            "healthy": scale_health_verdict(),
            "battery_pct": scale_status.battery_pct,
        }
    except Exception as e:
        logger.error(f"Error checking scale health: {e}")

    # Check valve availability (use cached SSE values)
    valve_health = {"available": False}
    try:
        # Use cached values from SSE listener
        valve_health = {"available": valve.available, "position": valve.get_position()}
    except Exception as e:
        logger.error(f"Error checking valve health: {e}")

    # Check InfluxDB connectivity
    influxdb_health = get_influxdb_health()

    # Check brew status
    brew_health = {
        "in_progress": cur_brew is not None
        and cur_brew.status in (BrewState.BREWING, BrewState.PAUSED),
        "brew_id": cur_brew.id if cur_brew else None,
        "status": cur_brew.status.value if cur_brew else "idle",
    }

    # Determine overall health status
    # Healthy: all components working
    # Degraded: some components have issues but core functionality works
    # Unhealthy: critical components are down

    # Contract version of the hardware service, so the UI can warn that the Pi
    # needs a push rather than letting a brew fail only at start time. Reads a
    # cached value -- no HTTP, so this stays fast and does not block when the Pi
    # is powered off.
    hardware_compat = check_hardware_compatibility()

    # InfluxDB is deliberately non-fatal: a brew drives the valve off the in-process
    # WeightBuffer and only falls back to Influx derivative queries. It can degrade the
    # reported status but must never reach UNHEALTHY, which is what apply.sh's deploy
    # gate refuses (it accepts healthy or degraded). Everything else is critical.
    critical_issues = []
    if not scale_health["connected"]:
        critical_issues.append("scale not connected")
    elif scale_health["healthy"] is False:
        # elif, not if: a silent scale and a disconnected one are the same fault
        # reported twice. Counting both would push "silent scale + valve down" from
        # DEGRADED to UNHEALTHY, which apply.sh refuses to deploy against.
        critical_issues.append("scale connected but not reporting weight")
    if not valve_health["available"]:
        critical_issues.append("valve not available")
    if not hardware_compat["compatible"]:
        critical_issues.append("hardware contract mismatch")

    if len(critical_issues) == 0:
        overall_status = HealthStatus.HEALTHY
    elif len(critical_issues) <= 2:
        overall_status = HealthStatus.DEGRADED
    else:
        overall_status = HealthStatus.UNHEALTHY

    if not influxdb_health["connected"] and overall_status == HealthStatus.HEALTHY:
        overall_status = HealthStatus.DEGRADED

    return HealthResponse(
        status=overall_status,
        scale=scale_health,
        valve=valve_health,
        influxdb=influxdb_health,
        brew=brew_health,
        hardware=hardware_compat,
        timestamp=datetime.now(timezone.utc),
    )


#### BREW ENDPOINTS ####
class MatchBrewId(BaseModel):
    """Middleware to match brew_id. Used to restrict execution to matching id pairs."""

    brew_id: str

    @field_validator("brew_id")
    def brew_id_must_match(cls, v):
        global cur_brew
        # logger.info(f"cur brew id: {cur_brew.id}")
        if cur_brew is None:
            raise ValueError("no brew_id in progress")
        elif v != cur_brew.id:
            raise ValueError("wrong brew_id")
        return v


async def collect_scale_data_task(brew_id, s):
    """Collect scale data every s seconds while brew_id matches current brew id."""
    global cur_brew
    # Tracks how long the scale has returned None while BREWING (the open-loop
    # pour guard below). Reset on any real reading and on pause.
    silence_since = None
    while brew_id is not None and cur_brew is not None and brew_id == cur_brew.id:
        try:
            # Collect data when actively brewing or in error state (to recover)
            if cur_brew.status in (
                BrewState.BREWING,
                BrewState.ERROR,
                BrewState.PAUSED,
            ):
                scale_state = get_scale_status()
                # logger.info(f"Scale state: {scale_state}")
                weight = scale_state.weight
                battery_pct = scale_state.battery_pct
                if weight is None:
                    logger.warn("Scale returned no weight")
                    # Open-loop pour guard: the strategy cannot act on a None
                    # flow (NOOP) and cannot STOP on a None weight, so a silent
                    # scale mid-brew means the valve freezes wherever it is.
                    # The hardware monitor holds the BLE link for this same
                    # window before rebuilding; past it, fail the brew and put
                    # the valve back rather than pouring unattended.
                    if cur_brew.status == BrewState.BREWING and BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS > 0:
                        now = time.monotonic()
                        if silence_since is None:
                            silence_since = now
                        elif now - silence_since >= BREWCTL_SCALE_SILENCE_RECONNECT_SECONDS:
                            logger.error(
                                f"Scale silent for {now - silence_since:.0f}s mid-brew -- "
                                "failing the brew and returning the valve."
                            )
                            cur_brew.status = BrewState.ERROR
                            cur_brew.error_message = (
                                f"scale silent for {now - silence_since:.0f}s mid-brew"
                            )
                            await asyncio.to_thread(valve.return_to_start)
                else:
                    silence_since = None
                if weight is not None and battery_pct is not None:
                    # logger.info(f"Brew ID: (writing influxdb data) {cur_brew.id} Weight: {weight}, Battery: {battery_pct}%")
                    time_series.write_scale_data(
                        weight, battery_pct, brew_id, dry_run=cur_brew.dry_run
                    )
                    weight_buffer.add_reading(weight)
                    # Recover from ERROR on a successful read -- but never from
                    # PAUSED. This loop also runs while paused (so the weight
                    # series has no gap), and unconditionally setting BREWING here
                    # silently un-paused the brew within one interval (0.5s),
                    # after which brew_step_task resumed driving the valve.
                    if cur_brew.status == BrewState.ERROR:
                        cur_brew.status = BrewState.BREWING
            await asyncio.sleep(s)
            # TODO should we also record the derivative as we've calculated it?
        except Exception as e:
            logger.error(f"Error collecting scale data: {e}")
            if cur_brew is not None:
                cur_brew.status = BrewState.ERROR
                cur_brew.error_message = str(e)
            await asyncio.sleep(s)


def check_hardware_compatibility() -> dict:
    """
    Compare the hardware service's contract version against what this api needs.

    The Pi is deployed by hand and never self-updates, so it can lag this service
    indefinitely -- this is what turns "forgot to push to the Pi" from a silent
    mid-brew failure into a refusal at the point of starting a brew.

    Reads the version cached from the last heartbeat rather than making an HTTP
    call, so this is safe to use on hot paths and does not block when the Pi is off.
    """
    version = getattr(valve, "hardware_api_version", None)
    # isinstance rather than a None check: a local/mock valve has no version at all,
    # and a malformed response could put anything here. bool is an int subclass, so
    # exclude it explicitly.
    if not isinstance(version, int) or isinstance(version, bool):
        # Never reached the hardware service, so we genuinely do not know. Treat as
        # incompatible: better to refuse than to start a brew we may not control.
        return {
            "compatible": False,
            "hardware_api_version": None,
            "required": MIN_HARDWARE_API_VERSION,
            "reason": "hardware service not yet reached",
        }
    return {
        "compatible": version >= MIN_HARDWARE_API_VERSION,
        "hardware_api_version": version,
        "required": MIN_HARDWARE_API_VERSION,
        "reason": None if version >= MIN_HARDWARE_API_VERSION else "hardware too old",
    }


HEARTBEAT_INTERVAL_SECONDS = 3.0


async def _safe_heartbeat():
    """Ping the hardware watchdog, logging rather than raising on failure."""
    try:
        await asyncio.to_thread(valve.heartbeat)
    except Exception as e:
        # Losing the heartbeat is not fatal to the brew loop -- the watchdog
        # closing the valve is the intended safe outcome.
        logger.warning(f"Valve heartbeat failed: {e}")


async def run_step_with_heartbeat(strategy, flow_rate, weight):
    """
    Run strategy.step() off the event loop, feeding the watchdog while it works.

    Most strategies are pure arithmetic and return instantly, but an LLM-backed one
    can block for seconds. That time is otherwise heartbeat-dead -- heartbeats are
    only emitted inside sleep_with_heartbeat -- so the hardware watchdog would close
    the valve mid-step.
    """
    task = asyncio.create_task(asyncio.to_thread(strategy.step, flow_rate, weight))
    while True:
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_INTERVAL_SECONDS)
        if done:
            return task.result()
        await _safe_heartbeat()


async def sleep_with_heartbeat(seconds: float) -> bool:
    """
    Sleep, pinging the hardware watchdog along the way.

    The strategy's valve interval (up to BREWCTL_VALVE_INTERVAL_SECONDS) is far longer
    than the hardware watchdog timeout, so an unbroken sleep would let the watchdog
    close the valve mid-brew.

    Returns True if a strategy switch cut the sleep short. The event is cleared at the
    top of the brew loop, never here -- see brew_step_task.
    """
    # The one choke point every brew-loop sleep passes through, so a dry run's
    # time scaling is applied exactly here. Chunking is deliberately not scaled:
    # an accelerated run then heartbeats more often per simulated second, never
    # less, so the hardware watchdog can only ever be fed too eagerly.
    remaining = seconds / _time_scale
    while remaining > 0:
        chunk = min(HEARTBEAT_INTERVAL_SECONDS, remaining)
        if strategy_switch_event is not None:
            try:
                await asyncio.wait_for(strategy_switch_event.wait(), timeout=chunk)
                # Woken early. Heartbeat before returning so the caller's next valve
                # command is never the first thing the hardware sees after a gap.
                await _safe_heartbeat()
                return True
            except asyncio.TimeoutError:
                pass  # wait_for really did consume `chunk` seconds
        else:
            await asyncio.sleep(chunk)
        remaining -= chunk
        await _safe_heartbeat()
    return False


async def brew_step_task(brew_id):
    """brew"""
    global cur_brew
    global strategy_switch_event

    # Created here, not in start_brew: an asyncio.Event waiter is only woken by a
    # set() on the loop it is parked on, and this task is where the waiting happens.
    strategy_switch_event = asyncio.Event()

    # Heartbeat before touching the valve at all. The loop below opens the valve and
    # only heartbeats after the first sleep chunk, so without this there is a window
    # of up to HEARTBEAT_INTERVAL_SECONDS where the valve is open but the hardware
    # has never seen a heartbeat -- which puts its watchdog on the slow backstop
    # timer rather than the tight one.
    try:
        await asyncio.to_thread(valve.heartbeat)
    except Exception as e:
        logger.warning(f"Initial valve heartbeat failed: {e}")

    while brew_id is not None and cur_brew is not None and brew_id == cur_brew.id:
        # Clear before reading, never after. A switch landing after the read re-sets
        # the event, so the sleep below short-circuits and the next iteration picks
        # it up; a switch landing before the read is already in cur_strategy. Clearing
        # inside sleep_with_heartbeat instead would leave the event set whenever a
        # switch arrived while this loop was in strategy.step() or a valve call -- the
        # common case -- and the next sleep would return instantly, firing two valve
        # commands back to back instead of a valve_interval apart.
        if strategy_switch_event is not None:
            strategy_switch_event.clear()
        strategy = cur_strategy
        if strategy is None:
            logger.warning(f"No strategy for brew {brew_id}, ending brew loop")
            break
        try:
            # Execute valve commands when actively brewing or in error state (to recover)
            if cur_brew.status in (BrewState.BREWING, BrewState.ERROR):
                # get the current flow rate and weight
                # Use local buffer first, fallback to InfluxDB during warm-up or if stale
                if weight_buffer.is_ready() and not weight_buffer.is_stale():
                    current_flow_rate = _simulated_flow(weight_buffer.get_flow_rate())
                    current_weight = weight_buffer.get_current_weight()
                else:
                    readings = time_series.get_recent_weight_readings(
                        duration_seconds=BREWCTL_VALVE_INTERVAL_SECONDS,
                        start_time_filter=cur_brew.time_started,
                        dry_run=cur_brew.dry_run,
                    )
                    current_flow_rate = _simulated_flow(
                        time_series.calculate_flow_rate_from_derivatives(readings)
                        if readings
                        else None
                    )
                    current_weight = time_series.get_current_weight(
                        dry_run=cur_brew.dry_run
                    )
                if current_flow_rate is not None:
                    brew_metrics.flow_rate.labels(brew_id=brew_id).set(current_flow_rate)
                    # getattr: target_flow_rate is on every real strategy, but a
                    # missing one must never be what fails a brew step.
                    target = getattr(strategy, "target_flow_rate", None)
                    if target is not None:
                        brew_metrics.flow_rate_error.set(target - current_flow_rate)

                (valve_command, interval) = await run_step_with_heartbeat(
                    strategy, current_flow_rate, current_weight
                )

                # step() can now take seconds (an LLM-backed strategy blocks on a
                # network call), so re-check what it was deciding for. Nothing
                # cancels these tasks -- stop/kill works purely by the brew_id
                # comparison at the top of the loop -- and asyncio.to_thread is not
                # cancellable anyway, so without this a brew stopped mid-step would
                # get one more valve command applied after return_to_start had
                # already run.
                if cur_brew is None or cur_brew.id != brew_id:
                    logger.info(f"Brew {brew_id} ended during strategy step, discarding command")
                    return
                # Likewise a strategy switch that landed mid-step: `strategy` was
                # read before the call, so its decision is stale. Let the next
                # iteration re-read cur_strategy rather than acting on it.
                if strategy_switch_event is not None and strategy_switch_event.is_set():
                    logger.info("Strategy switched during step, discarding stale command")
                    continue

                # Counted here rather than inside the branches below: there is no
                # else arm, so a NOOP would never be recorded -- and both discard
                # guards above have already run, so a dropped command is not counted.
                brew_metrics.valve_commands.labels(command=valve_command.name).inc()

                if valve_command == ValveCommand.STOP:
                    logger.info(f"Target weight reached, stopping brew {brew_id}")
                    brew_metrics.brews.labels(outcome="completed").inc()
                    cur_brew.status = BrewState.COMPLETED
                    cur_brew.time_completed = datetime.now(timezone.utc)
                    scale.disconnect()
                    # TODO should just be plain sync i think?
                    await asyncio.to_thread(valve.return_to_start)
                    await asyncio.to_thread(valve.release)
                    _restore_hardware()
                    _clear_strategy_state()
                    return
                elif valve_command == ValveCommand.FORWARD:
                    await asyncio.to_thread(valve.step_forward)
                elif valve_command == ValveCommand.BACKWARD:
                    await asyncio.to_thread(valve.step_backward)
                # Recover from ERROR on a successful valve operation -- but never
                # clobber PAUSED. There are awaits above, so a pause can land
                # mid-step; assigning BREWING unconditionally here silently
                # resumed it.
                if cur_brew is not None and cur_brew.status == BrewState.ERROR:
                    cur_brew.status = BrewState.BREWING
                await sleep_with_heartbeat(interval)
            else:
                # When paused, just sleep and check again. Still heartbeat: a paused
                # brew may be holding the valve open.
                await sleep_with_heartbeat(1)
        except Exception as e:
            logger.error(f"Error in brew step: {e}")
            traceback.print_exc()

            if cur_brew is not None:
                # Only on the way in: this loop keeps running while ERROR, so
                # counting every iteration would turn one flapping brew into
                # hundreds of failures.
                if cur_brew.status != BrewState.ERROR:
                    brew_metrics.brews.labels(outcome="error").inc()
                cur_brew.status = BrewState.ERROR
                cur_brew.error_message = str(e)
            await sleep_with_heartbeat(strategy.valve_interval)


def _build_base_params(req: StartBrewRequest) -> dict:
    """Build base parameters dict from request."""
    return {
        "target_flow_rate": req.target_flow_rate,
        "scale_interval": req.scale_interval,
        "valve_interval": req.valve_interval,
        "target_weight": req.target_weight,
        "vessel_weight": req.vessel_weight,
        "epsilon": req.epsilon,
    }


def _get_default_base_params() -> dict:
    """Get default base parameters from config."""
    return {
        "target_flow_rate": BREWCTL_TARGET_FLOW_RATE,
        "scale_interval": BREWCTL_SCALE_READ_INTERVAL,
        "valve_interval": BREWCTL_VALVE_INTERVAL_SECONDS,
        "target_weight": BREWCTL_TARGET_WEIGHT_GRAMS,
        "vessel_weight": BREWCTL_VESSEL_WEIGHT_GRAMS,
        "epsilon": BREWCTL_EPSILON,
    }


@app.post("/api/brew/start", response_model=StartBrewResponse)
async def start_brew(req: StartBrewRequest | None = None):
    """Start a brew with the given brew ID."""
    global cur_brew
    global scale
    global cur_strategy
    global cur_base_params

    logger.info(f"brew start request: {req}")

    # Check if a brew is already in progress
    if cur_brew is not None and cur_brew.status in (
        BrewState.BREWING,
        BrewState.PAUSED,
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "brew_in_progress", "message": "A brew is already in progress"},
        )

    dry_run = req is not None and req.dry_run

    # Refuse before the scale backoff below, so a version mismatch fails immediately
    # instead of waiting out several reconnect attempts first. Skipped for a dry
    # run: MockValve has no hardware_api_version, so this would 409 every
    # simulated brew -- and there is no Pi involved to be out of date.
    compat = {"compatible": True} if dry_run else check_hardware_compatibility()
    if not compat["compatible"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "hardware_version_mismatch",
                "message": (
                    f"Hardware service speaks contract v{compat['hardware_api_version']}, "
                    f"this api requires v{MIN_HARDWARE_API_VERSION}. "
                    "Push the latest code to the Pi (make deploy-device)."
                ),
                **compat,
            },
        )

    if dry_run:
        # Swap in simulated devices before the scale check below, which then
        # succeeds against the simulated scale rather than reaching for the Pi.
        _install_dry_run_hardware(req.time_scale)

    # Try to connect to scale with exponential backoff
    if scale is None or not scale.connected:
        if not dry_run:
            scale = HttpScale(BREWCTL_HARDWARE_URL)
        if not scale.reconnect_with_backoff():
            raise HTTPException(
                status_code=503,
                detail="Could not connect to scale after multiple attempts",
            )

    # A connected scale is not necessarily a working one: pyacaia marks the Lunar
    # connected as soon as BLE notifications are subscribed, and if that stream
    # dies every read comes back None until the hardware service reconnects. A brew
    # started against one drives the valve off no feedback at all.
    #
    # Skipped for dry runs, like the version check above -- there is no Pi involved.
    if not dry_run:
        # The scale above may have been constructed seconds ago, and the hardware
        # ticks its SSE stream every SCALE_SSE_INTERVAL (2s) while
        # reconnect_with_backoff only sleeps 0.5s. Judging it before the first frame
        # lands would refuse essentially every real brew.
        waiter = getattr(scale, "wait_for_first_frame", None)
        if waiter is not None:
            waiter(SCALE_FIRST_FRAME_TIMEOUT_SECONDS)

        if scale_health_verdict() is False:
            age = getattr(scale, "last_weight_age_seconds", lambda: None)()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "scale_unhealthy",
                    "message": (
                        "The scale is connected but has not reported a weight "
                        f"{'at all' if age is None else f'for {age:.1f}s'}. Its "
                        "Bluetooth stream is likely dead; the hardware service is "
                        "reconnecting. Retry in a few seconds."
                    ),
                    "last_weight_age_seconds": age,
                },
            )

    # Only allow starting if no brew or brew is completed/error
    if cur_brew is None or cur_brew.status in (BrewState.COMPLETED, BrewState.ERROR):
        new_id = str(uuid.uuid4())

        # Use defaults from config if request is None
        if req is None:
            # Build params with config defaults
            base_params = _get_default_base_params()
            strategy = create_brew_strategy(BrewStrategyType.DEFAULT, {}, base_params)
            target_weight = base_params["target_weight"]
            vessel_weight = base_params["vessel_weight"]
            strategy_type = BrewStrategyType.DEFAULT
        else:
            target_weight = req.target_weight
            vessel_weight = req.vessel_weight
            base_params = _build_base_params(req)
            strategy = create_brew_strategy(
                req.strategy, req.strategy_params, base_params
            )
            strategy_type = req.strategy
            logger.info(
                f"Created strategy: {req.strategy} with params: {req.strategy_params}"
            )

        cur_strategy = strategy
        cur_base_params = base_params

        cur_brew = Brew(
            id=new_id,
            status=BrewState.BREWING,
            time_started=datetime.now(timezone.utc),
            target_weight=target_weight,
            vessel_weight=vessel_weight,
            strategy=strategy_type,
            dry_run=dry_run,
        )

        weight_buffer.clear()

        # start scale read and brew tasks
        asyncio.create_task(
            collect_scale_data_task(cur_brew.id, BREWCTL_SCALE_READ_INTERVAL)
        )
        asyncio.create_task(brew_step_task(new_id))
        return StartBrewResponse(status="started", brew_id=cur_brew.id)
    else:
        # This should not be reached due to earlier check, but just in case
        _restore_hardware()
        raise HTTPException(status_code=409, detail="A brew is already in progress")


@app.post("/api/brew/stop")
async def stop_brew(brew_id: Annotated[MatchBrewId, Query()]):
    """Gracefully stop the current brew."""
    global cur_brew
    global scale

    old_id = cur_brew.id
    # Read before cur_brew is dropped below. Stopping an already-COMPLETED brew is
    # the normal UI flow once a brew finishes, and the STOP branch of the loop has
    # already counted that one -- without this guard it counts twice.
    if cur_brew.status != BrewState.COMPLETED:
        brew_metrics.brews.labels(outcome="stopped").inc()
    # TODO probably don't want to do this here, could cause some kind of conflict
    # edge case with teardown before anything has happened
    # valve.return_to_start()
    time.sleep(1)
    await asyncio.to_thread(valve.release)

    scale.disconnect()
    scale = None
    cur_brew = None
    _restore_hardware()
    _clear_strategy_state()
    return {"status": f"valve brew id ${old_id} stopped"}  # Placeholder response


@app.get("/api/brew/status")
async def brew_status():
    """Gets the current brew status."""
    global cur_brew
    if cur_brew is None:
        return {"status": "no brew in progress", "brew_state": BrewState.IDLE.value}
    elif cur_brew.status == BrewState.COMPLETED:
        # For completed brews, return final stats without computing dynamic values
        timestamp = datetime.now(timezone.utc)
        brew_status = cur_brew.to_brew_status(
            timestamp=timestamp,
            current_flow_rate=None,
            current_weight=None,
            estimated_time_remaining=0.0,
            valve_position=None,  # Valve returns to start on completion
        )
        return brew_status.model_dump()
    elif cur_brew.status == BrewState.ERROR:
        timestamp = datetime.now(timezone.utc)
        brew_status = cur_brew.to_brew_status(
            timestamp=timestamp,
            current_flow_rate=None,
            current_weight=None,
            estimated_time_remaining=None,
            valve_position=await asyncio.to_thread(valve.get_position),
        )
        return brew_status.model_dump()
    else:
        timestamp = datetime.now(timezone.utc)
        # Use time_started to filter out readings from previous brews
        readings = time_series.get_recent_weight_readings(
            duration_seconds=BREWCTL_VALVE_INTERVAL_SECONDS,
            start_time_filter=cur_brew.time_started,
            dry_run=cur_brew.dry_run,
        )
        current_flow_rate = _simulated_flow(
            time_series.calculate_flow_rate_from_derivatives(readings)
            if readings
            else None
        )
        current_weight = scale.get_weight()
        if current_weight is None:
            res = {
                "status": "scale not connected",
                "brew_state": cur_brew.status.value,
                "brew_id": cur_brew.id,
            }
        elif current_flow_rate is None:
            res = {
                "status": "insufficient data for flow rate",
                "brew_state": cur_brew.status.value,
                "brew_id": cur_brew.id,
            }
        else:
            # target_weight includes vessel_weight, so calculate remaining coffee weight
            vessel_weight = cur_brew.vessel_weight
            coffee_target = cur_brew.target_weight - vessel_weight
            current_coffee_weight = current_weight - vessel_weight
            remaining_weight = coffee_target - current_coffee_weight
            if remaining_weight <= 0:
                estimated_time_remaining = 0.0
            elif current_flow_rate <= 0:
                estimated_time_remaining = None
            else:
                estimated_time_remaining = remaining_weight / current_flow_rate

            brew_status = cur_brew.to_brew_status(
                timestamp=timestamp,
                current_flow_rate=current_flow_rate,
                current_weight=current_weight,
                estimated_time_remaining=estimated_time_remaining,
                valve_position=await asyncio.to_thread(valve.get_position),
            )
            return brew_status.model_dump()
        return res


@app.get("/api/brew/{brew_id}/quality")
async def get_brew_quality(brew_id: str):
    """
    Get quality metrics for a completed brew.

    Calculates how well the brew performed based on flow rate deviation
    from the target throughout the brewing process.
    """
    global cur_brew

    # Check if this is the current brew
    if cur_brew is not None and cur_brew.id == brew_id:
        # Can only get quality for completed brews
        if cur_brew.status != BrewState.COMPLETED:
            return {"error": "brew not completed yet", "status": cur_brew.status.value}

        if cur_brew.time_completed is None:
            return {"error": "brew has no completion time"}

        # Get brew parameters
        time_started = cur_brew.time_started
        time_completed = cur_brew.time_completed
        target_weight = cur_brew.target_weight
        vessel_weight = cur_brew.vessel_weight
        target_flow_rate = BREWCTL_TARGET_FLOW_RATE
        epsilon = BREWCTL_EPSILON
        dry_run = cur_brew.dry_run

        # Get actual final weight from the last reading
        readings = time_series.get_weight_readings_in_range(
            time_started, time_completed, dry_run=dry_run
        )
        if not readings:
            return {"error": "no weight readings found for this brew"}

        actual_weight = readings[-1][1]

    else:
        # TODO: Support querying historical brews from database
        return {"error": "brew not found or not the current brew"}

    # Get flow rates for the entire brew duration
    flow_rates = time_series.get_flow_rates_for_brew(
        time_started, time_completed, dry_run=dry_run
    )

    if not flow_rates:
        return {"error": "could not calculate flow rates for this brew"}

    # Calculate quality metrics
    metrics = compute_quality_score(
        flow_rates=flow_rates,
        target_flow_rate=target_flow_rate,
        epsilon=epsilon,
        target_weight=target_weight,
        vessel_weight=vessel_weight,
        actual_weight=actual_weight,
        time_started=time_started,
        time_completed=time_completed,
    )

    grade = get_score_grade(metrics.overall_score)

    return {
        "brew_id": brew_id,
        "grade": grade,
        "overall_score": round(metrics.overall_score, 1),
        "flow_rate_metrics": {
            "mean_absolute_error": round(metrics.mean_absolute_error, 4),
            "root_mean_square_error": round(metrics.root_mean_square_error, 4),
            "max_error": round(metrics.max_error, 4),
        },
        "stability_metrics": {
            "standard_deviation": round(metrics.flow_rate_std_dev, 4),
            "time_within_epsilon_pct": round(metrics.time_within_epsilon_pct, 1),
        },
        "completeness_metrics": {
            "target_weight": metrics.target_weight,
            "actual_weight": round(metrics.actual_weight, 1),
            "achieved_pct": round(metrics.weight_achieved_pct, 1),
        },
        "timing_metrics": {
            "expected_duration_seconds": round(metrics.expected_duration_seconds, 0),
            "actual_duration_seconds": round(metrics.actual_duration_seconds, 0),
            "efficiency_ratio": round(metrics.efficiency_ratio, 2),
        },
    }


def serialize_status(status: dict) -> dict:
    """Convert datetime objects to ISO format strings for JSON serialization."""
    if status is None:
        return status
    result = {}
    for key, value in status.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


async def sse_brew_status_generator() -> AsyncGenerator[str, None]:
    """
    SSE generator for real-time brew status updates.
    Yields SSE-formatted messages with brew status data.
    """
    try:
        while True:
            # Get current brew status
            status = await brew_status()
            serialized = serialize_status(status)

            # Format as SSE event
            yield f"data: {json.dumps(serialized)}\n\n"

            await asyncio.sleep(BREWCTL_WS_PUSH_INTERVAL)
    except asyncio.CancelledError:
        logger.info("SSE brew status connection closed by client")
        raise


@app.get("/sse/brew/status")
async def sse_brew_status():
    """
    SSE endpoint for real-time brew status updates.
    Clients connect and receive periodic brew status broadcasts via Server-Sent Events.
    """
    return StreamingResponse(
        sse_brew_status_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def sse_health_generator() -> AsyncGenerator[str, None]:
    """
    SSE generator for real-time health status updates.
    Yields SSE-formatted messages with component health data.
    """
    try:
        while True:
            # Get component health status. Offloaded: get_component_health() makes a
            # blocking InfluxDB ping, and running it inline here stalls the whole event
            # loop -- every SSE/WS client plus a running brew's step loop and heartbeat.
            health = await asyncio.to_thread(get_component_health)

            # Add timestamp
            health["timestamp"] = datetime.now(timezone.utc).isoformat()

            # Format as SSE event
            yield f"data: {json.dumps(health)}\n\n"

            await asyncio.sleep(BREWCTL_WS_HEALTH_PUSH_INTERVAL)
    except asyncio.CancelledError:
        logger.info("SSE health connection closed by client")
        raise


@app.get("/sse/health")
async def sse_health():
    """
    SSE endpoint for real-time health status updates.
    Clients connect and receive periodic component health broadcasts via Server-Sent Events.
    """
    return StreamingResponse(
        sse_health_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.post("/api/brew/pause", response_model=BrewCommandResponse)
async def pause_brew():
    """Pause the current brew."""
    global cur_brew
    if cur_brew is not None and cur_brew.status == BrewState.BREWING:
        cur_brew.status = BrewState.PAUSED
        logger.info("Brew paused")
        return BrewCommandResponse(status="paused", brew_state=cur_brew.status)
    elif cur_brew is not None and cur_brew.status == BrewState.PAUSED:
        return BrewCommandResponse(status="already paused", brew_state=cur_brew.status)
    else:
        raise HTTPException(
            status_code=400, detail="no brew in progress or already completed"
        )


@app.post("/api/brew/resume", response_model=BrewCommandResponse)
async def resume_brew():
    """Resume a paused brew."""
    global cur_brew
    if cur_brew is not None and cur_brew.status == BrewState.PAUSED:
        cur_brew.status = BrewState.BREWING
        logger.info("Brew resumed")
        return BrewCommandResponse(status="resumed", brew_state=cur_brew.status)
    elif cur_brew is not None and cur_brew.status == BrewState.BREWING:
        return BrewCommandResponse(status="already brewing", brew_state=cur_brew.status)
    else:
        raise HTTPException(status_code=400, detail="no paused brew to resume")


@app.post("/api/brew/strategy", response_model=BrewCommandResponse)
async def switch_strategy(req: SwitchStrategyRequest):
    """Swap the running brew's control strategy without stopping the brew.

    The valve is left exactly where it is -- that is the point: stopping and
    restarting returns the valve to start and throws away the operating point. The
    new strategy is warm-started from the current valve position and flow rate, and
    the switch is recorded on the brew and annotated in InfluxDB so the brew can be
    segmented by strategy afterwards.

    Note that the new strategy's scale_interval is inert: the scale collection task
    is started once with BREWCTL_SCALE_READ_INTERVAL and is not restarted here.
    """
    global cur_brew
    global cur_strategy
    global _last_strategy_switch_at

    if cur_brew is None or cur_brew.status not in (
        BrewState.BREWING,
        BrewState.PAUSED,
        BrewState.ERROR,
    ):
        raise HTTPException(status_code=409, detail="no running brew to switch")

    now = time.monotonic()
    if (
        _last_strategy_switch_at is not None
        and now - _last_strategy_switch_at < STRATEGY_SWITCH_MIN_INTERVAL_SECONDS
    ):
        raise HTTPException(
            status_code=429,
            detail=(
                "strategy switched too recently; wait "
                f"{STRATEGY_SWITCH_MIN_INTERVAL_SECONDS}s between switches"
            ),
        )

    async with _strategy_switch_lock:
        try:
            new_strategy = create_brew_strategy(
                req.strategy, req.strategy_params, cur_base_params or _get_default_base_params()
            )
        except ValueError as e:
            # Unknown strategy type or unusable params -- the caller's fault, not ours.
            raise HTTPException(status_code=400, detail=str(e))

        brew_id = cur_brew.id
        from_strategy = cur_brew.strategy

        # Blocking HTTP to the hardware service, so it must not run on the loop.
        valve_position = await asyncio.to_thread(valve.get_position)

        # The only suspension point in this critical section, so re-check that the
        # brew we are about to mutate is still the one that was running.
        if cur_brew is None or cur_brew.id != brew_id:
            raise HTTPException(status_code=409, detail="brew ended during switch")

        if weight_buffer.is_ready() and not weight_buffer.is_stale():
            flow_rate = _simulated_flow(weight_buffer.get_flow_rate())
        else:
            # None is a valid warm-start input; falling back to an InfluxDB derivative
            # query here would make the endpoint as slow as the brew loop's slow path.
            flow_rate = None

        new_strategy.warm_start(valve_position, flow_rate)

        cur_brew.strategy_switches.append(
            StrategySwitch(
                timestamp=datetime.now(timezone.utc),
                from_strategy=from_strategy,
                to_strategy=req.strategy,
                strategy_params=req.strategy_params,
                valve_position=valve_position,
                flow_rate=flow_rate,
            )
        )
        cur_brew.strategy = req.strategy
        cur_strategy = new_strategy
        # The new strategy may have a different target, so the old error is
        # meaningless and would otherwise sit there for a whole valve interval.
        brew_metrics.flow_rate_error.set(0)
        _last_strategy_switch_at = now
        if strategy_switch_event is not None:
            # None until brew_step_task first runs; the loop reads cur_strategy on
            # its next iteration regardless, this only cuts the sleep short.
            strategy_switch_event.set()

        logger.info(
            f"Brew {brew_id} strategy switched {from_strategy} -> {req.strategy} "
            f"at valve position {valve_position}, flow rate {flow_rate}"
        )

    try:
        await asyncio.to_thread(
            time_series.write_strategy_switch,
            brew_id,
            str(from_strategy.value if hasattr(from_strategy, "value") else from_strategy),
            str(req.strategy.value),
            valve_position,
            flow_rate,
            cur_brew.dry_run if cur_brew is not None else False,
        )
    except Exception as e:
        # An annotation is bookkeeping. Never let it abort a switch that already took.
        logger.warning(f"Failed to annotate strategy switch: {e}")

    return BrewCommandResponse(
        status="strategy_switched",
        brew_id=brew_id,
        brew_state=cur_brew.status if cur_brew is not None else None,
    )


@app.post("/api/brew/kill", response_model=BrewCommandResponse)
async def kill_brew():
    """Forcefully kill the current brew."""
    global cur_brew
    logger.info(f"{cur_brew.id if cur_brew else None} will be killed")
    if cur_brew is not None:
        old_id = cur_brew.id
        brew_metrics.brews.labels(outcome="killed").inc()
        cur_brew = None
        await asyncio.to_thread(valve.return_to_start)
        await asyncio.to_thread(valve.release)
        scale.disconnect()
        _restore_hardware()
        _clear_strategy_state()
        return BrewCommandResponse(
            status="killed", brew_id=old_id, brew_state=BrewState.IDLE
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no brew in progress"
        )


# TODO maybe not needed? might be better to just use the status end point
@app.get("/api/brew/flow_rate", response_model=FlowRateResponse)
def read_flow_rate():
    """Read the current flow rate from the time series."""
    global cur_brew
    if weight_buffer.is_ready() and not weight_buffer.is_stale():
        flow_rate = _simulated_flow(weight_buffer.get_flow_rate())
    elif cur_brew is not None and cur_brew.time_started is not None:
        readings = time_series.get_recent_weight_readings(
            duration_seconds=BREWCTL_VALVE_INTERVAL_SECONDS,
            start_time_filter=cur_brew.time_started,
            dry_run=cur_brew.dry_run,
        )
        flow_rate = _simulated_flow(
            time_series.calculate_flow_rate_from_derivatives(readings)
            if readings
            else None
        )
    else:
        flow_rate = time_series.get_current_flow_rate()
    return FlowRateResponse(
        brew_id=cur_brew.id if cur_brew else None, flow_rate=flow_rate
    )


# Rate limiting for nudge controls
import threading

_nudge_last_call_time: float = 0.0
NUDGE_MIN_INTERVAL_SECONDS: float = (
    2.0  # Minimum time between nudges to prevent motor damage
)
_nudge_lock = threading.Lock()


@app.post("/api/brew/nudge/open", response_model=BrewCommandResponse)
async def nudge_open():
    """Move valve one step open, bypassing strategy (with rate limiting)."""
    global cur_brew, _nudge_last_call_time

    if cur_brew is None or cur_brew.status != BrewState.BREWING:
        raise HTTPException(status_code=400, detail="no active brew in progress")

    with _nudge_lock:
        current_time = time.time()
        if current_time - _nudge_last_call_time < NUDGE_MIN_INTERVAL_SECONDS:
            raise HTTPException(
                status_code=429,
                detail=f"nudge too frequent, wait {NUDGE_MIN_INTERVAL_SECONDS} seconds",
            )
        _nudge_last_call_time = current_time

    logger.info(f"Nudge open for brew {cur_brew.id}")
    await asyncio.to_thread(valve.heartbeat)
    await asyncio.to_thread(valve.step_forward)
    return BrewCommandResponse(
        status="nudged_open", brew_id=cur_brew.id, brew_state=cur_brew.status
    )


@app.post("/api/brew/nudge/close", response_model=BrewCommandResponse)
async def nudge_close():
    """Move valve one step closed, bypassing strategy (with rate limiting)."""
    global cur_brew, _nudge_last_call_time

    if cur_brew is None or cur_brew.status != BrewState.BREWING:
        raise HTTPException(status_code=400, detail="no active brew in progress")

    with _nudge_lock:
        current_time = time.time()
        if current_time - _nudge_last_call_time < NUDGE_MIN_INTERVAL_SECONDS:
            raise HTTPException(
                status_code=429,
                detail=f"nudge too frequent, wait {NUDGE_MIN_INTERVAL_SECONDS} seconds",
            )
        _nudge_last_call_time = current_time

    logger.info(f"Nudge close for brew {cur_brew.id}")
    await asyncio.to_thread(valve.heartbeat)
    await asyncio.to_thread(valve.step_backward)
    return BrewCommandResponse(
        status="nudged_closed", brew_id=cur_brew.id, brew_state=cur_brew.status
    )


# ---- ui endpoints ----#


@app.get("/", include_in_schema=False)
async def root_to_app():
    """
    Send bare / to the UI.

    There was no root route at all, so every way in -- the published port, the
    Traefik hostname, a bookmark -- answered 404 to anyone who did not already
    know the UI lives at /app. Doing it here rather than as a Traefik middleware
    means it holds for direct :8000 access and `make prod-local` too, not only
    through the proxy.

    307, not 308: a permanent redirect is cached by browsers indefinitely, which
    would be painful to undo if / ever needs to serve something else.
    Redirecting to "/app/" with the trailing slash avoids a second hop through
    the catchall below.
    """
    return RedirectResponse(url="/app/", status_code=307)


# for react assets
assets_dir = "build/assets"
if not os.path.exists(assets_dir):
    os.makedirs(assets_dir)
app.mount("/app/assets", StaticFiles(directory=assets_dir), name="assets")


# catchall for react (must be last?)
@app.get("/app/{full_path:path}")
async def serve_react_app(full_path: str):
    return FileResponse("build/index.html")
