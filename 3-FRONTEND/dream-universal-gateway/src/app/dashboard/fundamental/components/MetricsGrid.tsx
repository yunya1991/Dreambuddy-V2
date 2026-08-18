"use client";

import React from "react";

interface MetricsGridProps {
  title?: string;
  metrics: Record<string, number | string>;
  columns?: 2 | 3 | 4;
  displayNames?: Record<string, string>;
  units?: Record<string, string>;
  highlight?: Record<string, "up" | "down" | "neutral">;
}

function formatValue(v: number | string | null | undefined): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" && isFinite(v)) {
    if (Math.abs(v) < 10) return v.toFixed(2);
    return v.toFixed(0);
  }
  if (v === null || v === undefined) return "—";
  return String(v);
}

export default function MetricsGrid({
  title,
  metrics,
  columns = 3,
  displayNames,
  units,
  highlight,
}: MetricsGridProps) {
  const keys = metrics ? Object.keys(metrics) : [];

  if (keys.length === 0) {
    return (
      <div
        style={{
          backgroundColor: "#1a1a1a",
          border: "1px solid #2a2a2a",
          borderRadius: 12,
          padding: 20,
        }}
      >
        {title && (
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "#e0e0e0",
              marginBottom: 12,
            }}
          >
            {title}
          </div>
        )}
        <div style={{ fontSize: 13, color: "#8a8a8a" }}>暂无数据</div>
      </div>
    );
  }

  const colCount = columns || 3;

  return (
    <div
      style={{
        backgroundColor: "#1a1a1a",
        border: "1px solid #2a2a2a",
        borderRadius: 12,
        padding: 20,
      }}
    >
      {title && (
        <div
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "#e0e0e0",
            marginBottom: 16,
          }}
        >
          {title}
        </div>
      )}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${colCount}, 1fr)`,
          gap: 12,
        }}
      >
        {keys.map((key) => {
          const value = metrics[key];
          const label = displayNames && displayNames[key] ? displayNames[key] : key;
          const unit = units && units[key] ? units[key] : undefined;
          const hl = highlight && highlight[key] ? highlight[key] : undefined;

          let valueColor = "#e0e0e0";
          let prefix = "";
          if (hl === "up") {
            valueColor = "#22c55e";
            prefix = "▲ ";
          } else if (hl === "down") {
            valueColor = "#ef4444";
            prefix = "▼ ";
          } else if (hl === "neutral") {
            valueColor = "#f59e0b";
            prefix = "◆ ";
          }

          return (
            <div
              key={key}
              style={{
                backgroundColor: "#0d0d0d",
                border: "1px solid #2a2a2a",
                borderRadius: 8,
                padding: "14px 16px",
              }}
            >
              <div
                style={{
                  fontSize: 12,
                  color: "#8a8a8a",
                  marginBottom: 8,
                }}
              >
                {label}
              </div>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 600,
                  color: valueColor,
                  lineHeight: 1.2,
                }}
              >
                {prefix}
                {formatValue(value)}
              </div>
              {unit && (
                <div
                  style={{
                    fontSize: 11,
                    color: "#8a8a8a",
                    marginTop: 4,
                  }}
                >
                  {unit}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
