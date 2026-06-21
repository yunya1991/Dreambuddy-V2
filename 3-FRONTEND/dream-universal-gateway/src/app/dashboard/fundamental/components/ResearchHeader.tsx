"use client";

import React, { useState } from "react";

interface ResearchHeaderProps {
  module: string;
  title: string;
  onRefresh: () => void;
  lastUpdated?: string | null;
  loading?: boolean;
}

const TIME_RANGES = ["7D", "30D", "90D"] as const;
type TimeRange = (typeof TIME_RANGES)[number];

export default function ResearchHeader({
  module,
  title,
  onRefresh,
  lastUpdated,
  loading = false,
}: ResearchHeaderProps) {
  const [selectedRange, setSelectedRange] = useState<TimeRange>("30D");

  return (
    <div
      className="flex items-center justify-between px-6 py-4 border-b"
      style={{ borderColor: "#2a2a2a", backgroundColor: "#1a1a1a" }}
    >
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-white">{title}</h1>
        <div className="flex items-center gap-1 ml-4">
          {TIME_RANGES.map((range) => (
            <button
              key={range}
              onClick={() => setSelectedRange(range)}
              className="px-3 py-1 rounded-md text-xs font-medium transition"
              style={{
                backgroundColor:
                  selectedRange === range ? "#3b82f6" : "#2a2a2a",
                color: selectedRange === range ? "#ffffff" : "#8a8a8a",
              }}
            >
              {range}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {lastUpdated && (
          <span className="text-xs text-[#8a8a8a]">
            🕐 {lastUpdated}
          </span>
        )}
        <button
          onClick={onRefresh}
          disabled={loading}
          className="px-3 py-1.5 rounded-md text-sm text-white transition disabled:opacity-50"
          style={{
            backgroundColor: loading ? "#374151" : "#3b82f6",
          }}
        >
          {loading ? "加载中..." : "🔄 刷新"}
        </button>
      </div>
    </div>
  );
}
