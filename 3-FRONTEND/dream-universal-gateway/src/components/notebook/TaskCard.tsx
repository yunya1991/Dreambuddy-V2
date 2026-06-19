"use client";

// ============================================================
// TaskCard — 任务摘要卡片
// 版本: v1.0 | 日期: 2026-06-15
// 显示单个任务的标题/阶段/进度/时间
// ============================================================

import type { NotebookTask } from "@/lib/notebook/types";

interface Props {
  task: NotebookTask;
  isCurrent?: boolean;
  onClick?: () => void;
}

const phaseColors: Record<string, { bg: string; border: string; label: string }> = {
  todo:    { bg: "#1a1a0d", border: "#4a4a1a", label: "待办" },
  active:  { bg: "#0d1a2d", border: "#0066ff", label: "活跃" },
  done:    { bg: "#0d2d1a", border: "#006b3f", label: "已完成" },
  archive: { bg: "#1a0d1a", border: "#4a3f4a", label: "归档" },
};

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function TaskCard({ task, isCurrent, onClick }: Props) {
  const color = phaseColors[task.phase] || phaseColors.active;
  const doneCount = task.steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const percent = Math.round((doneCount / task.steps.length) * 100);

  return (
    <div
      onClick={onClick}
      style={{
        padding: 14,
        backgroundColor: isCurrent ? color.bg : "#141414",
        border: `1px solid ${isCurrent ? color.border : "#1f1f1f"}`,
        borderRadius: 8,
        cursor: onClick ? "pointer" : "default",
        marginBottom: 8,
        transition: "all 0.15s",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: "#ddd" }}>{task.title}</div>
        <span
          style={{
            fontSize: 10,
            padding: "2px 8px",
            backgroundColor: `${color.border}44`,
            color: "#fff",
            borderRadius: 4,
            fontWeight: 600,
          }}
        >
          {color.label}
        </span>
      </div>

      <div style={{ fontSize: 11, color: "#777", marginBottom: 8, lineHeight: 1.5 }}>
        <span style={{ color: "#666" }}>intent: </span>
        <span style={{ color: "#0088aa" }}>{task.intent}</span>
        {Object.keys(task.entities || {}).length > 0 && (
          <>
            <span style={{ color: "#666" }}> · </span>
            {Object.entries(task.entities).map(([k, v], i) => (
              <span key={k} style={{ color: "#88aa" }}>
                {i > 0 && ", "}
                {v || k}
              </span>
            ))}
          </>
        )}
      </div>

      <div
        style={{
          height: 4,
          backgroundColor: "#1a1a1a",
          borderRadius: 2,
          overflow: "hidden",
          marginBottom: 6,
        }}
      >
        <div
          style={{
            width: `${percent}%`,
            height: "100%",
            backgroundColor: color.border,
            transition: "width 0.3s",
          }}
        />
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "#555",
        }}
      >
        <span>{doneCount}/{task.steps.length} 步</span>
        <span>{formatDate(task.lastActiveAt)}</span>
      </div>
    </div>
  );
}
