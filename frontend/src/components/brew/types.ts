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

export interface StrategySwitch {
  timestamp: string;
  from_strategy: string;
  to_strategy: string;
  // Whatever the strategy defines; keys vary per strategy.
  strategy_params: Record<string, unknown>;
  valve_position: number | null;
  flow_rate: number | null;
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
  // Gross target minus this is the coffee target. Nullable: a partial payload must
  // not turn the progress bar into NaN.
  vessel_weight?: number | null;
  // Simulated brew: mock hardware and an accelerated clock.
  dry_run?: boolean;
  // Live strategy swaps applied to this brew, oldest first.
  strategy_switches?: StrategySwitch[];
  // Historical data for trend visualization
  flow_rate_history?: DataPoint[];
  weight_history?: DataPoint[];
}

export type BrewContextShape = {
  brewInProgress: BrewInProgress | null;
  brewError: BrewError | null;
  isFlipped: boolean;
  fetchBrewInProgress: () => Promise<void>;
  stopConnection: () => void;
  toggleFlip: () => void;
  handlePause: () => Promise<void>;
  handleResume: () => Promise<void>;
  handleNudgeOpen: () => Promise<void>;
  handleNudgeClose: () => Promise<void>;
  dismissError: () => void;
};
