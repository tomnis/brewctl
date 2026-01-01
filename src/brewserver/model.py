from pydantic import BaseModel

from config import *
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class ValveCommand(Enum):
    NOOP = 0
    FORWARD = 1
    BACKWARD = 2


@dataclass
class StartBrewRequest(BaseModel):
    target_flow_rate: float = COLDBREW_TARGET_FLOW_RATE
    scale_interval: float = COLDBREW_SCALE_READ_INTERVAL
    valve_interval: float = COLDBREW_VALVE_INTERVAL_SECONDS
    epsilon: float = COLDBREW_EPSILON
    # strategy: str


class BrewStatusRecord(BaseModel):
    brew_id: str
    timestamp: datetime
    current_flow_rate: float
    current_weight: float
