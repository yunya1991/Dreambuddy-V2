"use client";

import React from "react";

interface MetricItem {
  label: string;
  value: number | string;
  unit?: string;
  trend?: "up" | "down" | "neutral";
  type?: "positive" | "negative" | "neutral";
}

interface MetricsCardProps {
  metrics: Record<string, number | string>;
  title?: string;
}

function getTrendIcon(trend: "up" | "down" | "neutral") {
  switch (trend) {
    case "up":
      return "↑";
    case "down":
      return "↓";
    default:
      return "→";
  }
}

function getTrendColor(type: "positive" | "negative" | "neutral" | undefined) {
  switch (type) {
    case "positive":
      return "#22c55e";
    case "negative":
      return "#ef4444";
    default:
      return "#8a8a8a";
  }
}

function getValueColor(value: number, type: "positive" | "negative" | "neutral" | undefined) {
  if (type === "positive" && value > 0) return "#22c55e";
  if (type === "negative" && value < 0) return "#ef4444";
  if (type === "neutral" || type === undefined) return "#e0e0e0";
  return "#e0e0e0";
}

export default function MetricsCard({ metrics, title }: MetricsCardProps) {
  // 只保留简单类型的 metrics（number 或 string），过滤掉对象/数组
  const simpleMetrics = Object.entries(metrics).filter(
    ([, value]) => typeof value === "number" || typeof value === "string"
  );

  const metricList: MetricItem[] = simpleMetrics.map(([key, value]) => {
    let trend: "up" | "down" | "neutral" = "neutral";
    let type: "positive" | "negative" | "neutral" = "neutral";

    if (typeof value === "number") {
      if (value > 0.1) {
        trend = "up";
        type = "positive";
      } else if (value < -0.1) {
        trend = "down";
        type = "negative";
      }
    }

    return {
      label: key,
      value,
      trend,
      type,
    };
  });

  return (
    <div
      className="rounded-lg p-4"
      style={{ backgroundColor: "#1a1a1a", border: "1px solid #2a2a2a" }}
    >
      {title && (
        <h3 className="text-sm font-semibold text-white mb-4">{title}</h3>
      )}
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}
      >
        {metricList.map((metric, index) => (
          <div
            key={index}
            className="p-3 rounded-lg"
            style={{ backgroundColor: "#121212" }}
          >
            <div className="text-xs text-[#8a8a8a] mb-1">{metric.label}</div>
            <div className="flex items-baseline gap-1">
              <span
                className="text-xl font-bold font-mono"
                style={{ color: getValueColor(Number(metric.value), metric.type) }}
              >
                {typeof metric.value === "number"
                  ? metric.value.toFixed(3)
                  : metric.value}
              </span>
              {metric.unit && (
                <span className="text-xs text-[#6b7280]">{metric.unit}</span>
              )}
              <span
                className="text-sm ml-1"
                style={{ color: getTrendColor(metric.type) }}
              >
                {getTrendIcon(metric.trend)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
