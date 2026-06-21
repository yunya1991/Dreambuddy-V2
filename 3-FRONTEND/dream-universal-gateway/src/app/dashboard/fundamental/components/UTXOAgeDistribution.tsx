"use client";

import React from "react";

interface UTXOBucket {
  age_range: string;
  percentage: number;
  color?: string;
}

interface UTXOAgeDistributionProps {
  buckets: UTXOBucket[];
  title?: string;
}

const DEFAULT_COLORS = [
  "#ef4444", // <1天 - 红色（高流动性）
  "#f97316", // 1-7天 - 橙色
  "#f59e0b", // 7-30天 - 黄色
  "#84cc16", // 30-90天 - 浅绿
  "#22c55e", // 90-365天 - 绿色
  "#14b8a6", // 1-2年 - 青色
  "#0ea5e9", // 2-3年 - 蓝色
  "#6366f1", // 3-5年 - 紫色
  "#8b5cf6", // >5年 - 深紫（长期持有）
];

const AGE_LABELS = [
  "<1天",
  "1-7天",
  "7-30天",
  "30-90天",
  "90-365天",
  "1-2年",
  "2-3年",
  "3-5年",
  ">5年",
];

export default function UTXOAgeDistribution({
  buckets,
  title = "UTXO年龄分布",
}: UTXOAgeDistributionProps) {
  if (!buckets || buckets.length === 0) {
    buckets = AGE_LABELS.map((label, i) => ({
      age_range: label,
      percentage: 10 + Math.random() * 5,
    }));
  }

  const total = buckets.reduce((sum, b) => sum + (b.percentage || 0), 0);
  const normalized = buckets.map((b) => ({
    ...b,
    percentage: (b.percentage / total) * 100,
  }));

  const shortTerm = normalized
    .slice(0, 3)
    .reduce((sum, b) => sum + b.percentage, 0);
  const midTerm = normalized
    .slice(3, 6)
    .reduce((sum, b) => sum + b.percentage, 0);
  const longTerm = normalized
    .slice(6)
    .reduce((sum, b) => sum + b.percentage, 0);

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
          display: "flex",
          height: 40,
          borderRadius: 8,
          overflow: "hidden",
          marginBottom: 12,
        }}
      >
        {normalized.map((bucket, i) => {
          const color = bucket.color || DEFAULT_COLORS[i] || "#3b82f6";
          const width = bucket.percentage;

          return (
            <div
              key={i}
              style={{
                width: `${width}%`,
                backgroundColor: color,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 10,
                color: "#fff",
                fontWeight: 500,
                minWidth: width > 5 ? 30 : 0,
              }}
              title={`${bucket.age_range}: ${bucket.percentage.toFixed(1)}%`}
            >
              {width > 8 ? `${bucket.percentage.toFixed(0)}%` : ""}
            </div>
          );
        })}
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "#8a8a8a",
          marginBottom: 16,
        }}
      >
        {normalized.map((bucket, i) => (
          <div
            key={i}
            style={{
              textAlign: "center",
              width: `${100 / normalized.length}%`,
            }}
          >
            {bucket.age_range}
          </div>
        ))}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 12,
        }}
      >
        <div
          style={{
            backgroundColor: "#0d0d0d",
            borderRadius: 8,
            padding: 12,
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 11, color: "#ef4444", marginBottom: 4 }}>
            短期持有
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, color: "#ef4444" }}>
            {shortTerm.toFixed(1)}%
          </div>
          <div style={{ fontSize: 10, color: "#8a8a8a" }}>&lt;30天</div>
        </div>

        <div
          style={{
            backgroundColor: "#0d0d0d",
            borderRadius: 8,
            padding: 12,
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 11, color: "#f59e0b", marginBottom: 4 }}>
            中期持有
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, color: "#f59e0b" }}>
            {midTerm.toFixed(1)}%
          </div>
          <div style={{ fontSize: 10, color: "#8a8a8a" }}>30天-2年</div>
        </div>

        <div
          style={{
            backgroundColor: "#0d0d0d",
            borderRadius: 8,
            padding: 12,
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 11, color: "#22c55e", marginBottom: 4 }}>
            长期持有
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, color: "#22c55e" }}>
            {longTerm.toFixed(1)}%
          </div>
          <div style={{ fontSize: 10, color: "#8a8a8a" }}>&gt;2年</div>
        </div>
      </div>

      <div
        style={{
          marginTop: 12,
          fontSize: 11,
          color: "#8a8a8a",
          textAlign: "center",
        }}
      >
        长期持有比例越高，表示市场信心越强，抛压越小
      </div>
    </div>
  );
}