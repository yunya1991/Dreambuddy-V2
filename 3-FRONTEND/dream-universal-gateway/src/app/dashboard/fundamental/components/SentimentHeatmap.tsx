"use client";

import React from "react";

interface HeatmapCell {
  category: string;
  score: number;
  label?: string;
}

interface SentimentHeatmapProps {
  data: HeatmapCell[];
  title?: string;
}

function getColor(score: number): string {
  if (score >= 80) return "#22c55e";
  if (score >= 60) return "#4ade80";
  if (score >= 40) return "#f59e0b";
  if (score >= 20) return "#f97316";
  return "#ef4444";
}

function getLabel(score: number): string {
  if (score >= 80) return "极度贪婪";
  if (score >= 60) return "贪婪";
  if (score >= 40) return "中性";
  if (score >= 20) return "恐惧";
  return "极度恐惧";
}

export default function SentimentHeatmap({
  data,
  title = "市场情绪热力图",
}: SentimentHeatmapProps) {
  if (!data || data.length === 0) {
    const defaultData: HeatmapCell[] = [
      { category: "社交媒体", score: 55 },
      { category: "新闻舆情", score: 48 },
      { category: "搜索热度", score: 62 },
      { category: "衍生品", score: 35 },
      { category: "资金流向", score: 70 },
      { category: "链上活动", score: 42 },
      { category: "宏观环境", score: 30 },
      { category: "技术面", score: 58 },
    ];
    data = defaultData;
  }

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

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 8,
        }}
      >
        {data.map((cell, i) => {
          const color = getColor(cell.score);
          const label = cell.label || getLabel(cell.score);

          return (
            <div
              key={i}
              style={{
                backgroundColor: color,
                borderRadius: 8,
                padding: 12,
                textAlign: "center",
                opacity: 0.85 + (cell.score / 100) * 0.15,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 500,
                  color: "#fff",
                  marginBottom: 4,
                }}
              >
                {cell.category}
              </div>
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: "#fff",
                }}
              >
                {Math.round(cell.score)}
              </div>
              <div
                style={{
                  fontSize: 10,
                  color: "rgba(255,255,255,0.8)",
                  marginTop: 2,
                }}
              >
                {label}
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: 12,
          fontSize: 11,
          color: "#8a8a8a",
          textAlign: "center",
        }}
      >
        数值越高表示市场越贪婪（看涨），越低表示越恐惧（看跌）
      </div>
    </div>
  );
}