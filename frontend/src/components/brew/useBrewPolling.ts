import { useRef, useState, useCallback } from "react";
import { apiUrl } from "./constants";
import { BrewInProgress } from "./types";
import { POLL_INTERVAL_MS } from "./constants";

export function useBrewPolling() {
  const [brewInProgress, setBrewInProgress] = useState<BrewInProgress | null>(null);

  const pollRef = useRef<{ 
    active: boolean; 
    timeoutId: number | null; 
    controller: AbortController | null;
  }>(
    { active: false, timeoutId: null, controller: null }
  );

  const fetchBrewInProgress = useCallback(async () => {
    if (pollRef.current.controller) {
      try { pollRef.current.controller.abort(); } catch {}
    }
    const controller = new AbortController();
    pollRef.current.controller = controller;
    try {
      const response = await fetch(`${apiUrl}/brew/status`, { signal: controller.signal });
      if (!response.ok) return;
      const data = await response.json();
      setBrewInProgress(data);
    } catch (e) {
      if ((e as any).name !== "AbortError") console.error("fetch error", e);
    } finally {
      pollRef.current.controller = null;
    }
  }, []);

  const backgroundRefreshBrewInProgress = useCallback(async () => {
    if (pollRef.current.controller) {
      try { pollRef.current.controller.abort(); } catch {}
    }
    const controller = new AbortController();
    pollRef.current.controller = controller;
    try {
      const response = await fetch(`${apiUrl}/brew/status`, { signal: controller.signal });
      if (!response.ok) return;
      const data = await response.json();
      setBrewInProgress(data);
    } catch (e) {
      if ((e as any).name !== "AbortError") console.error("fetch error", e);
    } finally {
      pollRef.current.controller = null;
    }
    
    if (!pollRef.current.active) return;
    const id = window.setTimeout(() => backgroundRefreshBrewInProgress(), POLL_INTERVAL_MS);
    pollRef.current.timeoutId = id;
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current.active) return;
    pollRef.current.active = true;
    backgroundRefreshBrewInProgress();
  }, [backgroundRefreshBrewInProgress]);

  const stopPolling = useCallback(() => {
    pollRef.current.active = false;
    if (pollRef.current.timeoutId != null) {
      clearTimeout(pollRef.current.timeoutId);
      pollRef.current.timeoutId = null;
    }
    if (pollRef.current.controller) {
      try { pollRef.current.controller.abort(); } catch {}
      pollRef.current.controller = null;
    }
  }, []);

  return { brewInProgress, fetchBrewInProgress, startPolling, stopPolling };
}
