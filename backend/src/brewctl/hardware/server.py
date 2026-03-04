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


scale: AbstractScale = None  # create_scale()
valve: AbstractValve = create_valve()

NUDGE_MIN_INTERVAL_SECONDS = 2.0
_nudge_last_call_time = 0.0
_nudge_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global valve, scale
    logger.info("Initializing valve...")
    valve = create_valve()
    logger.info("Valve initialized")

    logger.info("Initializing scale...")
    scale = create_scale()
    logger.info("Scale initialized")

    yield

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
            position = valve.get_position()
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
            scale_health = {
                "connected": scale.connected,
                "weight": scale.get_weight(),
                "units": scale.get_units(),
                "battery_pct": scale.get_battery_percentage(),
            }
    except Exception as e:
        logger.error(f"Error checking scale health: {e}")

    return {
        "status": "healthy",
        "mode": "hardware",
        "valve": valve_health,
        "scale": scale_health,
    }


# === Valve Endpoints ===


@app.post("/api/valve/nudge/open")
async def nudge_open():
    global _nudge_last_call_time

    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    with _nudge_lock:
        current_time = time.time()
        if current_time - _nudge_last_call_time < NUDGE_MIN_INTERVAL_SECONDS:
            raise HTTPException(
                status_code=429,
                detail=f"nudge too frequent, wait {NUDGE_MIN_INTERVAL_SECONDS} seconds",
            )
        _nudge_last_call_time = current_time

    logger.info("Valve nudge open")
    valve.step_forward()
    time.sleep(0.1)
    return {"status": "nudged_open", "position": valve.get_position()}


@app.post("/api/valve/nudge/close")
async def nudge_close():
    global _nudge_last_call_time

    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    with _nudge_lock:
        current_time = time.time()
        if current_time - _nudge_last_call_time < NUDGE_MIN_INTERVAL_SECONDS:
            raise HTTPException(
                status_code=429,
                detail=f"nudge too frequent, wait {NUDGE_MIN_INTERVAL_SECONDS} seconds",
            )
        _nudge_last_call_time = current_time

    logger.info("Valve nudge close")
    valve.step_backward()
    time.sleep(0.1)
    return {"status": "nudged_closed", "position": valve.get_position()}


@app.post("/api/valve/return_to_start")
async def return_to_start():
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    logger.info("Valve returning to start")
    valve.return_to_start()
    return {"status": "returned_to_start", "position": valve.get_position()}


@app.post("/api/valve/release")
async def release():
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    logger.info("Valve released")
    valve.release()
    return {"status": "released", "position": valve.get_position()}


@app.get("/api/valve/position")
async def get_position():
    if valve is None:
        raise HTTPException(status_code=503, detail="valve not available")

    return {"position": valve.get_position()}


@app.get("/api/valve/status")
async def get_status():
    if valve is None:
        return {"available": False, "position": None, "status": "not_initialized"}

    try:
        position = valve.get_position()
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
                position = valve.get_position()
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

async def sse_scale_status_generator() -> AsyncGenerator[str, None]:
    """SSE generator for real-time scale status updates."""
    try:
        while True:
            if scale is None:
                yield f"data: {json.dumps({'error': 'scale not available'})}\n\n"
                await asyncio.sleep(SCALE_SSE_INTERVAL)
                continue

            status = {
                "connected": scale.connected,
                "weight": scale.get_weight() if scale.connected else None,
                "units": scale.get_units() if scale.connected else None,
                "battery_pct": scale.get_battery_percentage()
                if scale.connected
                else None,
            }
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

    return {
        "connected": scale.connected,
        "weight": scale.get_weight() if scale.connected else None,
        "units": scale.get_units() if scale.connected else None,
        "battery_pct": scale.get_battery_percentage() if scale.connected else None,
    }


@app.post("/api/scale/connect")
async def connect_scale():
    if scale is None:
        raise HTTPException(status_code=503, detail="scale not available")

    scale.connect()
    return {"status": "connected" if scale.connected else "failed"}


@app.post("/api/scale/disconnect")
async def disconnect_scale():
    if scale is None:
        raise HTTPException(status_code=503, detail="scale not available")

    scale.disconnect()
    return {"status": "disconnected"}
