import { useRef, useState, useCallback, useEffect } from "react";
import { sseUrl } from "./constants";
import { BrewInProgress, BrewError, DataPoint } from "./types";

// Max history points for trend visualization
const MAX_HISTORY_POINTS = 128;

export function useBrewStatus() {
  const [brewInProgress, setBrewInProgress] = useState<BrewInProgress | null>(null);
  const [brewError, setBrewError] = useState<BrewError | null>(null);

  const eventSourceRef = useRef<EventSource | null>(null);
  
  // Rolling history buffers for trend visualization
  const flowRateHistoryRef = useRef<DataPoint[]>([]);
  const weightHistoryRef = useRef<DataPoint[]>([]);

  const connect = useCallback(() => {
    // Close existing connection if any
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const eventSource = new EventSource(sseUrl());
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      console.log("SSE connected for brew status");
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // Only track history when brew is active (brewing or paused)
        const isActive = data.brew_state === "brewing" || data.brew_state === "paused";
        
        if (isActive) {
          const timestamp = Date.now();
          const flowRate = data.current_flow_rate ? parseFloat(data.current_flow_rate) : null;
          const weight = data.current_weight ? parseFloat(data.current_weight) : null;
          
          // Add new data points to history
          const newFlowPoint: DataPoint = { timestamp, flowRate, weight: null };
          const newWeightPoint: DataPoint = { timestamp, flowRate: null, weight };
          
          // Update flow rate history
          flowRateHistoryRef.current = [...flowRateHistoryRef.current, newFlowPoint].slice(-MAX_HISTORY_POINTS);
          
          // Update weight history  
          weightHistoryRef.current = [...weightHistoryRef.current, newWeightPoint].slice(-MAX_HISTORY_POINTS);
          
          // Add history to the data object
          data.flow_rate_history = [...flowRateHistoryRef.current];
          data.weight_history = [...weightHistoryRef.current];
        } else if (data.brew_state === "completed" || data.brew_state === "idle" || data.brew_state === "error") {
          // Clear history when brew ends
          flowRateHistoryRef.current = [];
          weightHistoryRef.current = [];
        }
        
        setBrewInProgress(data);
        
        // Check if the brew is in error state
        if (data.brew_state === "error") {
          setBrewError({
            error: data.error_message || "An error occurred",
            timestamp: new Date().toISOString(),
          });
        } else {
          // Clear error when not in error state
          setBrewError(null);
        }
      } catch (e) {
        console.error("Failed to parse SSE message:", e);
      }
    };

    eventSource.onerror = (error) => {
      console.error("SSE error:", error);
      // EventSource automatically attempts to reconnect, but we can handle errors here
      // The connection will be closed and reconnect will be handled by the browser
    };
  }, []);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const startConnection = useCallback(() => {
    connect();
  }, [connect]);

  const stopConnection = useCallback(() => {
    disconnect();
    setBrewInProgress(null);
    setBrewError(null);
  }, [disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  // fetchBrewInProgress ensures we're connected
  const fetchBrewInProgress = useCallback(async () => {
    if (!eventSourceRef.current || eventSourceRef.current.readyState === EventSource.CLOSED) {
      connect();
    }
  }, [connect]);

  return { brewInProgress, brewError, fetchBrewInProgress, startConnection, stopConnection };
}
