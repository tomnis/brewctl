import { useRef, useState, useCallback, useEffect } from "react";
import { wsUrl } from "./constants";
import { BrewInProgress } from "./types";

// Reconnection delay settings
const RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;

export function useBrewPolling() {
  const [brewInProgress, setBrewInProgress] = useState<BrewInProgress | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttempts = useRef(0);

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
        setBrewInProgress(data);
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

  return { brewInProgress, fetchBrewInProgress, startPolling, stopPolling };
}
