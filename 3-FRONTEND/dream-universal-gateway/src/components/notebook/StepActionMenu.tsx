"use client";

// ============================================================
// StepActionMenu — 步骤决策菜单
// 版本: v1.0 | 日期: 2026-06-15
// 提供 continue/skip/jump/finalize/pause 5 个操作按钮
// ============================================================

import type { StepAction } from "@/lib/notebook/types";

interface Props {
  taskId: string;
  onAction: (action: StepAction, targetStep?: number, reason?: string) => void;
  totalSteps?: number;
  disabled?: boolean;
}

const actions: Array<{
  id: StepAction;
  label: string;
  description: string;
  color: string;
  requiresTarget?: boolean;
}> = [
  { id: "continue", label: "继续下一步", description: "完成当前, 激活下一步", color: "#006b3f" },
  { id: "skip",     label: "跳过当前步", description: "标记为 skipped, 进入下一步", color: "#666" },
  { id: "finalize", label: "全部完成",   description: "跳过剩余所有步骤, 任务结束", color: "#8b6f1c" },
  { id: "pause",    label: "暂停任务",   description: "当前步骤恢复 pending, 稍后继续", color: "#8b3c3c" },
];

export default function StepActionMenu({ taskId, onAction, totalSteps = 7, disabled }: Props) {
  return (
    <div
      style={{
        padding: 16,
        backgroundColor: "#0d0d0d",
        border: "1px solid #1a1a1a",
        borderRadius: 8,
      }}
    >
      <div style={{ fontSize: 13, color: "#888", marginBottom: 12, fontWeight: 600 }}>
        🔰 每步完成后的决策菜单
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 8,
        }}
      >
        {actions.map((action) => (
          <button
            key={action.id}
            onClick={() => onAction(action.id)}
            disabled={disabled}
            style={{
              padding: "12px 14px",
              backgroundColor: disabled ? "#1a1a1a" : "#141414",
              border: `1px solid ${action.color}55`,
              borderRadius: 6,
              color: disabled ? "#444" : action.color,
              fontSize: 12,
              fontWeight: 500,
              cursor: disabled ? "not-allowed" : "pointer",
              textAlign: "left",
              transition: "all 0.15s",
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{action.label}</div>
            <div style={{ fontSize: 10, opacity: 0.7, lineHeight: 1.4 }}>{action.description}</div>
          </button>
        ))}
      </div>

      <div
        style={{
          marginTop: 10,
          fontSize: 11,
          color: "#555",
          display: "flex",
          gap: 8,
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
        }}
      >
        <div>
          <span style={{ color: "#777" }}>跳到 Step：</span>
          {Array.from({ length: totalSteps - 2 }, (_, i) => i + 2).map((n) => (
            <button
              key={n}
              onClick={() => onAction("jump", n)}
              disabled={disabled}
              style={{
                margin: "0 2px",
                padding: "2px 8px",
                backgroundColor: "#1a1a1a",
                border: "1px solid #333",
                borderRadius: 4,
                color: disabled ? "#444" : "#888",
                fontSize: 11,
                cursor: disabled ? "not-allowed" : "pointer",
              }}
            >
              Step {n}
            </button>
          ))}
        </div>
        <span style={{ opacity: 0.6 }}>task: {taskId.slice(-8)}</span>
      </div>
    </div>
  );
}
