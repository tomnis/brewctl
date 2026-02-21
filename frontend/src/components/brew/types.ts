export type BrewState = "brewing" | "paused" | "completed" | "idle" | "error";

// Error types for enhanced error handling
export type ErrorSeverity = "info" | "warning" | "error" | "critical";
export type ErrorCategory = "scale" | "valve" | "timeseries" | "brew" | "network" | "hardware" | "configuration";

export interface BrewError {
  error: string;
  error_detailed?: string;
  category: ErrorCategory;
  severity: ErrorSeverity;
  timestamp: string;
  retryable: boolean;
  brew_id?: string;
  recovery_suggestion?: string;
  exception_type?: string;
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
