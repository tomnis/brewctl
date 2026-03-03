import time
import threading

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from brewctl.core.log import logger
from brewctl.core.valve import create_valve, AbstractValve
from brewctl.hardware.config import BREWCTL_VALVE_MOTOR_NUMBER


valve: AbstractValve = None

NUDGE_MIN_INTERVAL_SECONDS = 2.0
_nudge_last_call_time = 0.0
_nudge_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global valve
    logger.info("Initializing valve...")
    valve = create_valve()
    logger.info("Valve initialized")
    yield
    if valve:
        valve.release()
        logger.info("Shutting down, released valve")


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
    return {"status": "healthy", "mode": "hardware", "valve": valve_health}


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
