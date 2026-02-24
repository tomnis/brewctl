from typing import Dict, Any, Tuple, Optional

from config import *
from model import ValveCommand, BrewStrategyType
from brewctl.log import logger
from brewctl.strategies.DefaultBrewStrategy import (
    AbstractBrewStrategy,
    register_strategy,
    _extract_float,
)


@register_strategy(BrewStrategyType.PID)
class PIDBrewStrategy(AbstractBrewStrategy):
    """PID (Proportional-Integral-Derivative) controller for flow rate stabilization."""

    def __init__(self, target_flow_rate: float, scale_interval: float, valve_interval: float,
                 target_weight: float, vessel_weight: float,
                 kp: float, ki: float, kd: float,
                 output_min: float = -10.0, output_max: float = 10.0,
                 integral_limit: float = 100.0):
        self.target_flow_rate = target_flow_rate
        self.scale_interval = scale_interval
        self.valve_interval = valve_interval
        self.target_weight = target_weight
        self.vessel_weight = vessel_weight
        self.coffee_target = target_weight - vessel_weight
        
        # PID parameters
        self.kp = kp
        self.ki = ki
        self.kd = kd
        
        # PID state
        self.integral = 0.0
        self.prev_error = 0.0
        self.prev_timestamp = None
        
        # Output limits
        self.output_min = output_min
        self.output_max = output_max
        self.integral_limit = integral_limit

    @classmethod
    def get_params_schema(cls) -> Dict[str, Any]:
        return {
            "kp": {"type": "number", "default": 1.0, "label": "Proportional Gain (Kp)",
                   "description": "Controls response to current error"},
            "ki": {"type": "number", "default": 0.1, "label": "Integral Gain (Ki)",
                   "description": "Controls response to accumulated error"},
            "kd": {"type": "number", "default": 0.05, "label": "Derivative Gain (Kd)",
                   "description": "Controls response to rate of error change"},
            "output_min": {"type": "number", "default": -10.0, "label": "Output Min"},
            "output_max": {"type": "number", "default": 10.0, "label": "Output Max"},
            "integral_limit": {"type": "number", "default": 100.0, "label": "Integral Limit"},
        }

    @classmethod
    def from_params(cls, strategy_params: Dict[str, Any], base_params: Dict[str, Any]) -> "PIDBrewStrategy":
        return PIDBrewStrategy(
            target_flow_rate=float(base_params.get("target_flow_rate", COLDBREW_TARGET_FLOW_RATE)),
            scale_interval=float(base_params.get("scale_interval", COLDBREW_SCALE_READ_INTERVAL)),
            valve_interval=float(base_params.get("valve_interval", COLDBREW_VALVE_INTERVAL_SECONDS)),
            target_weight=float(base_params.get("target_weight", COLDBREW_TARGET_WEIGHT_GRAMS)),
            vessel_weight=float(base_params.get("vessel_weight", COLDBREW_VESSEL_WEIGHT_GRAMS)),
            kp=_extract_float(strategy_params.get("kp"), 1.0),
            ki=_extract_float(strategy_params.get("ki"), 0.1),
            kd=_extract_float(strategy_params.get("kd"), 0.05),
            output_min=_extract_float(strategy_params.get("output_min"), -10.0),
            output_max=_extract_float(strategy_params.get("output_max"), 10.0),
            integral_limit=_extract_float(strategy_params.get("integral_limit"), 100.0),
        )

    def _compute_pid(self, error: float, dt: float) -> float:
        """Compute PID output."""
        # Validate that gains are numeric (not sequences) to prevent cryptic errors
        if not isinstance(self.kp, (int, float)):
            raise TypeError(f"kp must be a number, got {type(self.kp).__name__}: {self.kp}")
        if not isinstance(self.ki, (int, float)):
            raise TypeError(f"ki must be a number, got {type(self.ki).__name__}: {self.ki}")
        if not isinstance(self.kd, (int, float)):
            raise TypeError(f"kd must be a number, got {type(self.kd).__name__}: {self.kd}")
        
        # Proportional term
        p_term = self.kp * error
        
        # Integral term with anti-windup
        self.integral += error * dt
        self.integral = max(-self.integral_limit, min(self.integral_limit, self.integral_limit))
        i_term = self.ki * self.integral
        
        # Derivative term
        if dt > 0:
            d_term = self.kd * (error - self.prev_error) / dt
        else:
            d_term = 0.0
        
        # Total output
        output = p_term + i_term + d_term
        output = max(self.output_min, min(self.output_max, output))
        
        return output

    def step(self, current_flow_rate: Optional[float], current_weight: Optional[float]) -> Tuple[ValveCommand, int]:
        """Perform a single step using PID control."""
        import time
        current_time = time.time()
        
        # Check target weight
        coffee_weight = (current_weight - self.vessel_weight) if current_weight is not None else None
        if coffee_weight is not None and coffee_weight >= self.coffee_target:
            logger.info(f"target weight reached: {coffee_weight}g >= {self.coffee_target}g")
            return ValveCommand.STOP, 0
        
        if current_flow_rate is None:
            logger.info("flow rate unavailable, noop")
            return ValveCommand.NOOP, self.valve_interval
        
        # Calculate error
        error = self.target_flow_rate - current_flow_rate
        
        # Calculate time delta
        if self.prev_timestamp is not None:
            dt = current_time - self.prev_timestamp
        else:
            dt = self.valve_interval
        
        # Compute PID output
        output = self._compute_pid(error, dt)
        
        # Update state
        self.prev_error = error
        self.prev_timestamp = current_time
        
        # Map output to valve command
        # Positive output = need more flow = open valve (FORWARD)
        # Negative output = too much flow = close valve (BACKWARD)
        logger.info(f"PID: target={self.target_flow_rate:.4f}, current={current_flow_rate:.4f}, "
                   f"error={error:.4f}, output={output:.4f}")
        
        # Use a threshold to determine direction
        # Small outputs within deadband = no action
        deadband = 0.1
        if abs(output) < deadband:
            return ValveCommand.NOOP, self.valve_interval * 2
        elif output > 0:
            return ValveCommand.FORWARD, self.valve_interval
        else:
            return ValveCommand.BACKWARD, self.valve_interval
