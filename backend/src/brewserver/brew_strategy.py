from abc import ABC, abstractmethod
import math
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
            ki=strategy_params.get("ki", 0.05),
            kd=strategy_params.get("kd", 0.1),
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


@register_strategy(BrewStrategyType.MPC)
class MPCBrewStrategy(AbstractBrewStrategy):
    """
    Model Predictive Control (MPC) for flow rate stabilization.
    
    MPC uses a model of the system to predict future behavior and optimizes
    control actions over a prediction horizon. At each timestep:
    1. Predict future flow rates over horizon using plant model
    2. Solve optimization to minimize cost (error + control effort)
    3. Apply only the first control action
    4. Repeat with updated measurements
    
    This approach handles constraints naturally and provides better
    performance than reactive controllers for systems with delays.
    
    Parameters:
        - horizon: Number of future timesteps to predict
        - plant_gain: Steady-state flow rate change per valve step
        - plant_time_constant: First-order time constant
        - q_error: Weight on tracking error in cost function
        - q_control: Weight on control effort (prevents aggressive moves)
        - q_delta: Weight on control rate (smoothness)
    """
    
    def __init__(self, target_flow_rate: float, scale_interval: float, valve_interval: float,
                 target_weight: float, vessel_weight: float,
                 horizon: int, plant_gain: float, plant_time_constant: float,
                 q_error: float, q_control: float, q_delta: float,
                 output_min: float = -10.0, output_max: float = 10.0):
        self.target_flow_rate = target_flow_rate
        self.scale_interval = scale_interval
        self.valve_interval = valve_interval
        self.target_weight = target_weight
        self.vessel_weight = vessel_weight
        self.coffee_target = target_weight - vessel_weight
        
        # MPC parameters
        self.horizon = horizon
        self.plant_gain = plant_gain
        self.plant_time_constant = plant_time_constant
        
        # Cost function weights
        self.q_error = q_error
        self.q_control = q_control
        self.q_delta = q_delta
        
        # Output limits
        self.output_min = output_min
        self.output_max = output_max
        
        # Plant model state
        self.model_state = 0.0  # Current modeled flow rate
        self.prev_control = 0.0  # Previous control action
        
        # State tracking
        self.prev_timestamp = None
        self.is_initialized = False
        
        # History for debugging
        self.history = []

    @classmethod
    def get_params_schema(cls) -> Dict[str, Any]:
        return {
            "horizon": {"type": "number", "default": 15, "label": "Prediction Horizon",
                       "description": "Number of future timesteps to predict"},
            "plant_gain": {"type": "number", "default": 0.01, "label": "Plant Gain",
                          "description": "Steady-state flow rate change per valve step"},
            "plant_time_constant": {"type": "number", "default": 10.0, "label": "Plant Time Constant",
                                  "description": "Time constant of the first-order plant model"},
            "q_error": {"type": "number", "default": 1.0, "label": "Error Weight (Qe)",
                       "description": "Weight on tracking error in cost function"},
            "q_control": {"type": "number", "default": 0.1, "label": "Control Weight (Qu)",
                         "description": "Weight on control effort (prevents aggressive moves)"},
            "q_delta": {"type": "number", "default": 0.5, "label": "Delta Weight (Qd)",
                       "description": "Weight on control rate for smoothness"},
            "output_min": {"type": "number", "default": -10.0, "label": "Output Min"},
            "output_max": {"type": "number", "default": 10.0, "label": "Output Max"},
        }

    @classmethod
    def from_params(cls, strategy_params: Dict[str, Any], base_params: Dict[str, Any]) -> "MPCBrewStrategy":
        return MPCBrewStrategy(
            target_flow_rate=base_params.get("target_flow_rate", COLDBREW_TARGET_FLOW_RATE),
            scale_interval=base_params.get("scale_interval", COLDBREW_SCALE_READ_INTERVAL),
            valve_interval=base_params.get("valve_interval", COLDBREW_VALVE_INTERVAL_SECONDS),
            target_weight=base_params.get("target_weight", COLDBREW_TARGET_WEIGHT_GRAMS),
            vessel_weight=base_params.get("vessel_weight", COLDBREW_VESSEL_WEIGHT_GRAMS),
            horizon=strategy_params.get("horizon", 15),
            plant_gain=strategy_params.get("plant_gain", 0.005),
            plant_time_constant=strategy_params.get("plant_time_constant", 15.0),
            q_error=strategy_params.get("q_error", 1.0),
            q_control=strategy_params.get("q_control", 0.1),
            q_delta=strategy_params.get("q_delta", 0.5),
            output_min=strategy_params.get("output_min", -10.0),
            output_max=strategy_params.get("output_max", 10.0),
        )

    def _predict_plant_response(self, initial_state: float, control_sequence: list, dt: float) -> list:
        """
        Predict plant response over horizon using first-order model.
        
        Model: y[k+1] = alpha * y[k] + (1-alpha) * K * u[k]
        where alpha = exp(-dt/tau)
        """
        predictions = []
        alpha = math.exp(-dt / self.plant_time_constant) if self.plant_time_constant > 0 else 0.0
        state = initial_state
        
        for u in control_sequence:
            # First-order dynamics
            state = alpha * state + (1 - alpha) * self.plant_gain * u
            predictions.append(state)
        
        return predictions

    def _solve_mpc(self, current_flow_rate: float, dt: float) -> float:
        """
        Solve MPC optimization to find optimal control action.
        
        Uses a simple gradient descent approach to minimize the cost function:
        J = sum(q_error * error^2 + q_control * u^2 + q_delta * delta_u^2)
        """
        # Initialize control sequence with previous action
        u_prev = self.prev_control
        u_current = u_prev
        
        # Simple iterative optimization (gradient descent)
        best_u = u_current
        best_cost = float('inf')
        
        # Try multiple candidate control values
        candidates = [u_current + delta for delta in [-2.0, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 2.0]]
        
        for u_candidate in candidates:
            # Clip to output limits
            u_candidate = max(self.output_min, min(self.output_max, u_candidate))
            
            # Build control sequence: first action is candidate, rest are steady
            control_seq = [u_candidate] + [u_candidate] * (self.horizon - 1)
            
            # Predict future flow rates
            predictions = self._predict_plant_response(current_flow_rate, control_seq, dt)
            
            # Compute cost
            cost = 0.0
            for k, predicted_flow in enumerate(predictions):
                error = self.target_flow_rate - predicted_flow
                delta_u = u_candidate - u_prev if k == 0 else 0.0
                
                # Cost = q_error * error^2 + q_control * u^2 + q_delta * delta_u^2
                cost += (self.q_error * error * error + 
                        self.q_control * u_candidate * u_candidate + 
                        self.q_delta * delta_u * delta_u)
            
            if cost < best_cost:
                best_cost = cost
                best_u = u_candidate
        
        return best_u

    def step(self, current_flow_rate: Optional[float], current_weight: Optional[float]) -> Tuple[ValveCommand, int]:
        """Perform a single step using MPC control."""
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
        
        # Calculate time delta
        if self.prev_timestamp is not None:
            dt = current_time - self.prev_timestamp
        else:
            dt = self.valve_interval
            self.model_state = current_flow_rate
            self.is_initialized = True
        
        # Update plant model with actual measurement
        if self.is_initialized:
            alpha = math.exp(-dt / self.plant_time_constant) if self.plant_time_constant > 0 else 0.0
            self.model_state = alpha * self.model_state + (1 - alpha) * self.plant_gain * self.prev_control
        
        # Solve MPC optimization
        output = self._solve_mpc(current_flow_rate, dt)
        
        # Update state
        self.prev_control = output
        self.prev_timestamp = current_time
        
        # Log for debugging
        logger.info(f"MPC: target={self.target_flow_rate:.4f}, current={current_flow_rate:.4f}, "
                   f"model={self.model_state:.4f}, output={output:.4f}")
        
        # Store in history
        self.history.append({
            'time': current_time,
            'flow_rate': current_flow_rate,
            'model': self.model_state,
            'output': output,
        })
        
        # Use a threshold to determine direction
        deadband = 0.1
        if abs(output) < deadband:
            return ValveCommand.NOOP, self.valve_interval * 2
        elif output > 0:
            return ValveCommand.FORWARD, self.valve_interval
        else:
            return ValveCommand.BACKWARD, self.valve_interval


