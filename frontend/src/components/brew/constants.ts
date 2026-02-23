// Derive WebSocket URL from API URL (replace /api with empty string, change http to ws)
const getApiUrl = () => import.meta.env.COLDBREW_FRONTEND_API_URL as string || "http://localhost:8000/api";
export const apiUrl = getApiUrl();

// WebSocket URL for real-time brew status updates
export const wsUrl = () => {
  const api = getApiUrl();
  return api.replace('/api', '').replace('http://', 'ws://').replace('https://', 'wss://');
};

// WebSocket URL for health status updates
export const healthWsUrl = () => {
  return `${wsUrl()}/ws/health`;
};

// SSE URL for real-time brew status updates
export const sseUrl = () => {
  const api = getApiUrl();
  return api.replace('/api', '') + '/sse/brew/status';
};

// SSE URL for health status updates
export const healthSseUrl = () => {
  return `${sseUrl().replace('/sse/brew/status', '/sse/health')}`;
};

export const DEFAULT_FLOW = "0.05";
export const DEFAULT_VALVE_INTERVAL = "90";
export const DEFAULT_EPSILON = "0.008";
export const POLL_INTERVAL_MS = 4000;
export const DEFAULT_TARGET_WEIGHT = "1337";

// Strategy types (must match backend BrewStrategyType enum)
export type StrategyType = "default" | "pid" | "kalman_pid" | "smith_predictor_advanced" | "adaptive_gain_scheduling" | "mpc";

export interface StrategyParam {
  name: string;
  label: string;
  placeholder: string;
  defaultValue: string;
  description?: string;
}

export interface Strategy {
  id: StrategyType;
  name: string;
  description: string;
  params: StrategyParam[];
}

