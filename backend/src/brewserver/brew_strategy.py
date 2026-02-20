from abc import ABC, abstractmethod
from typing import Tuple, Optional, Dict, Any, Type

from config import *
from model import *


# Strategy Registry
BREW_STRATEGY_REGISTRY: Dict[BrewStrategyType, Type["AbstractBrewStrategy"]] = {}


def register_strategy(strategy_type: BrewStrategyType):
    """Decorator to register a brew strategy."""
    def decorator(cls: Type["AbstractBrewStrategy"]) -> Type["AbstractBrewStrategy"]:
        BREW_STRATEGY_REGISTRY[strategy_type] = cls
        return cls
    return decorator


def create_brew_strategy(strategy_type: BrewStrategyType, params: Dict[str, Any], base_params: Dict[str, Any]) -> "AbstractBrewStrategy":
    """Factory function to create a brew strategy from the registry."""
    if strategy_type not in BREW_STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy type: {strategy_type}. Available: {list(BREW_STRATEGY_REGISTRY.keys())}")
    return BREW_STRATEGY_REGISTRY[strategy_type].from_params(params, base_params)


class AbstractBrewStrategy(ABC):
    """encapsulates a brewing strategy for controlling the brew process. assumes that lock strategy has already been handled"""

    @abstractmethod
    def step(self, flow_rate: Optional[float], current_weight: Optional[float]) -> Tuple[ValveCommand, int]:
        """Perform a single step in the brewing strategy. """
        pass

    @classmethod
    @abstractmethod
    def get_params_schema(cls) -> Dict[str, Any]:
        """Return JSON schema for strategy-specific parameters."""
        pass

    @classmethod
    @abstractmethod
    def from_params(cls, strategy_params: Dict[str, Any], base_params: Dict[str, Any]) -> "AbstractBrewStrategy":
        """Create strategy instance from strategy params and base params."""
        pass


@register_strategy(BrewStrategyType.DEFAULT)
class DefaultBrewStrategy(AbstractBrewStrategy):
    """A simple default brewing strategy, naively opening or closing the valve based on the current flow rate."""

    def __init__(self, target_flow_rate: float = None, scale_interval: float = None, valve_interval: float = None, 
                 epsilon: float = None, target_weight: float = None, vessel_weight: float = None):
        # Set defaults
        if target_flow_rate is None:
            target_flow_rate = COLDBREW_TARGET_FLOW_RATE
        if scale_interval is None:
            scale_interval = COLDBREW_SCALE_READ_INTERVAL
        if valve_interval is None:
            valve_interval = COLDBREW_VALVE_INTERVAL_SECONDS
        if epsilon is None:
            epsilon = COLDBREW_EPSILON
        if target_weight is None:
            target_weight = COLDBREW_TARGET_WEIGHT_GRAMS
        if vessel_weight is None:
            vessel_weight = COLDBREW_VESSEL_WEIGHT_GRAMS
        
        self.target_flow_rate = target_flow_rate
        self.scale_interval = scale_interval
        self.valve_interval = valve_interval
        self.epsilon = epsilon
        self.target_weight = target_weight
        self.vessel_weight = vessel_weight
        self.coffee_target = target_weight - vessel_weight

    @classmethod
    def get_params_schema(cls) -> Dict[str, Any]:
        """Return JSON schema for default strategy parameters (none needed)."""
        return {}

    @classmethod
    def from_params(cls, strategy_params: Dict[str, Any], base_params: Dict[str, Any]) -> "DefaultBrewStrategy":
        return DefaultBrewStrategy(
            target_flow_rate=base_params.get("target_flow_rate", COLDBREW_TARGET_FLOW_RATE),
            scale_interval=base_params.get("scale_interval", COLDBREW_SCALE_READ_INTERVAL),
            valve_interval=base_params.get("valve_interval", COLDBREW_VALVE_INTERVAL_SECONDS),
            epsilon=base_params.get("epsilon", COLDBREW_EPSILON),
            target_weight=base_params.get("target_weight", COLDBREW_TARGET_WEIGHT_GRAMS),
            vessel_weight=base_params.get("vessel_weight", COLDBREW_VESSEL_WEIGHT_GRAMS),
        )

    @classmethod
    def from_request(cls, req: StartBrewRequest) -> "DefaultBrewStrategy":
        return DefaultBrewStrategy(
            target_flow_rate=req.target_flow_rate,
            scale_interval=req.scale_interval,
            valve_interval=req.valve_interval,
            epsilon=req.epsilon,
            target_weight=req.target_weight,
            vessel_weight=req.vessel_weight,
        )

    def step(self, current_flow_rate: Optional[float], current_weight: Optional[float]) -> Tuple[ValveCommand, int]:
        """Perform a single step in the default brewing strategy."""
        coffee_weight = (current_weight - self.vessel_weight) if current_weight is not None else None
        if coffee_weight is not None and coffee_weight >= self.coffee_target:
            logger.info(f"target weight reached: {coffee_weight}g (coffee) >= {self.coffee_target}g (coffee target)")
            return ValveCommand.STOP, 0
        
        current_flow_rate_str = "None" if current_flow_rate is None else f"{current_flow_rate:.4f}g/s"
        msg = f"current flow rate: {current_flow_rate_str}"
        if current_flow_rate is None:
            logger.info("result is none")
            return ValveCommand.NOOP, self.valve_interval
        elif abs(self.target_flow_rate - current_flow_rate) <= self.epsilon:
            logger.info(f"{msg} (just right)")
            return ValveCommand.NOOP, self.valve_interval * 2
        elif current_flow_rate <= self.target_flow_rate:
            logger.info(f"{msg} (too slow)")
            return ValveCommand.FORWARD, self.valve_interval
        else:
            logger.info(f"{msg} (too fast)")
            return ValveCommand.BACKWARD, self.valve_interval


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
            target_flow_rate=base_params.get("target_flow_rate", COLDBREW_TARGET_FLOW_RATE),
            scale_interval=base_params.get("scale_interval", COLDBREW_SCALE_READ_INTERVAL),
            valve_interval=base_params.get("valve_interval", COLDBREW_VALVE_INTERVAL_SECONDS),
            target_weight=base_params.get("target_weight", COLDBREW_TARGET_WEIGHT_GRAMS),
            vessel_weight=base_params.get("vessel_weight", COLDBREW_VESSEL_WEIGHT_GRAMS),
            kp=strategy_params.get("kp", 1.0),
            ki=strategy_params.get("ki", 0.1),
            kd=strategy_params.get("kd", 0.05),
            output_min=strategy_params.get("output_min", -10.0),
            output_max=strategy_params.get("output_max", 10.0),
            integral_limit=strategy_params.get("integral_limit", 100.0),
        )

    def _compute_pid(self, error: float, dt: float) -> float:
        """Compute PID output."""
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
