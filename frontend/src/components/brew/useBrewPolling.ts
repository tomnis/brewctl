import { useRef, useState, useCallback, useEffect } from "react";
import { wsUrl } from "./constants";
import { BrewInProgress, BrewError, DataPoint } from "./types";

// Reconnection delay settings
const RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;
const MAX_HISTORY_POINTS = 128;

export function useBrewPolling() {
  const [brewInProgress, setBrewInProgress] = useState<BrewInProgress | null>(null);
  const [brewError, setBrewError] = useState<BrewError | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttempts = useRef(0);
  
  // Rolling history buffers for trend visualization
  const flowRateHistoryRef = useRef<DataPoint[]>([]);
  const weightHistoryRef = useRef<DataPoint[]>([]);

  const connect = useCallback(() => {
    // Close existing connection if any
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const ws = new WebSocket(`${wsUrl()}/ws/brew/status`);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("WebSocket connected");
      reconnectAttempts.current = 0;
    };

    ws.onmessage = (event) => {
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
        console.error("Failed to parse WebSocket message:", e);
      }
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected");
      wsRef.current = null;
      
      // Attempt to reconnect with exponential backoff
      const delay = Math.min(
        RECONNECT_DELAY_MS * Math.pow(2, reconnectAttempts.current),
        MAX_RECONNECT_DELAY_MS
      );
      reconnectAttempts.current += 1;
      
      console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts.current})`);
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, delay);
    };
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    reconnectAttempts.current = 0;
  }, []);

  const startPolling = useCallback(() => {
    connect();
  }, [connect]);

  const stopPolling = useCallback(() => {
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

  // fetchBrewInProgress is no longer needed with WebSocket - the connection handles it
  const fetchBrewInProgress = useCallback(async () => {
    // With WebSocket, we just ensure we're connected
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      connect();
    }
  }, [connect]);

  return { brewInProgress, brewError, fetchBrewInProgress, startPolling, stopPolling };
}
