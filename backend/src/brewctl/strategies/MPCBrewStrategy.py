import math
from typing import Dict, Any, Tuple, Optional

from config import *
from model import ValveCommand, BrewStrategyType
from brewctl.log import logger
from brewctl.strategies.DefaultBrewStrategy import (
    AbstractBrewStrategy,
    register_strategy,
    _extract_float,
)


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
            target_flow_rate=base_params.get("target_flow_rate", BREWCTL_TARGET_FLOW_RATE),
            scale_interval=base_params.get("scale_interval", BREWCTL_SCALE_READ_INTERVAL),
            valve_interval=base_params.get("valve_interval", BREWCTL_VALVE_INTERVAL_SECONDS),
            target_weight=base_params.get("target_weight", BREWCTL_TARGET_WEIGHT_GRAMS),
            vessel_weight=base_params.get("vessel_weight", BREWCTL_VESSEL_WEIGHT_GRAMS),
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
