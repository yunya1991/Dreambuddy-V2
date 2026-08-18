"use client";

import React from "react";

interface MVRVZoneChartProps {
  zScore: number;
  mvrvRatio?: number;
  title?: string;
  size?: number;
}

export default function MVRVZoneChart({
  zScore,
  mvrvRatio,
  title = "MVRV Z-Score 区间",
  size = 280,
}: MVRVZoneChartProps) {
  const z = typeof zScore === "number" && isFinite(zScore) ? zScore : 0;
  const ratio = typeof mvrvRatio === "number" && isFinite(mvrvRatio) ? mvrvRatio : 1.0;

  const zones = [
    { range: [-2, -1], label: "历史底部", color: "#22c55e", desc: "强买入区间" },
    { range: [-1, 0], label: "低估", color: "#4ade80", desc: "买入机会" },
    { range: [0, 1], label: "合理", color: "#f59e0b", desc: "中性持有" },
    { range: [1, 3], label: "偏高", color: "#f97316", desc: "谨慎观察" },
    { range: [3, 7], label: "过热", color: "#ef4444", desc: "风险区间" },
  ];

  const currentZone = zones.find(
    (zone) => z >= zone.range[0] && z < zone.range[1]
  ) || zones[zones.length - 1];

  const normalizedPosition = Math.max(0, Math.min(1, (z + 2) / 9));

  const zoneWidth = size - 40;
  const zoneHeight = 60;

  return (
    <div
      style={{
        backgroundColor: "#1a1a1a",
        border: "1px solid #2a2a2a",
        borderRadius: 12,
        padding: 20,
      }}
    >
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

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
          }}
        >
          <div
            style={{
              fontSize: 32,
              fontWeight: 700,
              color: currentZone.color,
            }}
          >
            {z.toFixed(2)}
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 500, color: currentZone.color }}>
              {currentZone.label}
            </div>
            <div style={{ fontSize: 12, color: "#8a8a8a" }}>
              {currentZone.desc}
            </div>
          </div>
        </div>

        <div
          style={{
            position: "relative",
            width: zoneWidth,
            height: zoneHeight,
            borderRadius: 8,
            overflow: "hidden",
          }}
        >
          {zones.map((zone, i) => {
            const width = (zone.range[1] - zone.range[0]) / 9 * zoneWidth;
            const left = (zone.range[0] + 2) / 9 * zoneWidth;

            return (
              <div
                key={i}
                style={{
                  position: "absolute",
                  left,
                  width,
                  height: zoneHeight,
                  backgroundColor: zone.color,
                  opacity: 0.6,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  color: "#fff",
                  fontWeight: 500,
                }}
              >
                {zone.label}
              </div>
            );
          })}

          <div
            style={{
              position: "absolute",
              left: normalizedPosition * zoneWidth - 4,
              top: -8,
              width: 8,
              height: zoneHeight + 16,
              backgroundColor: "#fff",
              borderRadius: 4,
              boxShadow: "0 0 8px rgba(255,255,255,0.5)",
            }}
          />
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 11,
            color: "#8a8a8a",
          }}
        >
          <span>-2 (底部)</span>
          <span>0 (合理)</span>
          <span>+3 (过热)</span>
          <span>+7 (泡沫)</span>
        </div>

        {mvrvRatio !== undefined && (
          <div
            style={{
              fontSize: 12,
              color: "#8a8a8a",
              textAlign: "center",
            }}
          >
            MVRV比率: {ratio.toFixed(3)} · 市价/已实现价格比值
          </div>
        )}
      </div>
    </div>
  );
}