export type BrewState = "brewing" | "paused" | "completed" | "idle" | "error";

// Simple error type
export interface BrewError {
  error: string;
  timestamp?: string;
}

export interface DataPoint {
  timestamp: number;
  flowRate: number | null;
  weight: number | null;
}

export interface BrewInProgress {
  brew_id: string;
  current_flow_rate: string | null;
  current_weight: string | null;
  target_weight: string;
  brew_state: BrewState;
  brew_strategy: string;
  time_started: string;
  time_completed: string | null;
  estimated_time_remaining: string | null;
  error_message: string | null;
  valve_position: number | null;  // 0-199 for one full rotation
  // Historical data for trend visualization
  flow_rate_history?: DataPoint[];
  weight_history?: DataPoint[];
}

export type BrewContextShape = {
  brewInProgress: BrewInProgress | null;
  brewError: BrewError | null;
  isFlipped: boolean;
  fetchBrewInProgress: () => Promise<void>;
  stopPolling: () => void;
  toggleFlip: () => void;
  handlePause: () => Promise<void>;
  handleResume: () => Promise<void>;
  handleNudgeOpen: () => Promise<void>;
  handleNudgeClose: () => Promise<void>;
  dismissError: () => void;
};
