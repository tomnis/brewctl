import { useRef, useState, useCallback, useEffect } from "react";
import { healthSseUrl } from "./constants";

// Types for component health status
export interface ComponentHealth {
  connected: boolean;
  battery_pct?: number | null;
  weight?: number | null;
  units?: string | null;
}

export interface ValveHealth {
  available: boolean;
  position?: number | null;
}

export interface InfluxDBHealth {
  connected: boolean;
  error?: string | null;
}

export interface ConnectionStatus {
  scale: ComponentHealth;
  valve: ValveHealth;
  influxdb: InfluxDBHealth;
  timestamp?: string;
}

export type ConnectionState = "connected" | "reconnecting" | "disconnected";

export interface UseConnectionStatusResult {
  connectionStatus: ConnectionStatus | null;
  connectionState: ConnectionState;
  startPolling: () => void;
  stopPolling: () => void;
}

export function useConnectionStatus(): UseConnectionStatusResult {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");

  const eventSourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    // Close existing connection if any
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    const eventSource = new EventSource(healthSseUrl());
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      console.log("SSE connected for health status");
      setConnectionState("connected");
    };

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setConnectionStatus(data);
      } catch (e) {
        console.error("Failed to parse SSE message:", e);
      }
    };

    eventSource.onerror = (error) => {
      console.error("SSE error:", error);
      // EventSource will automatically try to reconnect, but we can update state
      // The connection may be temporarily closed during reconnection
      if (eventSourceRef.current?.readyState === EventSource.CLOSED) {
        setConnectionState("reconnecting");
      }
    };
  }, []);

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setConnectionState("disconnected");
  }, []);

  const startPolling = useCallback(() => {
    connect();
  }, [connect]);

  const stopPolling = useCallback(() => {
    disconnect();
    setConnectionStatus(null);
  }, [disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return { connectionStatus, connectionState, startPolling, stopPolling };
}
