from typing import Dict, Any, Tuple, Optional

from config import *
from model import ValveCommand, BrewStrategyType
from brewctl.log import logger
from brewctl.strategies.DefaultBrewStrategy import (
    AbstractBrewStrategy,
    register_strategy,
    _extract_float,
)


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
            
            kp_low=_extract_float(strategy_params.get("kp_low"), 0.5),
            ki_low=_extract_float(strategy_params.get("ki_low"), 0.05),
            kd_low=_extract_float(strategy_params.get("kd_low"), 0.02),
            
            kp_med=_extract_float(strategy_params.get("kp_med"), 1.5),
            ki_med=_extract_float(strategy_params.get("ki_med"), 0.15),
            kd_med=_extract_float(strategy_params.get("kd_med"), 0.08),
            
            kp_high=_extract_float(strategy_params.get("kp_high"), 2.5),
            ki_high=_extract_float(strategy_params.get("ki_high"), 0.25),
            kd_high=_extract_float(strategy_params.get("kd_high"), 0.1),
            
            flow_rate_low_threshold=_extract_float(strategy_params.get("flow_rate_low_threshold"), 0.03),
            flow_rate_high_threshold=_extract_float(strategy_params.get("flow_rate_high_threshold"), 0.07),
            
            adaptation_enabled=strategy_params.get("adaptation_enabled", True),
            adaptation_rate=_extract_float(strategy_params.get("adaptation_rate"), 0.01),
            
            output_min=_extract_float(strategy_params.get("output_min"), -10.0),
            output_max=_extract_float(strategy_params.get("output_max"), 10.0),
            integral_limit=_extract_float(strategy_params.get("integral_limit"), 100.0),
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
