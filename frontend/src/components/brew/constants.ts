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
