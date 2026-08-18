"use client";

import React from "react";

export interface Resistance3D {
  direction: "up" | "down" | "neutral";
  direction_score: number;
  velocity: number;
  acceleration: number;
  trend_summary: string;
  confidence: number;
  data_points: number;
}

interface Props {
  data: Resistance3D;
  size?: "sm" | "md" | "lg";
}

function toNum(v: any, def = 0): number {
  if (typeof v === "number" && isFinite(v)) return v;
  if (typeof v === "string" && v.trim()) {
    const n = parseFloat(v);
    return isFinite(n) ? n : def;
  }
  return def;
}

function directionColor(d: string): string {
  return d === "up" ? "#22c55e" : d === "down" ? "#ef4444" : "#eab308";
}

function directionIcon(d: string): string {
  return d === "up" ? "↑" : d === "down" ? "↓" : "→";
}

function polarityColor(v: number): string {
  if (v > 0.1) return "#22c55e";
  if (v < -0.1) return "#ef4444";
  return "#eab308";
}

function Bar({
  value,
  label,
  color,
}: {
  value: number;
  label: string;
  color: string;
}) {
  const pct = ((value + 1) / 2) * 100;
  const widthPct = Math.abs(pct - 50);
  const leftPct = value >= 0 ? 50 : 50 - widthPct;

  return (
    <div className="mb-3 last:mb-0">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-[#9ca3af]">{label}</span>
        <span className="text-sm font-mono" style={{ color, opacity: 0.9 }}>
          {value >= 0 ? "+" : ""}
          {value.toFixed(3)}
        </span>
      </div>
      <div
        className="relative bg-[#1f1f1f] rounded-full overflow-hidden"
        style={{ height: 3 }}
      >
        <div
          className="absolute top-0 bottom-0"
          style={{ left: "50%", width: 1, backgroundColor: "#3f3f3f" }}
        />
        <div
          className="absolute top-0 bottom-0 rounded-full"
          style={{
            left: `${leftPct}%`,
            width: `${widthPct}%`,
            backgroundColor: color,
            opacity: 0.75,
          }}
        />
      </div>
    </div>
  );
}

export default function Resistance3DDisplay({ data, size = "md" }: Props) {
  const score = toNum(data.direction_score);
  const vel = toNum(data.velocity);
  const acc = toNum(data.acceleration);
  const dirColor = directionColor(data.direction);
  const velColor = polarityColor(vel);
  const accColor = polarityColor(acc);

  const titleSize =
    size === "lg" ? "text-5xl" : size === "sm" ? "text-2xl" : "text-4xl";

  return (
    <div
      className="rounded-xl"
      style={{ backgroundColor: "#121212", padding: 20 }}
    >
      <div className="text-center mb-4">
        <div className="text-xs text-[#6b7280] mb-1">综合方向得分</div>
        <div
          className={`${titleSize} font-bold font-mono leading-none`}
          style={{ color: dirColor, opacity: 0.9 }}
        >
          <span className="mr-1">{directionIcon(data.direction)}</span>
          {score >= 0 ? "+" : ""}
          {score.toFixed(3)}
        </div>
        <div className="text-[11px] text-[#6b7280] mt-2">
          置信度 {(toNum(data.confidence) * 100).toFixed(0)}% · 数据点{" "}
          {toNum(data.data_points)}
        </div>
      </div>

      <div className="px-1">
        <Bar value={score} label="方向" color={dirColor} />
        <Bar value={vel} label="速度" color={velColor} />
        <Bar value={acc} label="加速度" color={accColor} />
      </div>

      {data.trend_summary && (
        <div
          className="mt-3 pt-3 border-t text-xs text-[#8a8a8a] leading-relaxed text-center"
          style={{ borderColor: "#1f1f1f" }}
        >
          {data.trend_summary}
        </div>
      )}
    </div>
  );
}
