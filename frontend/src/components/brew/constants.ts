// Derive WebSocket URL from API URL (replace /api with empty string, change http to ws)
const getApiUrl = () => import.meta.env.COLDBREW_FRONTEND_API_URL as string || "http://localhost:8000/api";
export const apiUrl = getApiUrl();

// WebSocket URL for real-time brew status updates
export const wsUrl = () => {
  const api = getApiUrl();
  return api.replace('/api', '').replace('http://', 'ws://').replace('https://', 'wss://');
};

export const DEFAULT_FLOW = "0.05";
export const DEFAULT_VALVE_INTERVAL = "90";
export const DEFAULT_EPSILON = "0.008";
export const POLL_INTERVAL_MS = 4000;
export const DEFAULT_TARGET_WEIGHT = "1337";

// Strategy types (must match backend BrewStrategyType enum)
export type StrategyType = "default" | "pid" | "kalman_pid";

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