export const STRATEGIES: Strategy[] = [
  {
    id: "default",
    name: "Default (Threshold)",
    description: "Simple threshold-based control that opens/closes valve based on flow rate",
    params: [],
  },
  {
    id: "pid",
    name: "PID Controller",
    description: "Proportional-Integral-Derivative control for smoother flow rate stabilization",
    params: [
      {
        name: "kp",
        label: "Kp (Proportional Gain)",
        placeholder: "1.0",
        defaultValue: "1.0",
        description: "Controls response to current error",
      },
      {
        name: "ki",
        label: "Ki (Integral Gain)",
        placeholder: "0.1",
        defaultValue: "0.1",
        description: "Controls response to accumulated error",
      },
      {
        name: "kd",
        label: "Kd (Derivative Gain)",
        placeholder: "0.05",
        defaultValue: "0.05",
        description: "Controls response to rate of error change",
      },
    ],
  },
  {
    id: "kalman_pid",
    name: "Kalman PID",
    description: "PID controller with Kalman Filter for noise reduction on flow rate readings",
    params: [
      {
        name: "kp",
        label: "Kp (Proportional Gain)",
        placeholder: "1.0",
        defaultValue: "1.0",
        description: "Controls response to current error",
      },
      {
        name: "ki",
        label: "Ki (Integral Gain)",
        placeholder: "0.1",
        defaultValue: "0.1",
        description: "Controls response to accumulated error",
      },
      {
        name: "kd",
        label: "Kd (Derivative Gain)",
        placeholder: "0.05",
        defaultValue: "0.05",
        description: "Controls response to rate of error change",
      },
      {
        name: "q",
        label: "Q (Process Noise)",
        placeholder: "0.001",
        defaultValue: "0.001",
        description: "How much the flow naturally varies. Higher = more responsive to changes",
      },
      {
        name: "r",
        label: "R (Measurement Noise)",
        placeholder: "0.1",
        defaultValue: "0.1",
        description: "How noisy the sensor readings are. Higher = more smoothing",
      },
    ],
  },
  {
    id: "smith_predictor_advanced",
    name: "Smith Predictor (Advanced)",
    description: "Predictive control with plant model and delay compensation for handling system lag",
    params: [
      {
        name: "kp",
        label: "Kp (Proportional Gain)",
        placeholder: "1.0",
        defaultValue: "1.0",
        description: "Controls response to current error",
      },
      {
        name: "ki",
        label: "Ki (Integral Gain)",
        placeholder: "0.1",
        defaultValue: "0.1",
        description: "Controls response to accumulated error",
      },
      {
        name: "kd",
        label: "Kd (Derivative Gain)",
        placeholder: "0.05",
        defaultValue: "0.05",
        description: "Controls response to rate of error change",
      },
      {
        name: "dead_time",
        label: "Dead Time (seconds)",
        placeholder: "30.0",
        defaultValue: "30.0",
        description: "Transport delay between valve command and effect on flow rate",
      },
      {
        name: "plant_gain",
        label: "Plant Gain",
        placeholder: "0.01",
        defaultValue: "0.01",
        description: "Steady-state flow rate change per unit valve position",
      },
      {
        name: "plant_time_constant",
        label: "Plant Time Constant",
        placeholder: "10.0",
        defaultValue: "10.0",
        description: "Time constant of the first-order plant model",
      },
      {
        name: "q",
        label: "Q (Process Noise)",
        placeholder: "0.001",
        defaultValue: "0.001",
        description: "How much the flow naturally varies. Higher = more responsive to changes",
      },
      {
        name: "r",
        label: "R (Measurement Noise)",
        placeholder: "0.1",
        defaultValue: "0.1",
        description: "How noisy the sensor readings are. Higher = more smoothing",
      },
    ],
  },
  {
    id: "adaptive_gain_scheduling",
    name: "Adaptive Gain Scheduling",
    description: "Automatically adjusts PID gains based on operating region for optimal control at all flow rates",
    params: [
      // LOW region gains (startup)
      {
        name: "kp_low",
        label: "Kp (Low Region)",
        placeholder: "0.5",
        defaultValue: "0.5",
        description: "Proportional gain for low flow rates (startup)",
      },
      {
        name: "ki_low",
        label: "Ki (Low Region)",
        placeholder: "0.05",
        defaultValue: "0.05",
        description: "Integral gain for low flow rates (startup)",
      },
      {
        name: "kd_low",
        label: "Kd (Low Region)",
        placeholder: "0.02",
        defaultValue: "0.02",
        description: "Derivative gain for low flow rates (startup)",
      },
      // MEDIUM region gains (normal operation)
      {
        name: "kp_med",
        label: "Kp (Medium Region)",
        placeholder: "1.5",
        defaultValue: "1.5",
        description: "Proportional gain for medium flow rates",
      },
      {
        name: "ki_med",
        label: "Ki (Medium Region)",
        placeholder: "0.15",
        defaultValue: "0.15",
        description: "Integral gain for medium flow rates",
      },
      {
        name: "kd_med",
        label: "Kd (Medium Region)",
        placeholder: "0.08",
        defaultValue: "0.08",
        description: "Derivative gain for medium flow rates",
      },
      // HIGH region gains (high flow)
      {
        name: "kp_high",
        label: "Kp (High Region)",
        placeholder: "2.5",
        defaultValue: "2.5",
        description: "Proportional gain for high flow rates",
      },
      {
        name: "ki_high",
        label: "Ki (High Region)",
        placeholder: "0.25",
        defaultValue: "0.25",
        description: "Integral gain for high flow rates",
      },
      {
        name: "kd_high",
        label: "Kd (High Region)",
        placeholder: "0.1",
        defaultValue: "0.1",
        description: "Derivative gain for high flow rates",
      },
      // Region thresholds
      {
        name: "flow_rate_low_threshold",
        label: "Low→Medium Threshold (g/s)",
        placeholder: "0.03",
        defaultValue: "0.03",
        description: "Flow rate threshold for switching from low to medium gains",
      },
      {
        name: "flow_rate_high_threshold",
        label: "Medium→High Threshold (g/s)",
        placeholder: "0.07",
        defaultValue: "0.07",
        description: "Flow rate threshold for switching from medium to high gains",
      },
      // Adaptation settings
      {
        name: "adaptation_enabled",
        label: "Enable Real-time Adaptation",
        placeholder: "true",
        defaultValue: "true",
        description: "Allow gains to adapt in real-time based on sustained error",
      },
      {
        name: "adaptation_rate",
        label: "Adaptation Rate",
        placeholder: "0.01",
        defaultValue: "0.01",
        description: "How fast gains adapt when sustained error is detected",
      },
    ],
  },
  {
    id: "mpc",
    name: "MPC (Model Predictive)",
    description: "Predictive control that optimizes valve commands over a future horizon for best tracking",
    params: [
      {
        name: "horizon",
        label: "Prediction Horizon",
        placeholder: "15",
        defaultValue: "15",
        description: "Number of future timesteps to predict",
      },
      {
        name: "plant_gain",
        label: "Plant Gain",
        placeholder: "0.01",
        defaultValue: "0.01",
        description: "Steady-state flow rate change per valve step",
      },
      {
        name: "plant_time_constant",
        label: "Plant Time Constant",
        placeholder: "10.0",
        defaultValue: "10.0",
        description: "Time constant of the first-order plant model",
      },
      {
        name: "q_error",
        label: "Error Weight (Qe)",
        placeholder: "1.0",
        defaultValue: "1.0",
        description: "Weight on tracking error in cost function",
      },
      {
        name: "q_control",
        label: "Control Weight (Qu)",
        placeholder: "0.1",
        defaultValue: "0.1",
        description: "Weight on control effort (prevents aggressive moves)",
      },
      {
        name: "q_delta",
        label: "Delta Weight (Qd)",
        placeholder: "0.5",
        defaultValue: "0.5",
        description: "Weight on control rate for smoothness",
      },
    ],
  },
];

export const DEFAULT_STRATEGY: StrategyType = "default";

export async function pauseBrew(): Promise<void> {
  const response = await fetch(`${apiUrl}/brew/pause`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to pause brew: ${response.statusText}`);
  }
}

export async function resumeBrew(): Promise<void> {
  const response = await fetch(`${apiUrl}/brew/resume`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to resume brew: ${response.statusText}`);
  }
}

export async function nudgeOpen(): Promise<void> {
  const response = await fetch(`${apiUrl}/brew/nudge/open`, { method: "POST" });
  if (!response.ok) {
    if (response.status === 429) {
      throw new Error("Nudge too frequent, please wait");
    }
    throw new Error(`Failed to nudge open: ${response.statusText}`);
  }
}

export async function nudgeClose(): Promise<void> {
  const response = await fetch(`${apiUrl}/brew/nudge/close`, { method: "POST" });
  if (!response.ok) {
    if (response.status === 429) {
      throw new Error("Nudge too frequent, please wait");
    }
    throw new Error(`Failed to nudge close: ${response.statusText}`);
  }
}
