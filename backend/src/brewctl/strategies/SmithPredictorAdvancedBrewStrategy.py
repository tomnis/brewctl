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
from brewctl.strategies.kalman_filter import KalmanFilter


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
            kp=_extract_float(strategy_params.get("kp"), 1.0),
            ki=_extract_float(strategy_params.get("ki"), 0.05),
            kd=_extract_float(strategy_params.get("kd"), 0.1),
            dead_time=_extract_float(strategy_params.get("dead_time"), 45.0),
            plant_gain=_extract_float(strategy_params.get("plant_gain"), 0.005),
            plant_time_constant=_extract_float(strategy_params.get("plant_time_constant"), 15.0),
            q=_extract_float(strategy_params.get("q"), 0.0005),
            r=_extract_float(strategy_params.get("r"), 0.15),
            output_min=_extract_float(strategy_params.get("output_min"), -10.0),
            output_max=_extract_float(strategy_params.get("output_max"), 10.0),
            integral_limit=_extract_float(strategy_params.get("integral_limit"), 100.0),
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
