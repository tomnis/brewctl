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
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import field_validator
from typing import Annotated

from brewctl.core.log import logger
from brewctl.core.contract import HARDWARE_API_VERSION, MIN_HARDWARE_API_VERSION
from brewctl.core.config import *
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
)

from brewctl.api.http_valve import HttpValve
from brewctl.api.time_series import AbstractTimeSeries
from brewctl.api.time_series import InfluxDBTimeSeries
from brewctl.api.weight_buffer import WeightBuffer
from brewctl.api.brew_quality import compute_quality_score, get_score_grade
from datetime import datetime, timezone

from brewctl.api.config import BREWCTL_HARDWARE_URL

# Single instance of current brew instead of separate id and state
cur_brew: Brew | None = None


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


def get_component_health() -> dict:
    """
    Get health status of all components (scale, valve, influxdb).
    Returns a dict suitable for WebSocket broadcast.
    """
    # Check scale status
    scale_health = {
        "connected": False,
        "battery_pct": None,
        "weight": None,
        "units": None,
    }
    try:
        scale_status = get_scale_status()
        scale_health = {
            "connected": scale_status.connected,
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


@app.get("/api/health")
def health_check():
    """
    Health check endpoint that reports the status of all critical system components.
    Useful for load balancers, monitoring systems, and Docker healthchecks.
    """
    global cur_brew

    # Check scale status
    scale_health = {"connected": False, "battery_pct": None}
    try:
        scale_status = get_scale_status()
        scale_health = {
            "connected": scale_status.connected,
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
                if weight is not None and battery_pct is not None:
                    # logger.info(f"Brew ID: (writing influxdb data) {cur_brew.id} Weight: {weight}, Battery: {battery_pct}%")
                    time_series.write_scale_data(weight, battery_pct, brew_id)
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


async def sleep_with_heartbeat(seconds: float):
    """
    Sleep, pinging the hardware watchdog along the way.

    The strategy's valve interval (up to BREWCTL_VALVE_INTERVAL_SECONDS) is far longer
    than the hardware watchdog timeout, so an unbroken sleep would let the watchdog
    close the valve mid-brew.
    """
    remaining = seconds
    while remaining > 0:
        chunk = min(HEARTBEAT_INTERVAL_SECONDS, remaining)
        await asyncio.sleep(chunk)
        remaining -= chunk
        try:
            await asyncio.to_thread(valve.heartbeat)
        except Exception as e:
            # Losing the heartbeat is not fatal to the brew loop -- the watchdog
            # closing the valve is the intended safe outcome.
            logger.warning(f"Valve heartbeat failed: {e}")


async def brew_step_task(brew_id, strategy):
    """brew"""
    global cur_brew

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
        try:
            # Execute valve commands when actively brewing or in error state (to recover)
            if cur_brew.status in (BrewState.BREWING, BrewState.ERROR):
                # get the current flow rate and weight
                # Use local buffer first, fallback to InfluxDB during warm-up or if stale
                if weight_buffer.is_ready() and not weight_buffer.is_stale():
                    current_flow_rate = weight_buffer.get_flow_rate()
                    current_weight = weight_buffer.get_current_weight()
                else:
                    readings = time_series.get_recent_weight_readings(
                        duration_seconds=BREWCTL_VALVE_INTERVAL_SECONDS,
                        start_time_filter=cur_brew.time_started,
                    )
                    current_flow_rate = (
                        time_series.calculate_flow_rate_from_derivatives(readings)
                        if readings
                        else None
                    )
                    current_weight = time_series.get_current_weight()
                (valve_command, interval) = strategy.step(
                    current_flow_rate, current_weight
                )

                if valve_command == ValveCommand.STOP:
                    logger.info(f"Target weight reached, stopping brew {brew_id}")
                    cur_brew.status = BrewState.COMPLETED
                    cur_brew.time_completed = datetime.now(timezone.utc)
                    scale.disconnect()
                    # TODO should just be plain sync i think?
                    await asyncio.to_thread(valve.return_to_start)
                    await asyncio.to_thread(valve.release)
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

    # Refuse before the scale backoff below, so a version mismatch fails immediately
    # instead of waiting out several reconnect attempts first.
    compat = check_hardware_compatibility()
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

    # Try to connect to scale with exponential backoff
    if scale is None or not scale.connected:
        scale = HttpScale(BREWCTL_HARDWARE_URL)
        if not scale.reconnect_with_backoff():
            raise HTTPException(
                status_code=503,
                detail="Could not connect to scale after multiple attempts",
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

        cur_brew = Brew(
            id=new_id,
            status=BrewState.BREWING,
            time_started=datetime.now(timezone.utc),
            target_weight=target_weight,
            vessel_weight=vessel_weight,
            strategy=strategy_type,
        )

        weight_buffer.clear()

        # start scale read and brew tasks
        asyncio.create_task(
            collect_scale_data_task(cur_brew.id, BREWCTL_SCALE_READ_INTERVAL)
        )
        asyncio.create_task(brew_step_task(new_id, strategy))
        return StartBrewResponse(status="started", brew_id=cur_brew.id)
    else:
        # This should not be reached due to earlier check, but just in case
        raise HTTPException(status_code=409, detail="A brew is already in progress")


@app.post("/api/brew/stop")
async def stop_brew(brew_id: Annotated[MatchBrewId, Query()]):
    """Gracefully stop the current brew."""
    global cur_brew
    global scale

    old_id = cur_brew.id
    # TODO probably don't want to do this here, could cause some kind of conflict
    # edge case with teardown before anything has happened
    # valve.return_to_start()
    time.sleep(1)
    await asyncio.to_thread(valve.release)

    scale.disconnect()
    scale = None
    cur_brew = None
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
        )
        current_flow_rate = (
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

        # Get actual final weight from the last reading
        readings = time_series.get_weight_readings_in_range(
            time_started, time_completed
        )
        if not readings:
            return {"error": "no weight readings found for this brew"}

        actual_weight = readings[-1][1]

    else:
        # TODO: Support querying historical brews from database
        return {"error": "brew not found or not the current brew"}

    # Get flow rates for the entire brew duration
    flow_rates = time_series.get_flow_rates_for_brew(time_started, time_completed)

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


@app.websocket("/ws/brew/status")
async def websocket_brew_status(websocket: WebSocket):
    """
    WebSocket endpoint for real-time brew status updates.
    Clients connect and receive periodic brew status broadcasts.
    """
    await websocket.accept()
    logger.info("WebSocket client connected for brew status")

    try:
        while True:
            # Send status update
            status = await brew_status()
            serialized = serialize_status(status)
            await websocket.send_json(serialized)

            await asyncio.sleep(BREWCTL_WS_PUSH_INTERVAL)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from brew status")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


@app.websocket("/ws/health")
async def websocket_health(websocket: WebSocket):
    """
    WebSocket endpoint for real-time health status updates.
    Clients connect and receive periodic component health broadcasts.
    Separate from brew status to allow different polling intervals.
    """
    await websocket.accept()
    logger.info("WebSocket client connected for health status")

    try:
        while True:
            # Get component health status. Offloaded: get_component_health() makes a
            # blocking InfluxDB ping, and running it inline here stalls the whole event
            # loop -- every SSE/WS client plus a running brew's step loop and heartbeat.
            health = await asyncio.to_thread(get_component_health)

            # Add timestamp
            health["timestamp"] = datetime.now(timezone.utc).isoformat()

            await websocket.send_json(health)

            await asyncio.sleep(BREWCTL_WS_HEALTH_PUSH_INTERVAL)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from health status")
    except Exception as e:
        logger.error(f"Health WebSocket error: {e}")


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


@app.post("/api/brew/kill", response_model=BrewCommandResponse)
async def kill_brew():
    """Forcefully kill the current brew."""
    global cur_brew
    logger.info(f"{cur_brew.id if cur_brew else None} will be killed")
    if cur_brew is not None:
        old_id = cur_brew.id
        cur_brew = None
        await asyncio.to_thread(valve.return_to_start)
        await asyncio.to_thread(valve.release)
        scale.disconnect()
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
        flow_rate = weight_buffer.get_flow_rate()
    elif cur_brew is not None and cur_brew.time_started is not None:
        readings = time_series.get_recent_weight_readings(
            duration_seconds=BREWCTL_VALVE_INTERVAL_SECONDS,
            start_time_filter=cur_brew.time_started,
        )
        flow_rate = (
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
