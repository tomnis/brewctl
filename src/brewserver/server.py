import asyncio
import uuid
import time

from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from pydantic import BaseModel, validator
from typing import Annotated

from config import *
from scale import AbstractScale
from brew_strat import DefaultBrewStrategy, ValveCommand
from src.brewserver.model import StartBrewRequest
from model import *
from valve import AbstractValve
from time_series import AbstractTimeSeries
from time_series import InfluxDBTimeSeries
from config import *

cur_brew_id = None

from datetime import datetime, timezone

# Get current date and time in UTC as a timezone-aware object

# TODO dependency injection
def create_scale() -> AbstractScale:
    if COLDBREW_IS_PROD:
        print("Initializing production scale...")
        from pi.LunarScale import LunarScale
        s: AbstractScale = LunarScale(COLDBREW_SCALE_MAC_ADDRESS)
    else:
        print("Initializing mock scale...")
        from scale import MockScale
        s: AbstractScale = MockScale()
    return s


def create_valve() -> AbstractValve:
    if COLDBREW_IS_PROD:
        print("Initializing production valve...")
        from pi.MotorKitValve import MotorKitValve
        v: AbstractValve = MotorKitValve()
    else:
        print("Initializing mock valve...")
        from valve import MockValve
        v: AbstractValve = MockValve()
    return v


def create_time_series() -> AbstractTimeSeries:
    print("Initializing InfluxDB time series...")
    print(f"org = {COLDBREW_INFLUXDB_ORG}")

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
    print("server startup complete")
    yield
    if scale is not None:
        scale.disconnect()
    print("Shutting down, disconnected scale...")
    valve.release()
    print("Shutting down, released valve ...")

app = FastAPI(lifespan=lifespan)


# TODO move this return type to a class or pydantic model
def get_scale_status() -> dict:
    # good enough to support reconnection here. we can just powercycle the scale if anything goes wrong to get back on track
    global scale
    if scale is None or not scale.connected:
        scale = create_scale()
        scale.connect()

    if scale.connected:
        weight = scale.get_weight()
        battery_pct = scale.get_battery_percentage()
        units = scale.get_units()
        return {"scale.connected": True, "weight": weight, "battery_pct": battery_pct, "units": units}
    else:
        return {"scale.connected": False}

@app.get("/scale")
def read_scale():
    return get_scale_status()


#### VALVE ENDPOINTS ####
class MatchBrewId(BaseModel):
    brew_id: str
    @validator('brew_id')
    def brew_id_must_match(cls, v):
        print(f"cur brew id: {cur_brew_id}")
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
        print(f"Scale state: {scale_state}")
        weight = scale_state.get("weight")
        battery_pct = scale_state.get("battery_pct")
        if weight is not None and battery_pct is not None:
            print(f"Brew ID: (writing influxdb data) {cur_brew_id} Weight: {weight}, Battery: {battery_pct}%")
            # TODO could add a brew_id label here
            time_series.write_scale_data(weight, battery_pct)
        await asyncio.sleep(s)



async def brew_step_task(brew_id, strategy):
    """brew"""
    global cur_brew_id
    while brew_id is not None and brew_id == cur_brew_id:
        # TODO implement valve data collection
        # get the current flow rate
        current_flow_rate = time_series.get_current_flow_rate()
        (valve_command, interval) = strategy.step(current_flow_rate)
        if valve_command == ValveCommand.FORWARD:
            valve.step_forward()
        elif valve_command == ValveCommand.BACKWARD:
            valve.step_backward()
        await asyncio.sleep(interval)



# TODO should have an endpoint to get the brew status
@app.post("/brew/start")
async def start_brew(req: StartBrewRequest | None = None):
    print(f"brew start request: {req}")
    """Start a brew with the given brew ID."""
    global cur_brew_id
    if cur_brew_id is None:
        new_id = str(uuid.uuid4())
        cur_brew_id = new_id
        if req is None:
            strategy = DefaultBrewStrategy()
        else:
            strategy = DefaultBrewStrategy.from_request(req)

        print(f"strategy: {str(strategy)}")

        # start scale read and brew tasks
        asyncio.create_task(collect_scale_data_task(cur_brew_id, COLDBREW_SCALE_READ_INTERVAL))
        asyncio.create_task(brew_step_task(new_id, strategy))
        return {"status": "brew started", "brew_id": cur_brew_id}  # Placeholder response
    else:
        return {"status": "brew already in progress"}  # Placeholder response

@app.post("/brew/stop")
async def stop_brew(brew_id: Annotated[MatchBrewId, Query()]):
    return release_brew(brew_id)


@app.get("/brew/status")
async def brew_status():
    global cur_brew_id
    brew_id = cur_brew_id
    if brew_id is None:
        return {"status": "no brew in progress"}
    else:
        timestamp = datetime.now(timezone.utc)
        current_flow_rate = time_series.get_current_flow_rate()
        current_weight = scale.get_weight()
        res = BrewStatusRecord(brew_id=brew_id, timestamp=timestamp, current_flow_rate=current_flow_rate, current_weight=current_weight)
        return res





# use acquire/release semantics to start scale data collection but expected to manage brew logic locally
@app.post("/brew/acquire")
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
        # print(f"brew id {cur_brew_id} already acquired")
        return {"status": "valve already acquired"}  # Placeholder response kkk

@app.post("/brew/release")
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


@app.post("/brew/kill")
async def kill_brew():
    """Forcefully kill the current brew."""
    global cur_brew_id
    old_id = cur_brew_id
    cur_brew_id = None
    return {"status": f"valve brew id ${old_id} killed"}  # Placeholder response


@app.get("/brew/flow_rate")
def read_flow_rate():
    """Read the current flow rate from the time series."""
    flow_rate = time_series.get_current_flow_rate()
    return {"brew_id": cur_brew_id, "flow_rate": flow_rate}


@app.post("/brew/valve/forward")
def step_forward(brew_id: Annotated[MatchBrewId, Query()],):
    """Step the valve forward one step."""
    valve.step_forward()
    time.sleep(0.1)
    return {"status": f"stepped forward one step"}

@app.post("/brew/valve/backward")
def step_backward(brew_id: Annotated[MatchBrewId, Query()]):
    """Step the valve backward one step."""
    valve.step_backward()
    time.sleep(0.1)
    return {"status": f"stepped backward 1 step"}