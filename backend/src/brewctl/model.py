from pydantic import BaseModel

from brewctl.config import *
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


# ==================== Error Response Models ====================

class ErrorSeverity(str, Enum):
    """Severity level for errors."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(str, Enum):
    """Category of error for better frontend handling."""
    SCALE = "scale"
    VALVE = "valve"
    TIMESERIES = "timeseries"
    BREW = "brew"
    NETWORK = "network"
    HARDWARE = "hardware"
    CONFIGURATION = "configuration"


class BrewErrorResponse(BaseModel):
    """Enhanced error response for frontend consumption."""
    error: str
    error_detailed: Optional[str] = None
    category: ErrorCategory
    severity: ErrorSeverity
    timestamp: datetime
    retryable: bool
    brew_id: Optional[str] = None
    recovery_suggestion: Optional[str] = None
    # Original exception type for debugging
    exception_type: Optional[str] = None


class ScaleStatus(BaseModel):
    connected: bool
    weight: Optional[float] = None
    units: Optional[str] = None
    battery_pct: Optional[int] = None


class Brew(BaseModel):
    id: str
    status: BrewState
    time_started: datetime
    vessel_weight: float
    target_weight: float
    strategy: BrewStrategyType = BrewStrategyType.DEFAULT
    time_completed: Optional[datetime] = None
    error_message: Optional[str] = None

    def to_brew_status(
        self,
        timestamp: datetime,
        current_flow_rate: Optional[float] = None,
        current_weight: Optional[float] = None,
        estimated_time_remaining: Optional[float] = None,
        valve_position: Optional[int] = None,
    ) -> "BrewStatus":
        """Convert internal Brew state to API response BrewStatus."""
        return BrewStatus(
            brew_id=self.id,
            brew_state=self.status,
            brew_strategy=self.strategy,
            time_started=self.time_started,
            time_completed=self.time_completed,
            target_weight=self.target_weight,
            timestamp=timestamp,
            current_flow_rate=current_flow_rate,
            current_weight=current_weight,
            estimated_time_remaining=estimated_time_remaining,
            error_message=self.error_message,
            valve_position=valve_position,
        )


@dataclass
class StartBrewRequest(BaseModel):
    target_flow_rate: float = BREWCTL_TARGET_FLOW_RATE
    scale_interval: float = BREWCTL_SCALE_READ_INTERVAL
    valve_interval: float = BREWCTL_VALVE_INTERVAL_SECONDS
    target_weight: float = BREWCTL_TARGET_WEIGHT_GRAMS
    vessel_weight: float = BREWCTL_VESSEL_WEIGHT_GRAMS
    epsilon: float = BREWCTL_EPSILON
    strategy: BrewStrategyType = BrewStrategyType.DEFAULT
    strategy_params: Dict[str, Any] = {}


# Response Models

class StartBrewResponse(BaseModel):
    status: str
    brew_id: str


class BrewCommandResponse(BaseModel):
    status: str
    brew_id: Optional[str] = None
    brew_state: Optional[BrewState] = None


class FlowRateResponse(BaseModel):
    brew_id: Optional[str] = None
    flow_rate: Optional[float] = None


class BrewStatus(BaseModel):
    brew_id: str
    brew_state: BrewState
    brew_strategy: BrewStrategyType
    time_started: datetime
    time_completed: Optional[datetime] = None
    target_weight: float
    timestamp: datetime
    current_flow_rate: Optional[float] = None
    current_weight: Optional[float] = None
    estimated_time_remaining: Optional[float] = None
    error_message: Optional[str] = None
    valve_position: Optional[int] = None  # 0-199 for one full rotation


# ==================== Health Check Models ====================

class HealthStatus(str, Enum):
    """Health status of the system."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthResponse(BaseModel):
    """Response model for the health check endpoint."""
    status: HealthStatus
    scale: dict  # connected, battery_pct
    valve: dict  # available
    influxdb: dict  # connected, error message if any
    brew: dict  # in_progress, brew_id, status
    timestamp: datetime
