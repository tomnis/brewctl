import { apiUrl } from "./constants";

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
