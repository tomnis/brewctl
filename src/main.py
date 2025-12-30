from config import *
from fastapi import FastAPI
from typing import Tuple

from scale import Scale
from valve import Valve

app = FastAPI()


def initialize_hardware() -> Tuple[Scale, Valve]:
    if COLDBREW_IS_PROD:
        from LunarScale import LunarScale
        from MotorKitValve import MotorKitValve
        s: Scale = LunarScale(COLDBREW_SCALE_MAC_ADDRESS)
        v: Valve = MotorKitValve()
    else:
        from scale import MockScale
        from valve import MockValve
        s: Scale = MockScale()
        v: Valve= MockValve()
    return s, v

scale, valve = initialize_hardware()

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/scale")
def read_weight():
    weight = scale.get_weight()
    battery_pct = scale.get_battery_percentage()
    units = scale.get_units()
    return {"weight": weight, "battery_pct": battery_pct, "units": units}  # Placeholder value in grams

@app.post("/valve/step_forward")
def step_forward():
    valve.step_forward()
    return {"status": "stepped forward"}  # Placeholder response

@app.post("/valve/step_backward")
def step_backward():
    valve.step_backward()
    return {"status": "stepped backward"}  # Placeholder response

@app.post("/valve/return_to_start")
def return_to_start():
    valve.return_to_start()
    return {"status": "returned to start"}  # Placeholder response




