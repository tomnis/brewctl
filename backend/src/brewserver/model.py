from pydantic import BaseModel

from brewserver.config import *
from config import *
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class BrewState(str, Enum):
    IDLE = "idle"
    BREWING = "brewing"
    PAUSED = "paused"
    COMPLETED = "completed"


class ValveCommand(Enum):
    NOOP = 0
    FORWARD = 1
    BACKWARD = 2
    STOP = 3


class ScaleStatus(BaseModel):
    connected: bool
    weight: float
    units: str
    battery_pct: int

@dataclass
class StartBrewRequest(BaseModel):
    target_flow_rate: float = COLDBREW_TARGET_FLOW_RATE
    scale_interval: float = COLDBREW_SCALE_READ_INTERVAL
    valve_interval: float = COLDBREW_VALVE_INTERVAL_SECONDS
    target_weight: float = COLDBREW_TARGET_WEIGHT_GRAMS
    epsilon: float = COLDBREW_EPSILON
    # TODO strategy: str

# TODO add startbrewresponse


class BrewStatus(BaseModel):
    brew_id: str
    brew_state: BrewState
    timestamp: datetime
    current_flow_rate: float
    current_weight: float
    # TODO add ETA, time started
