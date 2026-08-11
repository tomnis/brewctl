import os
import time
import threading
import json
import asyncio
from typing import AsyncGenerator

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from brewctl.core.log import logger
from brewctl.core.valve import AbstractValve
from brewctl.core.scale import AbstractScale
from brewctl.core.config import *
from brewctl.hardware.config import *

SCALE_SSE_INTERVAL = 2.0
VALVE_SSE_INTERVAL = 2.0





def create_scale() -> AbstractScale:
    if BREWCTL_IS_PROD:
        logger.info("Initializing production [ac lunar] scale...")
        from brewctl.hardware.LunarScale import LunarScale

        s: AbstractScale = LunarScale(BREWCTL_SCALE_MAC_ADDRESS)
    else:
        logger.info("Initializing mock scale...")
        from brewctl.core.scale import MockScale

        s: AbstractScale = MockScale()
    return s


def create_valve() -> AbstractValve:
    if BREWCTL_IS_PROD:
        logger.info("Initializing production valve...")
        from brewctl.hardware.MotorKitValve import MotorKitValve

        v: AbstractValve = MotorKitValve()
    else:
        logger.info("Initializing mock valve...")
        from brewctl.core.valve import MockValve

        v: AbstractValve = MockValve()
    return v


scale: AbstractScale = None
valve: AbstractValve = None

NUDGE_MIN_INTERVAL_SECONDS = 2.0
_nudge_last_call_time = 0.0
_nudge_lock = threading.Lock()

# Deadman switch: if the valve is off its start position and no valve command or
# heartbeat arrives for this long, close it. Only the endpoints that touch the
# valve (and the explicit heartbeat) feed this timer -- unrelated traffic such as
# /health or SSE subscriptions must not keep an open valve alive.
WATCHDOG_TIMEOUT_SECONDS = float(os.getenv("BREWCTL_WATCHDOG_TIMEOUT_SECONDS", "10.0"))
WATCHDOG_POLL_INTERVAL_SECONDS = 1.0
_last_valve_command_time = time.time()


def feed_watchdog() -> None:
    """Record that a controller is still alive and holding the valve."""
    global _last_valve_command_time
    _last_valve_command_time = time.time()


async def hardware_watchdog():
    """Close the valve if no valve command or heartbeat arrives in time."""
    while True:
        await asyncio.sleep(WATCHDOG_POLL_INTERVAL_SECONDS)
        try:
            if valve is None:
                continue

            elapsed = time.time() - _last_valve_command_time
            if elapsed <= WATCHDOG_TIMEOUT_SECONDS:
                continue

            position = await asyncio.to_thread(valve.get_position)
            if position <= 0:
                continue

            logger.warning(
                f"Hardware watchdog triggered: no valve command for {elapsed:.1f}s "
                f"(timeout {WATCHDOG_TIMEOUT_SECONDS}s), position {position}. Closing valve."
            )
            await asyncio.to_thread(valve.return_to_start)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Hardware watchdog error: {e}")
        finally:
            # Re-arm regardless of outcome so a wedged valve doesn't spam retries
            # faster than the timeout.
            if time.time() - _last_valve_command_time > WATCHDOG_TIMEOUT_SECONDS:
                feed_watchdog()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global valve, scale
    logger.info("Initializing valve...")
    valve = create_valve()
    logger.info("Valve initialized")
    feed_watchdog()

    watchdog_task = asyncio.create_task(hardware_watchdog())

    logger.info("Initializing scale...")
    scale = create_scale()
    logger.info("Scale initialized")

    yield

    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass

    if valve:
        valve.release()
        logger.info("Shutting down, released valve")

    if scale:
        scale.disconnect()
        logger.info("Shutting down, disconnected scale")


app = FastAPI(title="BrewCTL Hardware API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Hello World from BrewCTL Hardware"}


@app.get("/health")
async def health():
    valve_health = {"available": False, "position": None}
    try:
        if valve:
            position = await asyncio.to_thread(valve.get_position)
            valve_health = {"available": True, "position": position}
    except Exception as e:
        logger.error(f"Error checking valve health: {e}")

    scale_health = {
        "connected": False,
        "weight": None,
        "units": None,
        "battery_pct": None,
    }
    try:
        if scale and scale.connected:
            scale_health = await asyncio.to_thread(_read_scale_status)
    except Exception as e:
        logger.error(f"Error checking scale health: {e}")

    return {
        "status": "healthy",
        "mode": "hardware",
        "valve": valve_health,
        "scale": scale_health,
    }


# === Valve Endpoints ===


@app.post("/api/valve/heartbeat")
async def heartbeat():
    """
    Keepalive for the watchdog. A controller holding the valve open must call this
    more often than WATCHDOG_TIMEOUT_SECONDS, otherwise the valve is closed.
    """
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    feed_watchdog()
    position = await asyncio.to_thread(valve.get_position)
    return {
        "status": "ok",
        "position": position,
        "watchdog_timeout_seconds": WATCHDOG_TIMEOUT_SECONDS,
    }


