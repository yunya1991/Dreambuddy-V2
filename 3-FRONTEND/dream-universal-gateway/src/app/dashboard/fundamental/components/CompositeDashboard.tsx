"use client";

import React from "react";

interface TopSignal {
  type: string;
  reason: string;
  strength?: number;
  confidence?: number;
  module?: string;
}

interface CompositeDashboardProps {
  score: number;
  confidence: number;
  strength: number;
  recommendation: string;
  reasons: string[];
  consistency: number;
  divergentModules: string[];
  topSignals: TopSignal[];
  riskWarnings?: string[];
  summary?: string;
  updatedAt?: string;
}

const recColorMap: Record<string, string> = {
  强烈买入: "#22c55e",
  strong_buy: "#22c55e",
  买入: "#10b981",
  buy: "#10b981",
  观望: "#f59e0b",
  hold: "#f59e0b",
  neutral: "#f59e0b",
  减仓: "#f97316",
  reduce: "#f97316",
  卖出: "#ef4444",
  sell: "#ef4444",
  强烈卖出: "#dc2626",
  strong_sell: "#dc2626",
};

const signalColorMap: Record<string, string> = {
  strong_buy: "#22c55e",
  buy: "#10b981",
  hold: "#f59e0b",
  neutral: "#f59e0b",
  reduce: "#f97316",
  sell: "#ef4444",
  strong_sell: "#dc2626",
  risk_alert: "#ef4444",
};

function getRecColor(rec: string): string {
  const key = rec.trim().toLowerCase();
  return recColorMap[rec] || recColorMap[key] || "#3b82f6";
}

function getSignalColor(type: string): string {
  const key = type.trim().toLowerCase();
  return signalColorMap[type] || signalColorMap[key] || "#3b82f6";
}

function NumberCard({
  label,
  value,
  unit,
  color,
}: {
  label: string;
  value: string;
  unit?: string;
  color?: string;
}) {
  return (
    <div
      style={{
        backgroundColor: "#0d0d0d",
        border: "1px solid #2a2a2a",
        borderRadius: 12,
        padding: "16px 20px",
        minWidth: 120,
        flex: 1,
      }}
    >
      <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <span
          style={{
            fontSize: 28,
            fontWeight: 600,
            color: color || "#e0e0e0",
            lineHeight: 1,
          }}
        >
          {value}
        </span>
        {unit && <span style={{ fontSize: 12, color: "#8a8a8a" }}>{unit}</span>}
      </div>
    </div>
  );
}

