"use client";

// ============================================================
// ActiveStrategyChain — S系列策略思维链可视化
// 版本: v1.0 | 日期: 2026-06-15
// 显示 S1→S2→S3→S4→S5 策略思维链
// ============================================================

import type { StrategyChainState, StrategyStep } from "@/lib/strategy/types";

interface Props {
  chain: StrategyChainState | null;
  compact?: boolean;
  onStepClick?: (stepId: string) => void;
}

const CHAIN_COLOR = "#6b5ce7"; // 紫色主题

const STEP_INFO: Record<string, { name: string; desc: string }> = {
  S1_RESEARCH: { name: "调研", desc: "市场数据收集" },
  S2_ANALYSIS: { name: "分析", desc: "多维度分析" },
  S3_DESIGN: { name: "设计", desc: "策略方案制定" },
  S4_VALIDATE: { name: "验证", desc: "回测风险评估" },
  S5_EXECUTE: { name: "执行", desc: "执行计划跟踪" },
};

const statusStyles: Record<string, { bg: string; border: string; text: string }> = {
  pending:  { bg: "#1a1a1a", border: "#2a2a2a", text: "#666" },
  active:   { bg: CHAIN_COLOR + "33", border: CHAIN_COLOR, text: "#fff" },
  done:     { bg: "#006b3f", border: "#006b3f", text: "#fff" },
  skipped:  { bg: "#4a4a4a", border: "#4a4a4a", text: "#999" },
};

export default function ActiveStrategyChain({ chain, compact, onStepClick }: Props) {
  if (!chain) {
    return (
      <div
        style={{
          padding: 12,
          backgroundColor: "#0d0d0d",
          border: "1px dashed #2a2a2a",
          borderRadius: 6,
          fontSize: 12,
          color: "#666",
          textAlign: "center",
        }}
      >
        S系列策略链未初始化 · 使用 /分析 等命令启动
      </div>
    );
  }

  const totalDone = chain.steps.filter(
    (s) => s.status === "done" || s.status === "skipped"
  ).length;
  const total = chain.steps.length;

  const getStepIcon = (status: string) => {
    switch (status) {
      case "active": return "▶";
      case "done": return "✓";
      case "skipped": return "⏭";
      default: return "⬜";
    }
  };

  return (
    <div
      style={{
        padding: compact ? 8 : 12,
        backgroundColor: "#0d0d0d",
        border: "1px solid #1a1a1a",
        borderRadius: 8,
      }}
    >
      {/* 标题栏 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
          fontSize: 12,
          color: "#888",
        }}
      >
        <span style={{ fontWeight: 600, color: "#ccc" }}>
          🎯 S系列策略思维链
        </span>
        <span>
          {totalDone}/{total} 步骤 · {chain.complexity === "quick" ? "快速" : chain.complexity === "standard" ? "标准" : "深度"}
        </span>
      </div>

      {/* 步骤流程 */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 4,
        }}
      >
        {chain.steps.map((step, idx) => {
          const style = statusStyles[step.status];
          const isLast = idx === chain.steps.length - 1;
          const info = STEP_INFO[step.id] || { name: step.id, desc: "" };

          return (
            <div
              key={step.id}
              style={{
                display: "flex",
                alignItems: "center",
                flex: isLast ? 0 : 1,
              }}
            >
              {/* 步骤节点 */}
              <div
                onClick={() => onStepClick && onStepClick(step.id)}
                style={{
                  width: compact ? 48 : 60,
                  height: compact ? 48 : 60,
                  borderRadius: "50%",
                  backgroundColor: style.bg,
                  border: `2px solid ${style.border}`,
                  color: style.text,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: compact ? 14 : 16,
                  cursor: onStepClick ? "pointer" : "default",
                  flexShrink: 0,
                  transition: "all 0.2s",
                }}
                title={`${info.name} - ${info.desc}`}
              >
                <span style={{ fontSize: compact ? 10 : 12 }}>{getStepIcon(step.status)}</span>
                <span style={{ fontSize: compact ? 10 : 11, marginTop: 2 }}>{step.number}</span>
              </div>

              {/* 连接线 */}
              {!isLast && (
                <div
                  style={{
                    flex: 1,
                    height: 2,
                    marginLeft: -1,
                    marginRight: -1,
                    backgroundColor:
                      chain.steps[idx + 1]?.status !== "pending"
                        ? CHAIN_COLOR
                        : "#2a2a2a",
                    minWidth: 8,
                  }}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* 步骤名称 */}
      {!compact && (
        <div
          style={{
            marginTop: 12,
            display: "flex",
            justifyContent: "space-between",
            gap: 4,
          }}
        >
          {chain.steps.map((step) => {
            const style = statusStyles[step.status];
            const info = STEP_INFO[step.id] || { name: step.id, desc: "" };
            return (
              <div
                key={step.id}
                style={{
                  flex: 1,
                  textAlign: "center",
                  fontSize: 11,
                  color: step.status === "active" ? CHAIN_COLOR : step.status === "done" ? "#008855" : style.text,
                  fontWeight: step.status === "active" ? 700 : 400,
                  padding: "4px 2px",
                  borderRadius: 4,
                  backgroundColor: step.status === "active" ? CHAIN_COLOR + "15" : "transparent",
                }}
                onClick={() => onStepClick && onStepClick(step.id)}
              >
                <div style={{ fontWeight: 600 }}>{info.name}</div>
                <div style={{ fontSize: 9, opacity: 0.7, marginTop: 2 }}>
                  {step.status === "active" ? "进行中" : step.status === "done" ? "已完成" : step.status === "skipped" ? "已跳过" : "待开始"}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 当前步骤详情 */}
      {chain.currentStep && !compact && (
        <div
          style={{
            marginTop: 12,
            padding: 8,
            backgroundColor: "#141414",
            borderRadius: 6,
            fontSize: 11,
            color: "#888",
          }}
        >
          <span style={{ color: CHAIN_COLOR, fontWeight: 600 }}>
            当前: {chain.currentStep}
          </span>
          {chain.scope && (
            <span style={{ marginLeft: 8 }}>
              范围: {chain.scope.slice(0, 30)}{chain.scope.length > 30 ? "..." : ""}
            </span>
          )}
        </div>
      )}

      {/* 进度条 */}
      <div
        style={{
          marginTop: 12,
          height: 4,
          backgroundColor: "#2a2a2a",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${Math.round((totalDone / total) * 100)}%`,
            backgroundColor: CHAIN_COLOR,
            transition: "width 0.3s ease",
          }}
        />
      </div>

      <div
        style={{
          marginTop: 6,
          fontSize: 10,
          color: "#666",
          textAlign: "center",
        }}
      >
        进度 {totalDone}/{total} · {Math.round((totalDone / total) * 100)}%
      </div>
    </div>
  );
}