def _check_nudge_rate_limit():
    global _nudge_last_call_time
    with _nudge_lock:
        current_time = time.time()
        if current_time - _nudge_last_call_time < NUDGE_MIN_INTERVAL_SECONDS:
            raise HTTPException(
                status_code=429,
                detail=f"nudge too frequent, wait {NUDGE_MIN_INTERVAL_SECONDS} seconds",
            )
        _nudge_last_call_time = current_time


@app.post("/api/valve/nudge/open")
async def nudge_open():
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    _check_nudge_rate_limit()
    feed_watchdog()

    logger.info("Valve nudge open")
    await asyncio.to_thread(valve.step_forward)
    await asyncio.sleep(0.1)
    position = await asyncio.to_thread(valve.get_position)
    feed_watchdog()
    return {"status": "nudged_open", "position": position}


@app.post("/api/valve/nudge/close")
async def nudge_close():
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    _check_nudge_rate_limit()
    feed_watchdog()

    logger.info("Valve nudge close")
    await asyncio.to_thread(valve.step_backward)
    await asyncio.sleep(0.1)
    position = await asyncio.to_thread(valve.get_position)
    feed_watchdog()
    return {"status": "nudged_closed", "position": position}


@app.post("/api/valve/return_to_start")
async def return_to_start():
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    feed_watchdog()
    logger.info("Valve returning to start")
    await asyncio.to_thread(valve.return_to_start)
    position = await asyncio.to_thread(valve.get_position)
    feed_watchdog()
    return {"status": "returned_to_start", "position": position}


@app.post("/api/valve/release")
async def release():
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    feed_watchdog()
    logger.info("Valve released")
    await asyncio.to_thread(valve.release)
    position = await asyncio.to_thread(valve.get_position)
    feed_watchdog()
    return {"status": "released", "position": position}


@app.get("/api/valve/position")
async def get_position():
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    return {"position": await asyncio.to_thread(valve.get_position)}


@app.get("/api/valve/status")
async def get_status():
    if valve is None:
        return {"available": False, "position": None, "status": "not_initialized"}

    try:
        position = await asyncio.to_thread(valve.get_position)
        return {"available": True, "position": position, "status": "ready"}
    except Exception as e:
        logger.error(f"Error getting valve status: {e}")
        return {
            "available": False,
            "position": None,
            "status": "error",
            "error": str(e),
        }


async def sse_valve_status_generator() -> AsyncGenerator[str, None]:
    """SSE generator for real-time valve status updates."""
    try:
        while True:
            if valve is None:
                yield f"data: {json.dumps({'error': 'valve not available'})}\n\n"
                await asyncio.sleep(VALVE_SSE_INTERVAL)
                continue

            try:
                position = await asyncio.to_thread(valve.get_position)
                status = {"available": True, "position": position}
            except Exception as e:
                logger.error(f"Error getting valve position in SSE: {e}")
                status = {"available": False, "position": None, "error": str(e)}

            yield f"data: {json.dumps(status)}\n\n"
            await asyncio.sleep(VALVE_SSE_INTERVAL)
    except asyncio.CancelledError:
        logger.info("SSE valve status connection closed by client")
        raise


@app.get("/sse/valve/status")
async def sse_valve_status():
    """SSE endpoint for real-time valve status updates."""
    return StreamingResponse(
        sse_valve_status_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# === Scale Endpoints ===


def _read_scale_status() -> dict:
    """Read all scale values. Blocking (BLE) -- call via asyncio.to_thread."""
    connected = scale.connected
    return {
        "connected": connected,
        "weight": scale.get_weight() if connected else None,
        "units": scale.get_units() if connected else None,
        "battery_pct": scale.get_battery_percentage() if connected else None,
    }


async def sse_scale_status_generator() -> AsyncGenerator[str, None]:
    """SSE generator for real-time scale status updates."""
    try:
        while True:
            if scale is None:
                yield f"data: {json.dumps({'error': 'scale not available'})}\n\n"
                await asyncio.sleep(SCALE_SSE_INTERVAL)
                continue

            status = await asyncio.to_thread(_read_scale_status)
            yield f"data: {json.dumps(status)}\n\n"
            await asyncio.sleep(SCALE_SSE_INTERVAL)
    except asyncio.CancelledError:
        logger.info("SSE scale status connection closed by client")
        raise


@app.get("/sse/scale/status")
async def sse_scale_status():
    """SSE endpoint for real-time scale status updates."""
    return StreamingResponse(
        sse_scale_status_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/scale/status")
async def get_scale_status():
    if scale is None:
        raise HTTPException(status_code=503, detail="scale not available")

    return await asyncio.to_thread(_read_scale_status)


@app.post("/api/scale/connect")
async def connect_scale():
    if scale is None:
        logger.info("scale is none")
        raise HTTPException(status_code=503, detail="scale not available")

    await asyncio.to_thread(scale.connect)
    return {"status": "connected" if scale.connected else "failed"}


@app.post("/api/scale/disconnect")
async def disconnect_scale():
    if scale is None:
        raise HTTPException(status_code=503, detail="scale not available")

    await asyncio.to_thread(scale.disconnect)
    return {"status": "disconnected"}
