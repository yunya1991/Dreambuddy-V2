"use client";

import React, { useState } from "react";
import Resistance3DDisplay, { Resistance3D } from "./Resistance3DDisplay";
import TimelineList, { TimelineEvent } from "./TimelineList";
import SignalBadge, { TradingSignal } from "./SignalBadge";

export interface ModuleMetrics {
  event_count: number;
  heat_score: number;
  sentiment_index: number;
  flow_index: number;
  narrative_consensus: number;
  stress_level: string;
}

export interface AnalysisModule {
  name: string;
  resistance_3d: Resistance3D;
  metrics: ModuleMetrics;
  signals: TradingSignal[];
  timeline: TimelineEvent[];
  ts?: string;
}

interface Props {
  module: AnalysisModule;
}

function toNum(v: any, def = 0): number {
  if (typeof v === "number" && isFinite(v)) return v;
  if (typeof v === "string" && v.trim()) {
    const n = parseFloat(v);
    return isFinite(n) ? n : def;
  }
  return def;
}

function moduleEmoji(name: string): string {
  const n = (name || "").toLowerCase();
  if (n.includes("news")) return "📰";
  if (n.includes("flow") || n.includes("资金")) return "💵";
  if (n.includes("sentiment") || n.includes("情绪")) return "📈";
  if (n.includes("macro")) return "🌐";
  return "📊";
}

function stressColor(level: string): string {
  const l = (level || "").toLowerCase();
  if (l === "high" || l === "h" || l.includes("高")) return "#ef4444";
  if (l === "medium" || l === "m" || l.includes("中")) return "#eab308";
  return "#22c55e";
}

function MetricRow({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-[#9ca3af]">{label}</span>
      <span
        className="text-xs font-mono font-bold"
        style={{ color: color || "#e0e0e0" }}
      >
        {value}
      </span>
    </div>
  );
}

export default function ModuleCard({ module }: Props) {
  const [timelineOpen, setTimelineOpen] = useState(true);
  const metrics = module.metrics || ({} as ModuleMetrics);

  const heatScore = toNum(metrics.heat_score);
  const heatColor =
    heatScore > 0.6 ? "#ef4444" : heatScore > 0.3 ? "#eab308" : "#22c55e";

  const sentIdx = toNum(metrics.sentiment_index);
  const sentColor =
    sentIdx > 0.2 ? "#22c55e" : sentIdx < -0.2 ? "#ef4444" : "#eab308";

  const flowIdx = toNum(metrics.flow_index);
  const flowColor =
    flowIdx > 0.2 ? "#22c55e" : flowIdx < -0.2 ? "#ef4444" : "#eab308";

  return (
    <div
      className="rounded-xl flex flex-col"
      style={{
        backgroundColor: "#1a1a1a",
        border: "1px solid #2a2a2a",
        padding: 16,
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-base font-semibold text-white">
          {moduleEmoji(module.name)} {module.name}
        </h3>
        {module.ts && (
          <span className="text-[11px] text-[#6b7280] font-mono">
            {module.ts.replace("T", " ").replace("Z", "")}
          </span>
        )}
      </div>

      <div className="mb-3">
        <Resistance3DDisplay data={module.resistance_3d} size="sm" />
      </div>

      <div className="grid grid-cols-2 gap-3 mb-3">
        <div
          className="rounded-lg"
          style={{ backgroundColor: "#121212", padding: 10 }}
        >
          <MetricRow
            label="事件数"
            value={String(toNum(metrics.event_count))}
          />
          <MetricRow
            label="热度"
            value={`${(heatScore * 100).toFixed(0)}%`}
            color={heatColor}
          />
          <MetricRow
            label="情绪"
            value={`${sentIdx >= 0 ? "+" : ""}${sentIdx.toFixed(2)}`}
            color={sentColor}
          />
          <MetricRow
            label="压力"
            value={String(metrics.stress_level || "-")}
            color={stressColor(metrics.stress_level || "")}
          />
        </div>
        <div>
          <SignalBadge
            signals={(module.signals || []).slice(0, 2)}
            size="sm"
          />
        </div>
      </div>

      {(module.timeline || []).length > 0 && (
        <div>
          <button
            onClick={() => setTimelineOpen((v) => !v)}
            className="text-[11px] text-[#9ca3af] hover:text-[#e0e0e0] mb-2 flex items-center gap-1 transition"
          >
            <span
              className="inline-block transition-transform"
              style={{ transform: timelineOpen ? "rotate(90deg)" : "rotate(0deg)" }}
            >
              ▶
            </span>
            {timelineOpen ? "收起" : "展开"} 时间线 ({module.timeline.length})
          </button>
          {timelineOpen && (
            <TimelineList
              events={module.timeline}
              max={8}
              defaultVisible={3}
            />
          )}
        </div>
      )}
    </div>
  );
}
