import asyncio
import uuid
import time

from contextlib import asynccontextmanager
from log import logger
from fastapi import FastAPI, Query, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import validator
from typing import Annotated

# from config import *
from scale import AbstractScale
from brew_strategy import DefaultBrewStrategy
from model import *
from valve import AbstractValve
from time_series import AbstractTimeSeries
from time_series import InfluxDBTimeSeries
from datetime import datetime, timezone

cur_brew_id = None


def create_scale() -> AbstractScale:
    if COLDBREW_IS_PROD:
        logger.info("Initializing production scale...")
        from pi.LunarScale import LunarScale
        s: AbstractScale = LunarScale(COLDBREW_SCALE_MAC_ADDRESS)
    else:
        logger.info("Initializing mock scale...")
        from scale import MockScale
        s: AbstractScale = MockScale()
    return s


def create_valve() -> AbstractValve:
    if COLDBREW_IS_PROD:
        logger.info("Initializing production valve...")
        from pi.MotorKitValve import MotorKitValve
        v: AbstractValve = MotorKitValve()
    else:
        logger.info("Initializing mock valve...")
        from valve import MockValve
        v: AbstractValve = MockValve()
    return v


def create_time_series() -> InfluxDBTimeSeries:
    logger.info("Initializing InfluxDB time series...")

    ts: AbstractTimeSeries = InfluxDBTimeSeries(
        url=COLDBREW_INFLUXDB_URL,
        token=COLDBREW_INFLUXDB_TOKEN,
        org=COLDBREW_INFLUXDB_ORG,
        bucket=COLDBREW_INFLUXDB_BUCKET,
    )
    return ts


scale = create_scale()
valve = create_valve()
time_series = create_time_series()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Try our best to manage the scale connection, but restart is finicky
    We don't need to eagerly connect to the scale here, just make sure we disconnect on shutdown
    """
    logger.info("lifespan: server startup complete, yielding control")
    yield
    if scale is not None:
        scale.disconnect()
    logger.info("Shutting down, disconnected scale...")
    valve.release()
    logger.info("Shutting down, released valve ...")


"""
Main place for pi-side logic. Webserver handles incoming requests acting as a "proxy" of sorts for both the scale and valve.
Prefer to use start/end endpoints as those are the simplest.
Acquire/release endpoints can be used for clients to implement their own fine-grained brewing logic.

