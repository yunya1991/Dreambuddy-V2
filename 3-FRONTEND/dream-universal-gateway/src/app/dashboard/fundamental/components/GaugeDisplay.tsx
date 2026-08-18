"use client";

import React from "react";

interface GaugeZone {
  min: number;
  max: number;
  label: string;
  color: string;
}

interface GaugeDisplayProps {
  value: number;
  title?: string;
  zones?: GaugeZone[];
  size?: number;
}

const defaultZones: GaugeZone[] = [
  { min: 0, max: 25, label: "极度恐惧", color: "#ef4444" },
  { min: 25, max: 45, label: "恐惧", color: "#f97316" },
  { min: 45, max: 55, label: "中性", color: "#f59e0b" },
  { min: 55, max: 75, label: "贪婪", color: "#10b981" },
  { min: 75, max: 100, label: "极度贪婪", color: "#22c55e" },
];

function polarToCartesian(
  cx: number,
  cy: number,
  radius: number,
  angleDeg: number
) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180.0;
  return {
    x: cx + radius * Math.cos(angleRad),
    y: cy + radius * Math.sin(angleRad),
  };
}

function describeArc(
  cx: number,
  cy: number,
  radius: number,
  startAngle: number,
  endAngle: number
) {
  const start = polarToCartesian(cx, cy, radius, endAngle);
  const end = polarToCartesian(cx, cy, radius, startAngle);
  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";
  return [
    "M",
    start.x,
    start.y,
    "A",
    radius,
    radius,
    0,
    largeArcFlag,
    0,
    end.x,
    end.y,
  ].join(" ");
}

function valueToAngle(v: number): number {
  const clamped = Math.max(0, Math.min(100, v));
  return 180 + (clamped / 100) * 180;
}

function getActiveZone(v: number, zones: GaugeZone[]): GaugeZone | null {
  for (const z of zones) {
    if (v >= z.min && v <= z.max) return z;
  }
  return null;
}

export default function GaugeDisplay({
  value,
  title,
  zones,
  size = 180,
}: GaugeDisplayProps) {
  const activeZones = zones && zones.length > 0 ? zones : defaultZones;
  const diameter = size || 180;
  const cx = diameter / 2;
  const cy = diameter / 2 + 10;
  const radius = diameter / 2 - 20;
  const strokeWidth = 14;

  const clamped = Math.max(0, Math.min(100, value));
  const valueAngle = valueToAngle(clamped);
  const active = getActiveZone(clamped, activeZones);

  const needleLength = radius - strokeWidth / 2 - 6;
  const needleEnd = polarToCartesian(cx, cy, needleLength, valueAngle);

  return (
    <div
      style={{
        backgroundColor: "#1a1a1a",
        border: "1px solid #2a2a2a",
        borderRadius: 12,
        padding: 20,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
      }}
    >
      <div
        style={{
          fontSize: 13,
          color: "#8a8a8a",
          marginBottom: 8,
          fontWeight: 500,
        }}
      >
        {title || "指标"}
      </div>

      <svg
        width={diameter}
        height={diameter}
        viewBox={`0 0 ${diameter} ${diameter + 10}`}
        style={{ display: "block" }}
      >
        <path
          d={describeArc(cx, cy, radius, 180, 360)}
          fill="none"
          stroke="#2a2a2a"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />

        {activeZones.map((z, idx) => {
          const startAngle = valueToAngle(z.min);
          const endAngle = valueToAngle(z.max);
          if (endAngle <= startAngle) return null;
          return (
            <path
              key={idx}
              d={describeArc(cx, cy, radius, startAngle, endAngle)}
              fill="none"
              stroke={z.color}
              strokeWidth={strokeWidth}
              strokeLinecap="butt"
              opacity={0.85}
            />
          );
        })}

        <line
          x1={cx}
          y1={cy}
          x2={needleEnd.x}
          y2={needleEnd.y}
          stroke="#e0e0e0"
          strokeWidth={3}
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r={6} fill="#e0e0e0" />
        <circle cx={cx} cy={cy} r={3} fill="#1a1a1a" />

        <text
          x={cx}
          y={cy + 30}
          textAnchor="middle"
          style={{
            fontSize: 28,
            fontWeight: 700,
            fill: active ? active.color : "#e0e0e0",
          }}
        >
          {Math.round(clamped)}
        </text>

        <text
          x={cx}
          y={cy - radius - 8}
          textAnchor="middle"
          style={{
            fontSize: 11,
            fill: "#8a8a8a",
          }}
        >
          0
        </text>
        <text
          x={cx + radius}
          y={cy + 4}
          textAnchor="middle"
          style={{
            fontSize: 11,
            fill: "#8a8a8a",
          }}
        >
          100
        </text>
      </svg>

      {active && (
        <div
          style={{
            fontSize: 12,
            color: active.color,
            fontWeight: 600,
            marginTop: 4,
          }}
        >
          {active.label}
        </div>
      )}
    </div>
  );
}
