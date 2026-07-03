"use client";

import { useState } from "react";
import type { ChainTrace } from "@/types";

// ============================================================
// 对话内嵌思考卡
// 展示在 AI 回复顶部，可折叠展开
// ============================================================

interface Props {
  trace: ChainTrace | null | undefined;
  executionTimeMs?: number;
  isLoading?: boolean;
}

const STEP_ICONS: Record<string, string> = {
  S1_RESEARCH: "🔍",
  S2_ANALYSIS: "🧠",
  S3_DESIGN: "📐",
  S4_VALIDATE: "✅",
  S5_EXECUTE: "⚡",
  S0_DIRECT_ANSWER: "💬",
};

export default function ThinkingCard({ trace, executionTimeMs, isLoading }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!trace && !isLoading) return null;

  const aNodes = trace?.nodes?.filter((n) => n.layer === "A") || [];
  const totalSteps = aNodes.length || 5;
  const doneSteps = aNodes.filter((n) => n.status === "done").length;
  const progress = isLoading ? (doneSteps / totalSteps) * 100 : 100;

  const timeText = executionTimeMs
    ? executionTimeMs >= 1000
      ? `${(executionTimeMs / 1000).toFixed(1)}s`
      : `${executionTimeMs}ms`
    : "";

  return (
    <div
      style={{
        marginBottom: 8,
        borderRadius: 10,
        backgroundColor: "#0d0d0d",
        border: "1px solid #1a1a1a",
        overflow: "hidden",
      }}
    >
      {/* ── 头部（折叠态也可见） ── */}
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: "10px 12px",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          userSelect: "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ fontSize: 14 }}>🧠</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#ccc" }}>
            {isLoading ? "思考中..." : "思考过程"}
          </span>
          {timeText && !isLoading && (
            <span style={{ fontSize: 11, color: "#666" }}>· {timeText}</span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* 节点 icon 流 */}
          <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
            {aNodes.length > 0 ? (
              aNodes.map((node) => (
                <span
                  key={node.id}
                  style={{
                    fontSize: 12,
                    opacity: node.status === "done" ? 1 : node.status === "active" ? 1 : 0.3,
                    transition: "opacity 0.3s",
                  }}
                >
                  {node.icon || STEP_ICONS[node.id] || "⚙️"}
                </span>
              ))
            ) : isLoading ? (
              <span style={{ fontSize: 12, animation: "pulse 1.5s infinite" }}>🔄</span>
            ) : null}
          </div>

          <span style={{ fontSize: 11, color: "#666", transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}>
            ▼
          </span>
        </div>
      </div>

      {/* 进度条 */}
      <div style={{ height: 2, backgroundColor: "#1a1a1a" }}>
        <div
          style={{
            height: "100%",
            width: `${progress}%`,
            backgroundColor: isLoading ? "#3b82f6" : "#00c853",
            transition: "width 0.4s ease, background-color 0.3s",
          }}
        />
      </div>

      {/* ── 展开详情 ── */}
      {expanded && trace && (
        <div style={{ padding: "12px", borderTop: "1px solid #1a1a1a", fontSize: 11 }}>
          {/* 意图 & 链路 */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 10 }}>
            <div>
              <span style={{ color: "#666" }}>意图: </span>
              <span style={{ color: "#3b82f6", fontWeight: 600 }}>{trace.intent.type}</span>
            </div>
            <div>
              <span style={{ color: "#666" }}>置信度: </span>
              <span style={{ color: "#00c853", fontWeight: 600 }}>
                {(trace.intent.confidence * 100).toFixed(0)}%
              </span>
            </div>
            <div>
              <span style={{ color: "#666" }}>模式: </span>
              <span style={{ color: "#ccc" }}>{trace.plan.complexity}</span>
            </div>
            <div>
              <span style={{ color: "#666" }}>品质: </span>
              <span style={{ color: trace.final.grade === 'excellent' ? '#00c853' : trace.final.grade === 'good' ? '#10b981' : '#f59e0b', fontWeight: 600 }}>
                {trace.final.grade}
              </span>
            </div>
          </div>

          {/* A层节点详情 */}
          {aNodes.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: "#888", marginBottom: 6, fontWeight: 600 }}>执行节点</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {aNodes.map((node) => (
                  <div
                    key={node.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "4px 8px",
                      borderRadius: 6,
                      backgroundColor: node.status === "done" ? "#0d1f15" : node.status === "active" ? "#0d1525" : "transparent",
                    }}
                  >
                    <span style={{ fontSize: 13 }}>
                      {node.status === "done" ? "✓" : node.status === "active" ? "▶" : "○"}
                    </span>
                    <span style={{ fontSize: 12, color: "#aaa" }}>{node.icon}</span>
                    <span style={{ fontSize: 12, color: "#ccc", flex: 1 }}>{node.name}</span>
                    {node.confidence !== undefined && (
                      <span style={{ fontSize: 10, color: "#00c853" }}>
                        {(node.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 自省结果 */}
          <div
            style={{
              padding: "8px 10px",
              borderRadius: 6,
              backgroundColor: "#0a0a0a",
              border: "1px solid #1a1a1a",
            }}
          >
            <div style={{ color: "#888", marginBottom: 4, fontWeight: 600 }}>🧠 自省结果</div>
            <div style={{ display: "flex", gap: 12 }}>
              <div>
                <span style={{ color: "#666" }}>质量: </span>
                <span style={{ color: "#00c853", fontWeight: 600 }}>
                  {(trace.final.quality_score * 100).toFixed(0)}%
                </span>
              </div>
              <div>
                <span style={{ color: "#666" }}>风险: </span>
                <span
                  style={{
                    color: trace.final.risk_score > 0.5 ? "#ff3b30" : "#f59e0b",
                    fontWeight: 600,
                  }}
                >
                  {(trace.final.risk_score * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {expanded && !trace && isLoading && (
        <div style={{ padding: "12px", borderTop: "1px solid #1a1a1a", fontSize: 11, color: "#666", textAlign: "center" }}>
          正在执行思考链...
        </div>
      )}
    </div>
  );
}