export default function CompositeDashboard({
  score,
  confidence,
  strength,
  recommendation,
  reasons,
  consistency,
  divergentModules,
  topSignals,
  riskWarnings,
  summary,
  updatedAt,
}: CompositeDashboardProps) {
  const scoreNum = typeof score === "number" && isFinite(score) ? score : 0;
  const confNum = typeof confidence === "number" && isFinite(confidence) ? confidence : 0.5;
  const strNum = typeof strength === "number" && isFinite(strength) ? strength : 0;
  const consNum = typeof consistency === "number" && isFinite(consistency) ? consistency : 50;

  const recColor = getRecColor(recommendation);
  const recLabel = recommendation || "观望";

  const scoreText = scoreNum >= 0 ? `+${scoreNum.toFixed(2)}` : scoreNum.toFixed(2);
  const confidenceText = `${(confNum * 100).toFixed(0)}`;
  const strengthText = `${strNum.toFixed(0)}`;

  return (
    <div
      style={{
        backgroundColor: "#1a1a1a",
        border: "1px solid #2a2a2a",
        borderRadius: 12,
        padding: 20,
        color: "#e0e0e0",
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 16,
          alignItems: "stretch",
          marginBottom: 20,
        }}
      >
        <div
          style={{
            flex: "0 0 auto",
            minWidth: 240,
            backgroundColor: "#0d0d0d",
            borderRadius: 12,
            padding: 20,
            borderLeft: `6px solid ${recColor}`,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
          }}
        >
          <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 8 }}>
            综合信号
          </div>
          <div
            style={{
              fontSize: 32,
              fontWeight: 700,
              color: recColor,
              lineHeight: 1.1,
              marginBottom: 8,
            }}
          >
            {recLabel}
          </div>
          {summary && (
            <div
              style={{
                fontSize: 13,
                color: "#e0e0e0",
                whiteSpace: "pre-line",
                lineHeight: 1.5,
              }}
            >
              {summary}
            </div>
          )}
        </div>

        <div
          style={{
            flex: 1,
            display: "flex",
            gap: 12,
          }}
        >
          <NumberCard
            label="方向得分"
            value={scoreText}
            color={scoreNum >= 0 ? "#22c55e" : "#ef4444"}
          />
          <NumberCard
            label="置信度"
            value={confidenceText}
            unit="%"
            color="#3b82f6"
          />
          <NumberCard
            label="信号强度"
            value={strengthText}
            unit="%"
            color="#f97316"
          />
        </div>
      </div>

      <div
        style={{
          display: "flex",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <div
          style={{
            flex: 1,
            backgroundColor: "#0d0d0d",
            border: "1px solid #2a2a2a",
            borderRadius: 12,
            padding: 16,
          }}
        >
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "#e0e0e0",
              marginBottom: 12,
            }}
          >
            支撑理由
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {reasons && reasons.length > 0 ? (
              reasons.map((r, idx) => (
                <div
                  key={idx}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 8,
                    fontSize: 13,
                    color: "#e0e0e0",
                    lineHeight: 1.5,
                    wordBreak: "break-word",
                  }}
                >
                  <span style={{ color: "#22c55e", flexShrink: 0 }}>•</span>
                  <span style={{ color: "#e0e0e0" }}>{r}</span>
                </div>
              ))
            ) : (
              <div style={{ fontSize: 13, color: "#8a8a8a" }}>暂无支撑理由</div>
            )}
          </div>
        </div>

        <div
          style={{
            flex: 1,
            backgroundColor: "#0d0d0d",
            border: "1px solid #2a2a2a",
            borderRadius: 12,
            padding: 16,
          }}
        >
          <div
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "#e0e0e0",
              marginBottom: 12,
            }}
          >
            TOP 信号
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {topSignals && topSignals.length > 0 ? (
              topSignals.slice(0, 5).map((s, idx) => {
                const signalColor = getSignalColor(s.type);
                const strengthPct =
                  typeof s.strength !== "number"
                    ? 0
                    : Math.round(s.strength * 100);
                return (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      padding: "8px 10px",
                      backgroundColor: "#1a1a1a",
                      borderRadius: 8,
                      border: "1px solid #2a2a2a",
                    }}
                  >
                    <span
                      style={{
                        flexShrink: 0,
                        fontSize: 11,
                        fontWeight: 600,
                        padding: "2px 8px",
                        borderRadius: 4,
                        backgroundColor: signalColor + "22",
                        color: signalColor,
                      }}
                    >
                      {s.type}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontSize: 13,
                          color: "#e0e0e0",
                          marginBottom: 6,
                          wordBreak: "break-word",
                          lineHeight: 1.4,
                        }}
                      >
                        {s.reason}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          color: "#8a8a8a",
                          display: "flex",
                          alignItems: "center",
                          gap: 8,
                        }}
                      >
                        <div
                          style={{
                            flex: 1,
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
                              backgroundColor: signalColor,
                            }}
                          />
                        </div>
                        <span>强度 {strengthPct}%</span>
                        {s.module && <span>· {s.module}</span>}
                      </div>
                    </div>
                  </div>
                );
              })
            ) : (
              <div style={{ fontSize: 13, color: "#8a8a8a" }}>暂无信号</div>
            )}
          </div>
        </div>
      </div>

      <div
        style={{
          backgroundColor: "#0d0d0d",
          border: "1px solid #2a2a2a",
          borderRadius: 12,
          padding: 16,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            marginBottom: 12,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: "#e0e0e0" }}>
            模块一致性
          </div>
          <div
            style={{
              flex: 1,
              height: 8,
              backgroundColor: "#2a2a2a",
              borderRadius: 4,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${consNum}%`,
                backgroundColor:
                  consNum >= 70
                    ? "#22c55e"
                    : consNum >= 40
                    ? "#f59e0b"
                    : "#ef4444",
                transition: "width 0.3s ease",
              }}
            />
          </div>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "#e0e0e0",
              minWidth: 48,
              textAlign: "right",
            }}
          >
            {consNum.toFixed(0)}%
          </div>
        </div>
        {divergentModules && divergentModules.length > 0 && (
          <div style={{ fontSize: 12, color: "#f97316", marginBottom: 8 }}>
            分歧模块：{divergentModules.join("、")}
          </div>
        )}
        {riskWarnings && riskWarnings.length > 0 && (
          <div
            style={{
              marginTop: 8,
              backgroundColor: "rgba(239, 68, 68, 0.08)",
              border: "1px solid rgba(239, 68, 68, 0.3)",
              borderRadius: 8,
              padding: "10px 12px",
            }}
          >
            <div
              style={{
                fontSize: 12,
                color: "#ef4444",
                fontWeight: 600,
                marginBottom: 6,
              }}
            >
              ⚠ 风险警告
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {riskWarnings.map((w, idx) => (
                <div key={idx} style={{ fontSize: 12, color: "#ef4444" }}>
                  • {w}
                </div>
              ))}
            </div>
          </div>
        )}
        {updatedAt && (
          <div style={{ marginTop: 10, fontSize: 11, color: "#8a8a8a" }}>
            更新时间：{updatedAt}
          </div>
        )}
      </div>
    </div>
  );
}
