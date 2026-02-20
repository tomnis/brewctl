import React from "react";

const STEPS_PER_REVOLUTION = 200;

// SVG dimensions
const SIZE = 120;
const CENTER = SIZE / 2;
const RADIUS = 45;
const STROKE_WIDTH = 8;

// Calculate the arc path for the gauge
function describeArc(x: number, y: number, radius: number, startAngle: number, endAngle: number): string {
  const start = polarToCartesian(x, y, radius, endAngle);
  const end = polarToCartesian(x, y, radius, startAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";
  return ["M", start.x, start.y, "A", radius, radius, 0, largeArcFlag, 0, end.x, end.y].join(" ");
}

function polarToCartesian(centerX: number, centerY: number, radius: number, angleInDegrees: number) {
  const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180;
  return {
    x: centerX + radius * Math.cos(angleInRadians),
    y: centerY + radius * Math.sin(angleInRadians),
  };
}

interface ValveGaugeProps {
  position: number | null;  // 0-199, null when not available
  isActive: boolean;  // Whether brew is active (brewing or paused)
}

export const ValveGauge: React.FC<ValveGaugeProps> = ({ position, isActive }) => {
  // Don't render if not active
  if (!isActive || position === null) {
    return null;
  }

  // Display as steps from starting position: 200 - position
  // Special case: position 0 (starting) should display as "0", not "200"
  const displayPosition = position === 0 ? 0 : 200 - position;

  // Convert position (0-199) to angle (0-360 degrees)
  // Position 0 = 12 o'clock, position 200 = 12 o'clock (full circle)
  const angle = (position / STEPS_PER_REVOLUTION) * 360;
  
  // Arc goes from 0 to current position
  const arcEndAngle = angle;
  
  // Background circle (full revolution)
  const backgroundArc = describeArc(CENTER, CENTER, RADIUS, 0, 360);
  
  // Progress arc (0 to current position)
  // SVG arcs can't draw full circle, so we use 359.9 for full
  const progressArc = angle > 0 
    ? describeArc(CENTER, CENTER, RADIUS, 0, arcEndAngle >= 360 ? 359.9 : arcEndAngle)
    : "";

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "4px" }}>
      <span style={{ fontSize: "12px", color: "#666", fontWeight: 500 }}>
        VALVE
      </span>
      <svg width={SIZE} height={SIZE} style={{ overflow: "visible" }}>
        {/* Background circle */}
        <circle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={STROKE_WIDTH}
        />
        
        {/* Progress arc */}
        {progressArc && (
          <path
            d={progressArc}
            fill="none"
            stroke="#3b82f6"
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
          />
        )}
        
        {/* Needle/indicator dot at current position */}
        {position !== null && position !== undefined && (
          <circle
            cx={CENTER + RADIUS * Math.cos((angle - 90) * Math.PI / 180)}
            cy={CENTER + RADIUS * Math.sin((angle - 90) * Math.PI / 180)}
            r={6}
            fill="#2563eb"
          />
        )}
        
        {/* Center text */}
        <text
          x={CENTER}
          y={CENTER + 5}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{
            fontSize: "16px",
            fontWeight: 600,
            fill: "#1f2937",
          }}
        >
          {displayPosition}
        </text>
        <text
          x={CENTER}
          y={CENTER + 22}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{
            fontSize: "10px",
            fill: "#6b7280",
          }}
        >
          / {STEPS_PER_REVOLUTION}
        </text>
      </svg>
    </div>
  );
};
