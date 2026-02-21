from pydantic import BaseModel

from brewserver.config import *
from config import *
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any


class BrewStrategyType(str, Enum):
    DEFAULT = "default"
    PID = "pid"
    KALMAN_PID = "kalman_pid"
    SMITH_PREDICTOR_ADVANCED = "smith_predictor_advanced"
    ADAPTIVE_GAIN_SCHEDULING = "adaptive_gain_scheduling"
    MPC = "mpc"


class BrewState(str, Enum):
    IDLE = "idle"
    BREWING = "brewing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


class ValveCommand(Enum):
    NOOP = 0
    FORWARD = 1
    BACKWARD = 2
    STOP = 3


class ScaleStatus(BaseModel):
    connected: bool
    weight: Optional[float] = None
    units: Optional[str] = None
    battery_pct: Optional[int] = None


@dataclass
class Brew:
    id: str
    status: BrewState
    time_started: datetime
    vessel_weight: float
    target_weight: float
    time_completed: Optional[datetime] = None
    error_message: Optional[str] = None


@dataclass
class StartBrewRequest(BaseModel):
    target_flow_rate: float = COLDBREW_TARGET_FLOW_RATE
    scale_interval: float = COLDBREW_SCALE_READ_INTERVAL
    valve_interval: float = COLDBREW_VALVE_INTERVAL_SECONDS
    target_weight: float = COLDBREW_TARGET_WEIGHT_GRAMS
    vessel_weight: float = COLDBREW_VESSEL_WEIGHT_GRAMS
    epsilon: float = COLDBREW_EPSILON
    strategy: BrewStrategyType = BrewStrategyType.DEFAULT
    strategy_params: Dict[str, Any] = {}


# TODO add startbrewresponse


class BrewStatus(BaseModel):
    brew_id: str
    brew_state: BrewState
    time_started: datetime
    time_completed: Optional[datetime] = None
    target_weight: float
    timestamp: datetime
    current_flow_rate: Optional[float] = None
    current_weight: Optional[float] = None
    estimated_time_remaining: Optional[float] = None
    error_message: Optional[str] = None
    valve_position: Optional[int] = None  # 0-199 for one full rotation