@register_strategy(BrewStrategyType.ADAPTIVE_GAIN_SCHEDULING)
class AdaptiveGainSchedulingBrewStrategy(AbstractBrewStrategy):
    """
    Adaptive Control with Gain Scheduling for flow rate stabilization.
    
    This strategy automatically adjusts PID gains based on the operating region
    (current flow rate). The idea is that different flow conditions may require
    different control behaviors:
    
    - LOW region (startup): Conservative gains to avoid overshoot when starting
    - MEDIUM region (normal operation): Balanced gains for steady-state control
    - HIGH region (high flow): Aggressive gains to handle disturbances
    
    The strategy also includes optional real-time adaptation that can increase
    gains if the error persists, helping the system respond to changes in
    the brewing system (e.g., coffee grind size, temperature, etc.)
    
    Parameters:
        - kp_low, ki_low, kd_low: PID gains for LOW flow region
        - kp_med, ki_med, kd_med: PID gains for MEDIUM flow region  
        - kp_high, ki_high, kd_high: PID gains for HIGH flow region
        - flow_rate_low_threshold: Upper bound of LOW region (g/s)
        - flow_rate_high_threshold: Lower bound of HIGH region (g/s)
        - adaptation_enabled: Whether to enable real-time gain adaptation
        - adaptation_rate: Rate at which gains adjust based on sustained error
    """
    
    def __init__(self, target_flow_rate: float, scale_interval: float, valve_interval: float,
                 target_weight: float, vessel_weight: float,
                 kp_low: float, ki_low: float, kd_low: float,
                 kp_med: float, ki_med: float, kd_med: float,
                 kp_high: float, ki_high: float, kd_high: float,
                 flow_rate_low_threshold: float, flow_rate_high_threshold: float,
                 adaptation_enabled: bool = True, adaptation_rate: float = 0.01,
                 output_min: float = -10.0, output_max: float = 10.0,
                 integral_limit: float = 100.0):
        self.target_flow_rate = target_flow_rate
        self.scale_interval = scale_interval
        self.valve_interval = valve_interval
        self.target_weight = target_weight
        self.vessel_weight = vessel_weight
        self.coffee_target = target_weight - vessel_weight
        
        # Gain scheduling tables - one set of gains per region
        self.gains = {
            'low': {'kp': kp_low, 'ki': ki_low, 'kd': kd_low},
            'med': {'kp': kp_med, 'ki': ki_med, 'kd': kd_med},
            'high': {'kp': kp_high, 'ki': ki_high, 'kd': kd_high},
        }
        
        # Current active gains (may be adapted in real-time)
        self.kp = kp_low
        self.ki = ki_low
        self.kd = kd_low
        
        # Region thresholds
        self.flow_rate_low_threshold = flow_rate_low_threshold
        self.flow_rate_high_threshold = flow_rate_high_threshold
        
        # Current region tracking
        self.current_region = 'low'
        
        # Adaptation settings
        self.adaptation_enabled = adaptation_enabled
        self.adaptation_rate = adaptation_rate
        self.sustained_error_count = 0
        self.adaptation_factor = 1.0
        
        # PID state
        self.integral = 0.0
        self.prev_error = 0.0
        self.prev_timestamp = None
        
        # Output limits
        self.output_min = output_min
        self.output_max = output_max
        self.integral_limit = integral_limit
        
        # History for debugging
        self.history = []

    @classmethod
    def get_params_schema(cls) -> Dict[str, Any]:
        return {
            # LOW region gains (startup)
            "kp_low": {"type": "number", "default": 0.5, "label": "Kp (Low Region)",
                       "description": "Proportional gain for low flow rates (startup)"},
            "ki_low": {"type": "number", "default": 0.05, "label": "Ki (Low Region)",
                       "description": "Integral gain for low flow rates (startup)"},
            "kd_low": {"type": "number", "default": 0.02, "label": "Kd (Low Region)",
                       "description": "Derivative gain for low flow rates (startup)"},
            
            # MEDIUM region gains (normal operation)
            "kp_med": {"type": "number", "default": 1.5, "label": "Kp (Medium Region)",
                       "description": "Proportional gain for medium flow rates"},
            "ki_med": {"type": "number", "default": 0.15, "label": "Ki (Medium Region)",
                       "description": "Integral gain for medium flow rates"},
            "kd_med": {"type": "number", "default": 0.08, "label": "Kd (Medium Region)",
                       "description": "Derivative gain for medium flow rates"},
            
            # HIGH region gains (high flow)
            "kp_high": {"type": "number", "default": 2.5, "label": "Kp (High Region)",
                        "description": "Proportional gain for high flow rates"},
            "ki_high": {"type": "number", "default": 0.25, "label": "Ki (High Region)",
                        "description": "Integral gain for high flow rates"},
            "kd_high": {"type": "number", "default": 0.1, "label": "Kd (High Region)",
                        "description": "Derivative gain for high flow rates"},
            
            # Region thresholds
            "flow_rate_low_threshold": {"type": "number", "default": 0.03,
                                        "label": "Low→Medium Threshold (g/s)",
                                        "description": "Flow rate threshold for switching from low to medium gains"},
            "flow_rate_high_threshold": {"type": "number", "default": 0.07,
                                         "label": "Medium→High Threshold (g/s)",
                                         "description": "Flow rate threshold for switching from medium to high gains"},
            
            # Adaptation settings
            "adaptation_enabled": {"type": "boolean", "default": True,
                                   "label": "Enable Real-time Adaptation",
                                   "description": "Allow gains to adapt in real-time based on sustained error"},
            "adaptation_rate": {"type": "number", "default": 0.01,
                                "label": "Adaptation Rate",
                                "description": "How fast gains adapt when sustained error is detected"},
            
            "output_min": {"type": "number", "default": -10.0, "label": "Output Min"},
            "output_max": {"type": "number", "default": 10.0, "label": "Output Max"},
            "integral_limit": {"type": "number", "default": 100.0, "label": "Integral Limit"},
        }

    @classmethod
    def from_params(cls, strategy_params: Dict[str, Any], base_params: Dict[str, Any]) -> "AdaptiveGainSchedulingBrewStrategy":
        return AdaptiveGainSchedulingBrewStrategy(
            target_flow_rate=base_params.get("target_flow_rate", COLDBREW_TARGET_FLOW_RATE),
            scale_interval=base_params.get("scale_interval", COLDBREW_SCALE_READ_INTERVAL),
            valve_interval=base_params.get("valve_interval", COLDBREW_VALVE_INTERVAL_SECONDS),
            target_weight=base_params.get("target_weight", COLDBREW_TARGET_WEIGHT_GRAMS),
            vessel_weight=base_params.get("vessel_weight", COLDBREW_VESSEL_WEIGHT_GRAMS),
            
            kp_low=strategy_params.get("kp_low", 0.5),
            ki_low=strategy_params.get("ki_low", 0.05),
            kd_low=strategy_params.get("kd_low", 0.02),
            
            kp_med=strategy_params.get("kp_med", 1.5),
            ki_med=strategy_params.get("ki_med", 0.15),
            kd_med=strategy_params.get("kd_med", 0.08),
            
            kp_high=strategy_params.get("kp_high", 2.5),
            ki_high=strategy_params.get("ki_high", 0.25),
            kd_high=strategy_params.get("kd_high", 0.1),
            
            flow_rate_low_threshold=strategy_params.get("flow_rate_low_threshold", 0.03),
            flow_rate_high_threshold=strategy_params.get("flow_rate_high_threshold", 0.07),
            
            adaptation_enabled=strategy_params.get("adaptation_enabled", True),
            adaptation_rate=strategy_params.get("adaptation_rate", 0.01),
            
            output_min=strategy_params.get("output_min", -10.0),
            output_max=strategy_params.get("output_max", 10.0),
            integral_limit=strategy_params.get("integral_limit", 100.0),
        )

    def _determine_region(self, flow_rate: float) -> str:
        """Determine which region we're operating in based on flow rate."""
        if flow_rate < self.flow_rate_low_threshold:
            return 'low'
        elif flow_rate > self.flow_rate_high_threshold:
            return 'high'
        else:
            return 'med'

    def _update_gains(self, flow_rate: float, error: float):
        """Update active gains based on current region and optional adaptation."""
        # Determine target region
        new_region = self._determine_region(flow_rate)
        
        if new_region != self.current_region:
            logger.info(f"Gain Scheduling: Switching from {self.current_region} to {new_region} region "
                       f"(flow_rate={flow_rate:.4f})")
            self.current_region = new_region
            # Reset adaptation factor on region change
            self.adaptation_factor = 1.0
            self.sustained_error_count = 0
        
        # Get base gains for current region
        base_gains = self.gains[self.current_region]
        
        # Apply real-time adaptation if enabled
        if self.adaptation_enabled:
            # Check for sustained error (same sign as target = we need more/less flow)
            if abs(error) > 0.01:  # Threshold for meaningful error
                self.sustained_error_count += 1
                if self.sustained_error_count > 5:  # After 5+ steps of sustained error
                    # Gradually increase gains to respond more aggressively
                    self.adaptation_factor = min(2.0, self.adaptation_factor + self.adaptation_rate)
            else:
                # Reset adaptation when error is small
                self.sustained_error_count = 0
                self.adaptation_factor = max(1.0, self.adaptation_factor - self.adaptation_rate * 2)
        
        # Apply adaptation factor to gains
        self.kp = base_gains['kp'] * self.adaptation_factor
        self.ki = base_gains['ki'] * self.adaptation_factor
        self.kd = base_gains['kd'] * self.adaptation_factor

    def _compute_pid(self, error: float, dt: float) -> float:
        """Compute PID output using current (potentially adapted) gains."""
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
        """Perform a single step using adaptive gain scheduling."""
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
        
        # Update gains based on current operating region and adaptation
        self._update_gains(current_flow_rate, error)
        
        # Compute PID output using current gains
        output = self._compute_pid(error, dt)
        
        # Update state
        self.prev_error = error
        self.prev_timestamp = current_time
        
        # Log for debugging
        logger.info(f"AdaptiveGain: target={self.target_flow_rate:.4f}, current={current_flow_rate:.4f}, "
                   f"error={error:.4f}, region={self.current_region}, "
                   f"kp={self.kp:.3f}, ki={self.ki:.3f}, kd={self.kd:.3f}, "
                   f"adaptation={self.adaptation_factor:.2f}, output={output:.4f}")
        
        # Store in history
        self.history.append({
            'time': current_time,
            'flow_rate': current_flow_rate,
            'error': error,
            'region': self.current_region,
            'kp': self.kp,
            'ki': self.ki,
            'kd': self.kd,
            'output': output,
        })
        
        # Use a threshold to determine direction
        deadband = 0.1
        if abs(output) < deadband:
            return ValveCommand.NOOP, self.valve_interval * 2
        elif output > 0:
            return ValveCommand.FORWARD, self.valve_interval
        else:
            return ValveCommand.BACKWARD, self.valve_interval


