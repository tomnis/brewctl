from abc import ABC, abstractmethod
from typing import Dict, Any, Type, Tuple, Optional

from config import *
from model import *
from brewctl.log import logger


# Strategy Registry
BREW_STRATEGY_REGISTRY: Dict[BrewStrategyType, Type["AbstractBrewStrategy"]] = {}


def register_strategy(strategy_type: BrewStrategyType):
    """Decorator to register a brew strategy."""
    def decorator(cls: Type["AbstractBrewStrategy"]) -> Type["AbstractBrewStrategy"]:
        BREW_STRATEGY_REGISTRY[strategy_type] = cls
        return cls
    return decorator


def _extract_float(value: Any, default: float) -> float:
    """
    Extract a float from a value that might be a sequence (list/tuple) or already a number.
    
    If value is a sequence, extracts the first element.
    If value is already a number (int/float), returns it directly.
    Otherwise, returns the default.
    """
    if value is None:
        return default
    
    # If it's already a number, return it
    if isinstance(value, (int, float)):
        return float(value)
    
    # If it's a sequence (list/tuple), extract first element
    if isinstance(value, (list, tuple)) and len(value) > 0:
        first = value[0]
        if isinstance(first, (int, float)):
            return float(first)
    
    # Log warning and return default
    import logging
    logging.getLogger(__name__).warning(
        f"Could not extract float from {type(value).__name__}: {value}, using default: {default}"
    )
    return default


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


def create_brew_strategy(strategy_type: BrewStrategyType, params: Dict[str, Any], base_params: Dict[str, Any]) -> "AbstractBrewStrategy":
    """Factory function to create a brew strategy from the registry."""
    if strategy_type not in BREW_STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy type: {strategy_type}. Available: {list(BREW_STRATEGY_REGISTRY.keys())}")
    return BREW_STRATEGY_REGISTRY[strategy_type].from_params(params, base_params)


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
        msg = f"current_flow_rate: {current_flow_rate_str}"
        if current_flow_rate is None:
            logger.warning(f"{msg}")
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
