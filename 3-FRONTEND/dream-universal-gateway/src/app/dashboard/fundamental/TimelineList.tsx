"use client";

import React, { useState } from "react";

export interface TimelineEvent {
  id?: string;
  timestamp: string;
  title: string;
  sentiment: number;
  category?: string;
  impact_score?: number;
  source?: string;
}

interface Props {
  events: TimelineEvent[];
  max?: number;
  defaultVisible?: number;
}

function toNum(v: any, def = 0): number {
  if (typeof v === "number" && isFinite(v)) return v;
  if (typeof v === "string" && v.trim()) {
    const n = parseFloat(v);
    return isFinite(n) ? n : def;
  }
  return def;
}

function sentimentColor(v: number): string {
  if (v > 0.2) return "#22c55e";
  if (v < -0.2) return "#ef4444";
  return "#eab308";
}

function sentimentLabel(v: number): string {
  if (v > 0.2) return "利多";
  if (v < -0.2) return "利空";
  return "中性";
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) {
      const m = ts.match(/(\d{2}):(\d{2})/);
      if (m) return `${m[1]}:${m[2]}`;
      return ts.slice(0, 5);
    }
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  } catch {
    return ts.slice(0, 5);
  }
}

export default function TimelineList({
  events,
  max = 8,
  defaultVisible,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const list = (events || []).slice(0, max);
  const showCount =
    defaultVisible && !expanded ? Math.min(defaultVisible, list.length) : list.length;
  const visible = list.slice(0, showCount);
  const hasMore = defaultVisible && list.length > defaultVisible;

  if (list.length === 0) {
    return (
      <div
        className="rounded-lg text-sm text-center"
        style={{ backgroundColor: "#121212", padding: 16, color: "#6b7280" }}
      >
        暂无时间线数据
      </div>
    );
  }

  return (
    <div style={{ backgroundColor: "#121212", padding: 12, borderRadius: 8 }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-[#9ca3af]">时间线</span>
        {hasMore && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-[11px] text-[#3b82f6] hover:text-[#60a5fa] transition"
          >
            {expanded ? "收起" : `展开全部 (${list.length})`}
          </button>
        )}
      </div>
      <div className="relative pl-3">
        <div
          className="absolute left-1 top-1 bottom-1"
          style={{ width: 1, backgroundColor: "#2a2a2a" }}
        />
        <div className="space-y-2">
          {visible.map((e, i) => {
            const sent = toNum(e.sentiment);
            const color = sentimentColor(sent);
            const impact = toNum(e.impact_score);
            return (
              <div key={e.id || i} className="relative flex items-start gap-2 pl-2">
                <div
                  className="absolute left-0 top-2 rounded-full"
                  style={{
                    width: 6,
                    height: 6,
                    marginLeft: -7,
                    backgroundColor: color,
                    opacity: 0.85,
                  }}
                />
                <span
                  className="text-[11px] font-mono shrink-0 mt-0.5"
                  style={{ color: "#8a8a8a" }}
                >
                  {formatTime(e.timestamp)}
                </span>
                <div className="flex-1 min-w-0">
                  <div
                    className="text-xs text-[#e0e0e0] leading-snug truncate"
                    title={e.title}
                  >
                    {e.title}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: `${color}20`,
                        color,
                      }}
                    >
                      {sentimentLabel(sent)}
                    </span>
                    {e.category && (
                      <span className="text-[10px] text-[#6b7280]">
                        {e.category}
                      </span>
                    )}
                  </div>
                </div>
                {impact > 0 && (
                  <span
                    className="text-[10px] font-mono shrink-0 px-1.5 py-0.5 rounded mt-0.5"
                    style={{
                      backgroundColor: "#1f1f1f",
                      color: "#9ca3af",
                    }}
                  >
                    {impact.toFixed(0)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
