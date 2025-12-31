import uuid
import time

from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, Path
from pydantic import BaseModel, validator
from typing import Tuple, Annotated

from ..base.config import *
from ..base.scale import Scale
from ..base.valve import Valve

min_steps = 1
max_steps = 16
cur_brew_id = None

# TODO dependency injection

def initialize_scale() -> Scale:
    if COLDBREW_IS_PROD:
        print("Initializing production scale...")
        from ..brewcontroller.LunarScale import LunarScale
        s: Scale = LunarScale(COLDBREW_SCALE_MAC_ADDRESS)
    else:
        print("Initializing mock scale...")
        from ..base.scale import MockScale
        s: Scale = MockScale()
    return s


def initialize_valve() -> Valve:
    if COLDBREW_IS_PROD:
        print("Initializing production valve...")
        from ..brewcontroller.MotorKitValve import MotorKitValve
        v: Valve = MotorKitValve()
    else:
        print("Initializing mock valve...")
        from ..base.valve import MockValve
        v: Valve= MockValve()
    return v

scale = initialize_scale()
valve = initialize_valve()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("server startup complete")
    yield
    scale.disconnect()
    print("Shutting down, disconnected scale...")
    valve.release()
    print("Shutting down, released valve ...")

app = FastAPI(lifespan=lifespan)


@app.get("/scale")
def read_weight():
    global scale
    if not scale.connected:
        scale = initialize_scale()
        scale.connect()
    weight = scale.get_weight()
    battery_pct = scale.get_battery_percentage()
    units = scale.get_units()
    return {"weight": weight, "battery_pct": battery_pct, "units": units}  # Placeholder value in grams


# TODO doesn't seem like this works when reconnecting
# TODO investigate calling scale.disconnect then scale.connect in sequence
# tests:
# - scale is turned off during brew, then turned back on, should be able to reconnect
# - server process restarts due to crash or update, should be able to reconnect
# restarting the server won't work, we do need to handle gracefully
# - disconnect
# TODO i guess just to be safe we need to powercycle the scale
# we should be able to power cycle the scale and have the server reconnect
@app.post("/scale/refresh")
def refresh_scale_connection():
    if scale.connected:
        scale.disconnect()
        time.sleep(5.0)
    scale.connect()
    return {"status": "scale connection refreshed"}  # Placeholder response





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

@app.post("/valve/acquire")
def acquire_valve(q: str | None = None):
    global cur_brew_id
    if cur_brew_id is None:
        new_id = str(uuid.uuid4())
        cur_brew_id = new_id
        return {"status": "valve acquired", "brew_id": new_id}  # Placeholder response
    else:
        print(f"brew id {cur_brew_id} already acquired")
        return {"status": "valve already acquired"}  # Placeholder response

@app.post("/valve/release")
# TODO accept release brew id and verify matches
def release_valve(brew_id: Annotated[MatchBrewId, Query()]):
    global cur_brew_id
    old_id = cur_brew_id
    cur_brew_id = None
    return {"status": f"valve brew id ${old_id} released"}  # Placeholder response



@app.post("/valve/forward/{num_steps}")
def step_forward(
        num_steps: Annotated[int, Path(title="number of steps on stepper motor", ge=min_steps, le=max_steps)],
        brew_id: Annotated[MatchBrewId, Query()],
):
    #print(f"cur brew id: {cur_brew_id}")
    #print(f"query param: q={brew_id}")
    for i in range(num_steps):
        valve.step_forward()
        time.sleep(0.1)
    return {"status": f"stepped forward {num_steps} step(s)"}  # Placeholder response

@app.post("/valve/backward/{num_steps}")
def step_backward(
        num_steps: Annotated[int, Path(title="number of steps on stepper motor", ge=min_steps, le=max_steps)],
        brew_id: Annotated[MatchBrewId, Query()],
):
    #print(f"cur brew id: {cur_brew_id}")
    #print(f"query param: q={brew_id}")
    for i in range(num_steps):
        valve.step_backward()
        time.sleep(0.1)
    return {"status": f"stepped backward {num_steps} step(s)"}  # Placeholder response