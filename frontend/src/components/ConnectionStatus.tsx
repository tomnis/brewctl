import { useEffect } from "react";
import { useConnectionStatus } from "./brew/useConnectionStatus";

// Status indicator dot component
function StatusDot({ connected }: { connected: boolean }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: "8px",
        height: "8px",
        borderRadius: "50%",
        backgroundColor: connected ? "#4ade80" : "#ef4444",
        marginRight: "4px",
        boxShadow: connected 
          ? "0 0 6px #4ade80" 
          : "0 0 6px #ef4444",
      }}
      aria-hidden="true"
    />
  );
}

// Single component indicator
function ComponentIndicator({ 
  name, 
  connected, 
  details 
}: { 
  name: string; 
  connected: boolean; 
  details?: string 
}) {
  return (
    <span 
      className="terminal-glow" 
      style={{ 
        fontSize: "0.75rem",
        display: "inline-flex",
        alignItems: "center",
        marginRight: "8px"
      }}
      title={`${name}: ${connected ? "Connected" : "Disconnected"}${details ? ` (${details})` : ""}`}
    >
      <StatusDot connected={connected} />
      <span style={{ marginRight: "2px" }}>{name}:</span>
      <span>{connected ? "OK" : "Error"}</span>
      {details && <span style={{ opacity: 0.7, marginLeft: "2px" }}>{details}</span>}
    </span>
  );
}

export default function ConnectionStatus() {
  const { connectionStatus, connectionState, startPolling, stopPolling } = useConnectionStatus();

  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  const isConnected = connectionState === "connected" && connectionStatus !== null;
  const isReconnecting = connectionState === "reconnecting";

  // Format battery percentage if available
  const scaleDetails = connectionStatus?.scale?.battery_pct !== undefined && connectionStatus?.scale?.battery_pct !== null
    ? `${connectionStatus.scale.battery_pct}%`
    : undefined;

  return (
    <div 
      style={{ 
        display: "flex", 
        alignItems: "center", 
        flexWrap: "wrap",
        gap: "4px"
      }}
      role="status"
      aria-label="Connection status"
    >
      {/* Show reconnecting indicator when reconnecting */}
      {isReconnecting && !isConnected && (
        <span 
          className="terminal-glow" 
          style={{ 
            fontSize: "0.75rem",
            color: "#fbbf24",
            display: "inline-flex",
            alignItems: "center",
            marginRight: "8px"
          }}
        >
          <span
            style={{
              display: "inline-block",
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              backgroundColor: "#fbbf24",
              marginRight: "4px",
              animation: "pulse 1s infinite",
            }}
            aria-hidden="true"
          />
          Reconnecting...
        </span>
      )}

      {/* Show connection status indicators when connected */}
      {isConnected && (
        <>
          <ComponentIndicator 
            name="SCALE" 
            connected={connectionStatus?.scale?.connected ?? false}
            details={scaleDetails}
          />
          <ComponentIndicator 
            name="VALVE" 
            connected={connectionStatus?.valve?.available ?? false}
          />
          <ComponentIndicator 
            name="INFLUXDB"
            connected={connectionStatus?.influxdb?.connected ?? false}
          />
        </>
      )}

      {/* Show disconnected state when not connected and not reconnecting */}
      {!isConnected && !isReconnecting && (
        <span 
          className="terminal-glow" 
          style={{ 
            fontSize: "0.75rem",
            color: "#ef4444"
          }}
        >
          Disconnected
        </span>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}