Kill endpoints are also provided to forcefully kill an in-progress brew. 
"""
app = FastAPI(lifespan=lifespan)

origins = [
    "http://localhost:5173",
    COLDBREW_FRONTEND_API_URL,
    "localhost:5173"
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)



def get_scale_status() -> ScaleStatus:
    """
    Reads status from the scale. Used for both a specific endpoint, and polling+writing scale data as part of the event loop.
    """
    # good enough to support reconnection here. we can just powercycle the scale if anything goes wrong to get back on track
    global scale
    if scale is None or not scale.connected:
        scale = create_scale()
        scale.connect()

    if scale.connected:
        weight = scale.get_weight()
        battery_pct = scale.get_battery_percentage()
        units = scale.get_units()
        return ScaleStatus(connected=True, weight=weight, units=units, battery_pct=battery_pct)
    else:
        return ScaleStatus(connected=False, weight=None, units=None, battery_pct=None)

@app.get("/api/scale")
def read_scale():
    return get_scale_status()


#### BREW ENDPOINTS ####
class MatchBrewId(BaseModel):
    """ Middleware to match brew_id. Used to restrict execution to matching id pairs."""
    brew_id: str
    @validator('brew_id')
    def brew_id_must_match(cls, v):
        global cur_brew_id
        # logger.info(f"cur brew id: {cur_brew_id}")
        if cur_brew_id is None:
            raise ValueError('no brew_id in progress')
        elif v != cur_brew_id:
            raise ValueError('wrong brew_id')
        return v.title()


async def collect_scale_data_task(brew_id, s):
    """Collect scale data every s seconds while brew_id matches current brew id."""
    global cur_brew_id
    while brew_id is not None and brew_id == cur_brew_id:
        scale_state = get_scale_status()
        # logger.info(f"Scale state: {scale_state}")
        weight = scale_state.weight
        battery_pct = scale_state.battery_pct
        if weight is not None and battery_pct is not None:
            # logger.info(f"Brew ID: (writing influxdb data) {cur_brew_id} Weight: {weight}, Battery: {battery_pct}%")
            # TODO could add a brew_id label here
            time_series.write_scale_data(weight, battery_pct)
        await asyncio.sleep(s)



async def brew_step_task(brew_id, strategy):
    """brew"""
    global cur_brew_id
    while brew_id is not None and brew_id == cur_brew_id:
        # get the current flow rate
        current_flow_rate = time_series.get_current_flow_rate()
        (valve_command, interval) = strategy.step(current_flow_rate)
        if valve_command == ValveCommand.FORWARD:
            valve.step_forward()
        elif valve_command == ValveCommand.BACKWARD:
            valve.step_backward()
        await asyncio.sleep(interval)



@app.post("/api/brew/start")
async def start_brew(req: StartBrewRequest | None = None):
    logger.info(f"brew start request: {req}")
    """Start a brew with the given brew ID."""
    global cur_brew_id
    if cur_brew_id is None:
        new_id = str(uuid.uuid4())
        cur_brew_id = new_id
        if req is None:
            strategy = DefaultBrewStrategy()
        else:
            strategy = DefaultBrewStrategy.from_request(req)

        # logger.info(f"strategy: {str(strategy)}")

        # start scale read and brew tasks
        asyncio.create_task(collect_scale_data_task(cur_brew_id, COLDBREW_SCALE_READ_INTERVAL))
        asyncio.create_task(brew_step_task(new_id, strategy))
        return {"status": "started", "brew_id": cur_brew_id}
    else:
        raise HTTPException(status_code=409, detail="brew already in progress")

@app.post("/api/brew/stop")
async def stop_brew(brew_id: Annotated[MatchBrewId, Query()]):
    """Politely stops the given brew."""
    return await release_brew(brew_id)


@app.get("/api/brew/status")
async def brew_status():
    """Gets the current brew status."""
    global cur_brew_id
    brew_id = cur_brew_id
    if brew_id is None:
        return {"status": "no brew in progress"}
    else:
        timestamp = datetime.now(timezone.utc)
        current_flow_rate = time_series.get_current_flow_rate()
        current_weight = scale.get_weight()
        if current_weight is None:
            res = {"status": "scale not connected"}
        elif current_flow_rate is None:
            res = {"status": "insufficient data for flow rate"}
        else:
            res = BrewStatus(brew_id=brew_id, timestamp=timestamp, current_flow_rate=current_flow_rate, current_weight=current_weight)
        return res




# use acquire/release semantics to start scale data collection but expected to manage brew logic clientside
@app.post("/api/brew/acquire")
async def acquire_brew():
    """Acquire the brew valve for exclusive use."""
    global cur_brew_id
    if cur_brew_id is None:
        new_id = str(uuid.uuid4())
        cur_brew_id = new_id
        # start a scale thread
        asyncio.create_task(collect_scale_data_task(cur_brew_id, COLDBREW_SCALE_READ_INTERVAL))
        return {"status": "valve acquired", "brew_id": new_id}  # Placeholder response
    else:
        # logger.info(f"brew id {cur_brew_id} already acquired")
        return {"status": "valve already acquired"}  # Placeholder response kkk

@app.post("/api/brew/release")
async def release_brew(brew_id: Annotated[MatchBrewId, Query()]):
    """Gracefully release the current brew."""
    global cur_brew_id
    global scale

    old_id = cur_brew_id
    # TODO probably don't want to do this here, could cause some kind of conflict
    # edge case with teardown before anything has happened
    #valve.return_to_start()
    time.sleep(1)
    valve.release()

    scale.disconnect()
    scale = None
    cur_brew_id = None
    return {"status": f"valve brew id ${old_id} released"}  # Placeholder response


@app.post("/api/brew/kill")
async def kill_brew():
    """Forcefully kill the current brew."""
    global cur_brew_id
    logger.info(f"{cur_brew_id} will be killed")
    old_id = cur_brew_id
    if old_id is not None:
        cur_brew_id = None
        valve.return_to_start()
        valve.release()
        return {"status": "killed", "brew_id": old_id}
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no brew in progress")


# TODO maybe not needed? might be better to just use the status end point
@app.get("/api/brew/flow_rate")
def read_flow_rate():
    """Read the current flow rate from the time series."""
    flow_rate = time_series.get_current_flow_rate()
    return {"brew_id": cur_brew_id, "flow_rate": flow_rate}


@app.post("/api/brew/valve/forward")
def step_forward(brew_id: Annotated[MatchBrewId, Query()],):
    """Step the valve forward one step."""
    valve.step_forward()
    time.sleep(0.1)
    return {"status": f"stepped forward one step"}

@app.post("/api/brew/valve/backward")
def step_backward(brew_id: Annotated[MatchBrewId, Query()]):
    """Step the valve backward one step."""
    valve.step_backward()
    time.sleep(0.1)
    return {"status": f"stepped backward 1 step"}



#---- ui endpoints ----#
# for react assets
app.mount("/app/assets", StaticFiles(directory="build/assets"), name="assets")

# catchall for react (must be last?)
@app.get("/app/{full_path:path}")
async def serve_react_app(full_path: str):
    return FileResponse("build/index.html")



# if not COLDBREW_IS_PROD:
if False:
    logger.info("running some tests...")
    import pytest
    exit_code = pytest.main(["--disable-warnings", "-v", "."])