class SmithPredictorAdvancedBrewStrategy(AbstractBrewStrategy):
    """
    Smith Predictor (Advanced) controller for flow rate stabilization.
    
    This strategy uses a Smith Predictor architecture to compensate for time delays
    in the system. It consists of:
    1. A process model (FOPDT - First Order Plus Dead Time) that predicts the plant output
    2. A delay element that accounts for transport delay
    3. A Kalman filter for noise reduction on measurements
    4. A PID controller for error correction
    
    The Smith Predictor predicts what the flow rate will be in the future (after the
    dead time has passed), allowing the controller to act proactively rather than
    reactively responding to delayed measurements.
    
    Parameters:
        - kp, ki, kd: PID controller gains
        - dead_time: The transport delay in seconds (time between valve command and effect)
        - plant_gain: The static gain of the plant (steady-state flow rate / valve position)
        - plant_time_constant: The time constant of the first-order plant model
        - q, r: Kalman filter parameters for noise reduction
    """
    
    def __init__(self, target_flow_rate: float, scale_interval: float, valve_interval: float,
                 target_weight: float, vessel_weight: float,
                 kp: float, ki: float, kd: float,
                 dead_time: float, plant_gain: float, plant_time_constant: float,
                 q: float, r: float,
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
        
        # Smith Predictor parameters
        self.dead_time = dead_time  # Transport delay in seconds
        self.plant_gain = plant_gain  # Static gain of the plant
        self.plant_time_constant = plant_time_constant  # Time constant of first-order model
        
        # Internal plant model state (for prediction)
        self.model_output = 0.0  # Model's prediction of current output
        self.delay_buffer = []  # Buffer to store delayed control signals
        self.delay_samples = max(1, int(dead_time / valve_interval))  # Number of samples to delay
        
        # Kalman filter for smoothing flow rate
        self.kalman = KalmanFilter(q=q, r=r, initial_estimate=target_flow_rate)
        
        # History for debugging/logging
        self.history = []

    @classmethod
    def get_params_schema(cls) -> Dict[str, Any]:
        return {
            "kp": {"type": "number", "default": 1.0, "label": "Proportional Gain (Kp)",
                   "description": "Controls response to current error"},
            "ki": {"type": "number", "default": 0.1, "label": "Integral Gain (Ki)",
                   "description": "Controls response to accumulated error"},
            "kd": {"type": "number", "default": 0.05, "label": "Derivative Gain (Kd)",
                   "description": "Controls response to rate of error change"},
            "dead_time": {"type": "number", "default": 30.0, "label": "Dead Time (seconds)",
                         "description": "Transport delay between valve command and effect on flow rate"},
            "plant_gain": {"type": "number", "default": 0.01, "label": "Plant Gain",
                          "description": "Steady-state flow rate change per unit valve position"},
            "plant_time_constant": {"type": "number", "default": 10.0, "label": "Plant Time Constant",
                                   "description": "Time constant of the first-order plant model"},
            "q": {"type": "number", "default": 0.001, "label": "Kalman Process Noise (Q)",
                   "description": "How much the flow naturally varies. Higher = more responsive to changes"},
            "r": {"type": "number", "default": 0.1, "label": "Kalman Measurement Noise (R)",
                   "description": "How noisy the sensor readings are. Higher = more smoothing"},
            "output_min": {"type": "number", "default": -10.0, "label": "Output Min"},
            "output_max": {"type": "number", "default": 10.0, "label": "Output Max"},
            "integral_limit": {"type": "number", "default": 100.0, "label": "Integral Limit"},
        }

    @classmethod
    def from_params(cls, strategy_params: Dict[str, Any], base_params: Dict[str, Any]) -> "SmithPredictorAdvancedBrewStrategy":
        return SmithPredictorAdvancedBrewStrategy(
            target_flow_rate=base_params.get("target_flow_rate", COLDBREW_TARGET_FLOW_RATE),
            scale_interval=base_params.get("scale_interval", COLDBREW_SCALE_READ_INTERVAL),
            valve_interval=base_params.get("valve_interval", COLDBREW_VALVE_INTERVAL_SECONDS),
            target_weight=base_params.get("target_weight", COLDBREW_TARGET_WEIGHT_GRAMS),
            vessel_weight=base_params.get("vessel_weight", COLDBREW_VESSEL_WEIGHT_GRAMS),
            kp=strategy_params.get("kp", 1.0),
            ki=strategy_params.get("ki", 0.05),
            kd=strategy_params.get("kd", 0.1),
            dead_time=strategy_params.get("dead_time", 45.0),
            plant_gain=strategy_params.get("plant_gain", 0.005),
            plant_time_constant=strategy_params.get("plant_time_constant", 15.0),
            q=strategy_params.get("q", 0.0005),
            r=strategy_params.get("r", 0.15),
            output_min=strategy_params.get("output_min", -10.0),
            output_max=strategy_params.get("output_max", 10.0),
            integral_limit=strategy_params.get("integral_limit", 100.0),
        )

    def _update_plant_model(self, valve_command: float, dt: float):
        """
        Update the internal plant model using a first-order model.
        
        Model: G(s) = K / (tau * s + 1)
        Discrete: y[k] = alpha * y[k-1] + (1 - alpha) * K * u[k-delay]
        
        where alpha = exp(-dt/tau)
        """
        # First-order filter coefficient
        alpha = math.exp(-dt / self.plant_time_constant) if self.plant_time_constant > 0 else 0.0
        
        # Get the delayed control signal from buffer
        delayed_control = self.delay_buffer[0] if len(self.delay_buffer) > 0 else 0.0
        
        # Update model output using first-order dynamics
        self.model_output = alpha * self.model_output + (1 - alpha) * self.plant_gain * delayed_control
        
        # Update delay buffer: add current command, remove oldest
        self.delay_buffer.append(valve_command)
        if len(self.delay_buffer) > self.delay_samples:
            self.delay_buffer.pop(0)

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
        """Perform a single step using Smith Predictor control."""
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
        
        # Calculate time delta
        if self.prev_timestamp is not None:
            dt = current_time - self.prev_timestamp
        else:
            dt = self.valve_interval
            # Initialize model on first step
            self.model_output = current_flow_rate
        
        # Apply Kalman filter to smooth the flow rate
        filtered_flow_rate = self.kalman.update(current_flow_rate)
        
        # Update the internal plant model with previous control action
        # (Use a neutral command as initial, will be updated for next iteration)
        if self.prev_timestamp is not None:
            # Use last PID output as the valve command for model update
            last_command = self._compute_pid(self.prev_error, dt) if self.prev_error != 0 else 0.0
            self._update_plant_model(last_command, dt)
        
        # Smith Predictor: Use model prediction instead of delayed actual measurement
        # The model predicts what the output would be without delay
        predicted_flow_rate = self.model_output
        
        # Calculate error using the predicted flow rate (Smith Predictor advantage)
        error = self.target_flow_rate - predicted_flow_rate
        
        # Also calculate error from actual filtered measurement for monitoring
        actual_error = self.target_flow_rate - filtered_flow_rate
        
        # Compute PID output using the predicted error
        output = self._compute_pid(error, dt)
        
        # Update state
        self.prev_error = error
        self.prev_timestamp = current_time
        
        # Log for debugging
        logger.info(f"SmithPredictor: target={self.target_flow_rate:.4f}, "
                   f"raw={current_flow_rate:.4f}, filtered={filtered_flow_rate:.4f}, "
                   f"model={predicted_flow_rate:.4f}, pred_error={error:.4f}, "
                   f"actual_error={actual_error:.4f}, output={output:.4f}")
        
        # Store in history for debugging
        self.history.append({
            'time': current_time,
            'raw': current_flow_rate,
            'filtered': filtered_flow_rate,
            'model': predicted_flow_rate,
            'error': error,
            'output': output,
        })
        
        # Use a threshold to determine direction
        # Small outputs within deadband = no action
        deadband = 0.1
        if abs(output) < deadband:
            return ValveCommand.NOOP, self.valve_interval * 2
        elif output > 0:
            return ValveCommand.FORWARD, self.valve_interval
        else:
            return ValveCommand.BACKWARD, self.valve_interval


# Register the Smith Predictor Advanced strategy
register_strategy(BrewStrategyType.SMITH_PREDICTOR_ADVANCED)(SmithPredictorAdvancedBrewStrategy)


class KalmanFilter:
    """
    A simple 1D Kalman Filter for smoothing flow rate measurements.
    
    State: x = flow rate (g/s)
    Process model: x_k = x_{k-1} + w (random walk)
    Measurement model: z_k = x_k + v (noisy observation)
    
    Parameters:
        q: Process noise covariance (how much the flow naturally varies)
        r: Measurement noise covariance (how noisy our sensor readings are)
    """
    
    def __init__(self, q: float = 0.001, r: float = 0.1, initial_estimate: float = 0.0, initial_error: float = 1.0):
        self.q = q  # Process noise covariance
        self.r = r  # Measurement noise covariance
        
        self.x = initial_estimate  # Current state estimate
        self.p = initial_error      # Current estimate error covariance
        self.is_initialized = initial_error < 1e9  # Have we received our first measurement?
    
    def update(self, measurement: float) -> float:
        """
        Update the filter with a new measurement.
        
        Args:
            measurement: The raw flow rate reading from the sensor
            
        Returns:
            The filtered (smoothed) flow rate estimate
        """
        if measurement is None:
            return self.x
        
        if not self.is_initialized:
            # First measurement - just use it as our initial estimate
            self.x = measurement
            self.p = self.r
            self.is_initialized = True
            return self.x
        
        # Prediction step: predict current state and error
        # Since we're using a random walk model, x_pred = x_prev
        x_pred = self.x
        p_pred = self.p + self.q
        
        # Update step: incorporate the measurement
        # Kalman gain
        k = p_pred / (p_pred + self.r)
        
        # Update state estimate
        self.x = x_pred + k * (measurement - x_pred)
        
        # Update error estimate
        self.p = (1 - k) * p_pred
        
        return self.x
    
    def reset(self):
        """Reset the filter to its initial state."""
        self.x = 0.0
        self.p = 1.0
        self.is_initialized = False


@register_strategy(BrewStrategyType.KALMAN_PID)
class KalmanPIDBrewStrategy(AbstractBrewStrategy):
    """
    PID controller with Kalman Filter for flow rate stabilization.
    
    Uses a Kalman Filter to smooth out noisy scale readings before
    passing them to the PID controller. This reduces jitter and
    provides more stable control.
    """
    
    def __init__(self, target_flow_rate: float, scale_interval: float, valve_interval: float,
                 target_weight: float, vessel_weight: float,
                 kp: float, ki: float, kd: float,
                 q: float, r: float,
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
        
        # Kalman filter for smoothing flow rate
        self.kalman = KalmanFilter(q=q, r=r, initial_estimate=target_flow_rate)

    @classmethod
    def get_params_schema(cls) -> Dict[str, Any]:
        return {
            "kp": {"type": "number", "default": 1.0, "label": "Proportional Gain (Kp)",
                   "description": "Controls response to current error"},
            "ki": {"type": "number", "default": 0.1, "label": "Integral Gain (Ki)",
                   "description": "Controls response to accumulated error"},
            "kd": {"type": "number", "default": 0.05, "label": "Derivative Gain (Kd)",
                   "description": "Controls response to rate of error change"},
            "q": {"type": "number", "default": 0.001, "label": "Kalman Process Noise (Q)",
                   "description": "How much the flow naturally varies. Higher = more responsive to changes"},
            "r": {"type": "number", "default": 0.1, "label": "Kalman Measurement Noise (R)",
                   "description": "How noisy the sensor readings are. Higher = more smoothing"},
            "output_min": {"type": "number", "default": -10.0, "label": "Output Min"},
            "output_max": {"type": "number", "default": 10.0, "label": "Output Max"},
            "integral_limit": {"type": "number", "default": 100.0, "label": "Integral Limit"},
        }

    @classmethod
    def from_params(cls, strategy_params: Dict[str, Any], base_params: Dict[str, Any]) -> "KalmanPIDBrewStrategy":
        return KalmanPIDBrewStrategy(
            target_flow_rate=base_params.get("target_flow_rate", COLDBREW_TARGET_FLOW_RATE),
            scale_interval=base_params.get("scale_interval", COLDBREW_SCALE_READ_INTERVAL),
            valve_interval=base_params.get("valve_interval", COLDBREW_VALVE_INTERVAL_SECONDS),
            target_weight=base_params.get("target_weight", COLDBREW_TARGET_WEIGHT_GRAMS),
            vessel_weight=base_params.get("vessel_weight", COLDBREW_VESSEL_WEIGHT_GRAMS),
            kp=strategy_params.get("kp", 1.0),
            ki=strategy_params.get("ki", 0.05),
            kd=strategy_params.get("kd", 0.1),
            q=strategy_params.get("q", 0.0005),
            r=strategy_params.get("r", 0.15),
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
        """Perform a single step using Kalman-filtered PID control."""
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
        
        # Apply Kalman filter to smooth the flow rate
        filtered_flow_rate = self.kalman.update(current_flow_rate)
        
        # Calculate error using the filtered flow rate
        error = self.target_flow_rate - filtered_flow_rate
        
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
        logger.info(f"KalmanPID: target={self.target_flow_rate:.4f}, raw={current_flow_rate:.4f}, "
                   f"filtered={filtered_flow_rate:.4f}, error={error:.4f}, output={output:.4f}")
        
        # Use a threshold to determine direction
        # Small outputs within deadband = no action
        deadband = 0.1
        if abs(output) < deadband:
            return ValveCommand.NOOP, self.valve_interval * 2
        elif output > 0:
            return ValveCommand.FORWARD, self.valve_interval
        else:
            return ValveCommand.BACKWARD, self.valve_interval
