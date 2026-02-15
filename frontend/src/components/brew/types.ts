export type BrewState = "brewing" | "paused" | "completed" | "idle";

export interface BrewInProgress {
  brew_id: string;
  current_flow_rate: string;
  current_weight: string;
  brew_state: BrewState;
}

export type BrewContextShape = {
  brewInProgress: BrewInProgress | null;
  isFlipped: boolean;
  fetchBrewInProgress: () => Promise<void>;
  stopPolling: () => void;
  toggleFlip: () => void;
  handlePause: () => Promise<void>;
  handleResume: () => Promise<void>;
};
