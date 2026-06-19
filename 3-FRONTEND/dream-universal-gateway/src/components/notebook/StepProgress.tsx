"use client";

// ============================================================
// StepProgress — 7步进度指示器
// 版本: v1.0 | 日期: 2026-06-15
// 显示 7 个圆形步骤 + 连接线 + 状态图标
// ============================================================

import type { NotebookStep } from "@/lib/notebook/types";

interface Props {
  steps: NotebookStep[];
  onStepClick?: (stepNumber: number) => void;
  compact?: boolean;
}

const statusStyles: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  pending:  { bg: "#1a1a1a", border: "#2a2a2a", text: "#666",    icon: "⬜" },
  active:   { bg: "#0066ff", border: "#0066ff", text: "#fff",    icon: "▶" },
  done:     { bg: "#006b3f", border: "#006b3f", text: "#fff",    icon: "✓" },
  skipped:  { bg: "#4a4a4a", border: "#4a4a4a", text: "#999",    icon: "⏭" },
};

export default function StepProgress({ steps, onStepClick, compact }: Props) {
  const progress = steps.filter((s) => s.status !== "pending").length;
  const total = steps.length;

  return (
    <div
      style={{
        width: "100%",
        padding: compact ? "8px 4px" : "16px 8px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 0,
          position: "relative",
        }}
      >
        {steps.map((step, idx) => {
          const style = statusStyles[step.status];
          const isLast = idx === steps.length - 1;
          return (
            <div
              key={step.id}
              style={{
                display: "flex",
                alignItems: "center",
                flex: isLast ? 0 : 1,
              }}
            >
              <div
                onClick={() => onStepClick && onStepClick(step.number)}
                style={{
                  width: compact ? 32 : 44,
                  height: compact ? 32 : 44,
                  borderRadius: "50%",
                  backgroundColor: style.bg,
                  border: `2px solid ${style.border}`,
                  color: style.text,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 600,
                  fontSize: compact ? 12 : 14,
                  cursor: onStepClick ? "pointer" : "default",
                  position: "relative",
                  zIndex: 2,
                  flexShrink: 0,
                  transition: "all 0.2s",
                }}
                title={step.name}
              >
                <span style={{ fontSize: compact ? 12 : 14, lineHeight: 1 }}>
                  {compact ? step.icon : style.icon}
                </span>
                {!compact && (
                  <span
                    style={{
                      fontSize: 10,
                      marginTop: 2,
                      opacity: 0.85,
                    }}
                  >
                    S{step.number}
                  </span>
                )}
              </div>
              {!isLast && (
                <div
                  style={{
                    flex: 1,
                    height: 2,
                    marginLeft: -1,
                    marginRight: -1,
                    backgroundColor:
                      steps[idx + 1]?.status !== "pending"
                        ? "#006b3f"
                        : "#2a2a2a",
                    zIndex: 1,
                    minWidth: 10,
                  }}
                />
              )}
            </div>
          );
        })}
      </div>

      {!compact && (
        <div
          style={{
            marginTop: 16,
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            justifyContent: "space-between",
          }}
        >
          {steps.map((step) => {
            const style = statusStyles[step.status];
            return (
              <div
                key={step.id}
                style={{
                  fontSize: 11,
                  color: step.status === "active" ? "#0066ff" : step.status === "done" ? "#008855" : style.text,
                  fontWeight: step.status === "active" ? 700 : 400,
                  textAlign: "center",
                  minWidth: 60,
                  maxWidth: 100,
                  flex: 1,
                }}
                onClick={() => onStepClick && onStepClick(step.number)}
              >
                <div style={{ fontWeight: step.status === "active" ? 700 : 500 }}>
                  {step.name}
                </div>
                {step.status !== "pending" && step.status !== "active" && (
                  <div style={{ fontSize: 10, opacity: 0.6, marginTop: 2 }}>
                    {step.status === "done" ? "完成" : "跳过"}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div
        style={{
          marginTop: 12,
          fontSize: 11,
          color: "#666",
          textAlign: "center",
        }}
      >
        进度 {progress}/{total} · 已完成 {Math.round((progress / total) * 100)}%
      </div>
    </div>
  );
}
