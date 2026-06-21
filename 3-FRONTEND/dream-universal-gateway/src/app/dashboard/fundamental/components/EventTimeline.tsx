"use client";

import React, { useState } from "react";

interface ModuleEvent {
  id: string;
  timestamp: string;
  title: string;
  category: string;
  sentiment: number;
  impact_score: number;
  source: string;
}

interface EventTimelineProps {
  events: ModuleEvent[];
  title?: string;
}

function getSentimentColor(sentiment: number) {
  if (sentiment > 0.1) return "#22c55e";
  if (sentiment < -0.1) return "#ef4444";
  return "#eab308";
}

function getSentimentLabel(sentiment: number) {
  if (sentiment > 0.1) return "正面";
  if (sentiment < -0.1) return "负面";
  return "中性";
}

export default function EventTimeline({ events, title }: EventTimelineProps) {
  const [expanded, setExpanded] = useState(true);

  if (!events || events.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full rounded-lg"
        style={{ backgroundColor: "#1a1a1a", minHeight: 150 }}
      >
        <p className="text-[#6b7280] text-sm">暂无事件</p>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg p-4"
      style={{ backgroundColor: "#1a1a1a", border: "1px solid #2a2a2a" }}
    >
      <div
        className="flex items-center justify-between mb-4 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        {title && <h3 className="text-sm font-semibold text-white">{title}</h3>}
        <span className="text-[#8a8a8a] text-xs">{expanded ? "收起" : "展开"}</span>
      </div>

      {expanded && (
        <div className="relative">
          <div
            className="absolute left-2 top-0 bottom-0 w-0.5"
            style={{ backgroundColor: "#2a2a2a" }}
          />

          <div className="space-y-4 max-h-80 overflow-y-auto">
            {events.map((event, index) => (
              <div key={event.id} className="relative pl-8">
                <div
                  className="absolute left-1.5 top-1.5 w-1 h-1 rounded-full"
                  style={{ backgroundColor: getSentimentColor(event.sentiment) }}
                />

                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[#e0e0e0] mb-1 truncate">
                      {event.title}
                    </p>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className="px-1.5 py-0.5 rounded text-xs"
                        style={{ backgroundColor: "#2a2a2a", color: "#8a8a8a" }}
                      >
                        {event.category}
                      </span>
                      <span
                        className="px-1.5 py-0.5 rounded text-xs"
                        style={{
                          backgroundColor: `${getSentimentColor(event.sentiment)}20`,
                          color: getSentimentColor(event.sentiment),
                        }}
                      >
                        {getSentimentLabel(event.sentiment)}
                      </span>
                    </div>
                  </div>

                  <div className="text-right flex-shrink-0">
                    <div className="text-xs text-[#6b7280]">
                      {new Date(event.timestamp).toLocaleString("zh-CN", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </div>
                    <div className="text-xs text-[#8a8a8a] mt-0.5">
                      {event.source}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
