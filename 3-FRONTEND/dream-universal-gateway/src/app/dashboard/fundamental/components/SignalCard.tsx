"use client";

import React from "react";

interface SignalItem {
  type:
    | "strong_buy"
    | "buy"
    | "hold"
    | "sell"
    | "strong_sell"
    | "reduce"
    | "risk_alert"
    | string;
  reason: string;
  strength?: number;
  confidence?: number;
  module?: string;
  horizon?: string;
}

interface SignalCardProps {
  signals: SignalItem[];
  title?: string;
  maxItems?: number;
}

const typeColorMap: Record<string, string> = {
  strong_buy: "#22c55e",
  buy: "#10b981",
  hold: "#f59e0b",
  neutral: "#f59e0b",
  reduce: "#f97316",
  sell: "#ef4444",
  strong_sell: "#dc2626",
  risk_alert: "#ef4444",
};

const typeLabelMap: Record<string, string> = {
  strong_buy: "强买",
  buy: "买入",
  hold: "观望",
  neutral: "观望",
  reduce: "减仓",
  sell: "卖出",
  strong_sell: "强卖",
  risk_alert: "风险",
};

function getTypeColor(type: string): string {
  const key = type.trim().toLowerCase();
  return typeColorMap[type] || typeColorMap[key] || "#3b82f6";
}

function getTypeLabel(type: string): string {
  const key = type.trim().toLowerCase();
  return typeLabelMap[type] || typeLabelMap[key] || type;
}

export default function SignalCard({
  signals,
  title,
  maxItems = 5,
}: SignalCardProps) {
  const items = (signals || []).slice(0, maxItems);

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

      {items.length === 0 ? (
        <div style={{ fontSize: 13, color: "#8a8a8a" }}>暂无信号</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((s, idx) => {
            const color = getTypeColor(s.type);
            const label = getTypeLabel(s.type);
            const strengthPct =
              typeof s.strength !== "number"
                ? 0
                : Math.round(s.strength * 100);
            const confidencePct =
              typeof s.confidence !== "number"
                ? 0
                : Math.round(s.confidence * 100);

            return (
              <div
                key={idx}
                style={{
                  display: "flex",
                  alignItems: "stretch",
                  minHeight: 70,
                  backgroundColor: "#0d0d0d",
                  border: "1px solid #2a2a2a",
                  borderRadius: 8,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: 4,
                    backgroundColor: color,
                    flexShrink: 0,
                  }}
                />
                <div
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "flex-start",
                    padding: "12px 14px",
                    gap: 12,
                  }}
                >
                  <span
                    style={{
                      flexShrink: 0,
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "3px 8px",
                      borderRadius: 4,
                      backgroundColor: color + "22",
                      color: color,
                    }}
                  >
                    {label}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        color: "#e0e0e0",
                        lineHeight: 1.5,
                        wordBreak: "break-word",
                        marginBottom: 8,
                      }}
                    >
                      {s.reason}
                    </div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        fontSize: 11,
                        color: "#8a8a8a",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                        }}
                      >
                        <div
                          style={{
                            width: 60,
                            height: 4,
                            backgroundColor: "#2a2a2a",
                            borderRadius: 2,
                            overflow: "hidden",
                          }}
                        >
                          <div
                            style={{
                              height: "100%",
                              width: `${strengthPct}%`,
                              backgroundColor: color,
                            }}
                          />
                        </div>
                        <span>强度 {strengthPct}%</span>
                      </div>
                      {typeof s.confidence === "number" && (
                        <span>置信 {confidencePct}%</span>
                      )}
                      {s.module && <span>· {s.module}</span>}
                      {s.horizon && <span>· {s.horizon}</span>}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
