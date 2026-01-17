from pydantic import BaseModel

from brewserver.config import *
from config import *
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class ValveCommand(Enum):
    NOOP = 0
    FORWARD = 1
    BACKWARD = 2


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
    epsilon: float = COLDBREW_EPSILON
    # TODO strategy: str

# TODO add startbrewresponse


# TODO rename to just brew status
class BrewStatus(BaseModel):
    brew_id: str
    timestamp: datetime
    current_flow_rate: float
    current_weight: float
    # TODO add ETA, time started
