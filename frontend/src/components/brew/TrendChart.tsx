import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { DataPoint } from "./types";
import { DEFAULT_FLOW } from "./constants";

interface TrendChartProps {
  flowRateHistory: DataPoint[];
  weightHistory: DataPoint[];
  targetWeight: string | null;
  isActive: boolean;
}

const TARGET_FLOW_RATE = parseFloat(DEFAULT_FLOW);

// Format timestamp to relative time (seconds ago)
function formatTime(timestamp: number): string {
  const secondsAgo = Math.round((Date.now() - timestamp) / 1000);
  if (secondsAgo < 60) {
    return `-${secondsAgo}s`;
  }
  return `-${Math.floor(secondsAgo / 60)}m`;
}

// Custom tooltip to show values
interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{
    value: number;
    dataKey: string;
    color: string;
  }>;
  label?: number;
}

const CustomTooltip: React.FC<CustomTooltipProps> = ({ active, payload }) => {
  if (active && payload && payload.length) {
    return (
      <div
        style={{
          backgroundColor: "#1f2937",
          border: "1px solid #374151",
          padding: "8px 12px",
          borderRadius: "4px",
          fontSize: "12px",
          fontFamily: "monospace",
        }}
      >
        {payload.map((entry, index) => (
          <div key={index} style={{ color: entry.color }}>
            {entry.dataKey === "flowRate"
              ? `Flow: ${entry.value?.toFixed(3) ?? "—"} g/s`
              : `Weight: ${entry.value?.toFixed(1) ?? "—"} g`}
          </div>
        ))}
      </div>
    );
  }
  return null;
};

export const TrendChart: React.FC<TrendChartProps> = ({
  flowRateHistory,
  weightHistory,
  targetWeight,
  isActive,
}) => {
  // Don't render if not active or no data
  if (!isActive || (flowRateHistory.length === 0 && weightHistory.length === 0)) {
    return null;
  }

  // Merge the data into a single array for the chart
  // We need to align by timestamp
  const chartData = flowRateHistory.map((flowPoint, index) => {
    const weightPoint = weightHistory[index];
    return {
      time: formatTime(flowPoint.timestamp),
      timestamp: flowPoint.timestamp,
      flowRate: flowPoint.flowRate,
      weight: weightPoint?.weight ?? null,
    };
  });

  // Calculate dynamic Y-axis domains
  const flowRates = flowRateHistory
    .map((p) => p.flowRate)
    .filter((v): v is number => v !== null);
  
  const weights = weightHistory
    .map((p) => p.weight)
    .filter((v): v is number => v !== null);

  // Flow rate domain: [0, max(1.5x target, actual max + margin)]
  const flowMax = flowRates.length > 0 
    ? Math.max(TARGET_FLOW_RATE * 1.5, Math.max(...flowRates) * 1.2) 
    : TARGET_FLOW_RATE * 1.5;
  
  // Weight domain: [0, max(target weight * 1.2, actual max)]
  const weightNum = targetWeight ? parseFloat(targetWeight) : null;
  const weightMax = weightNum 
    ? Math.max(weightNum * 1.2, weights.length > 0 ? Math.max(...weights) * 1.2 : weightNum) 
    : (weights.length > 0 ? Math.max(...weights) * 1.2 : 100);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "4px",
        width: "100%",
        minWidth: "200px",
      }}
    >
      <span style={{ fontSize: "12px", color: "#666", fontWeight: 500 }}>
        TREND
      </span>
      
      {/* Flow Rate Chart */}
      <div style={{ width: "100%", height: "100px", minHeight: 100 }}>
        <ResponsiveContainer width={400} height={100}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="time"
              tick={{ fill: "#9ca3af", fontSize: 10 }}
              tickLine={{ stroke: "#374151" }}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[0, flowMax]}
              tick={{ fill: "#9ca3af", fontSize: 10 }}
              tickLine={{ stroke: "#374151" }}
              tickFormatter={(value) => value.toFixed(2)}
              width={35}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              y={TARGET_FLOW_RATE}
              stroke="#10b981"
              strokeDasharray="5 5"
              strokeWidth={1}
            />
            <Line
              type="monotone"
              dataKey="flowRate"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              name="flowRate"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Weight Chart */}
      <div style={{ width: "100%", height: "80px", marginTop: "8px", minHeight: 80 }}>
        <ResponsiveContainer width={400} height={80}>
          <LineChart data={chartData} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="time"
              tick={{ fill: "#9ca3af", fontSize: 10 }}
              tickLine={{ stroke: "#374151" }}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[0, weightMax]}
              tick={{ fill: "#9ca3af", fontSize: 10 }}
              tickLine={{ stroke: "#374151" }}
              tickFormatter={(value) => value.toFixed(0)}
              width={35}
            />
            <Tooltip content={<CustomTooltip />} />
            {targetWeight && (
              <ReferenceLine
                y={parseFloat(targetWeight)}
                stroke="#10b981"
                strokeDasharray="5 5"
                strokeWidth={1}
              />
            )}
            <Line
              type="monotone"
              dataKey="weight"
              stroke="#f59e0b"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              name="weight"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div
        style={{
          display: "flex",
          gap: "16px",
          fontSize: "10px",
          color: "#9ca3af",
          marginTop: "4px",
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <span style={{ width: "12px", height: "2px", backgroundColor: "#3b82f6" }} />
          Flow (g/s)
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
          <span style={{ width: "12px", height: "2px", backgroundColor: "#f59e0b" }} />
          Weight (g)
        </span>
      </div>
    </div>
  );
};
