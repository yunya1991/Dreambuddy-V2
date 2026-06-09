"use client";

const STATUS_CONFIG = {
  in_progress: { label: "执行中", bg: "#1a3a6b", color: "#60a5fa" },
  delivered:   { label: "已交付", bg: "#1a4a2e", color: "#4ade80" },
  accepted:    { label: "已接受", bg: "#14532d", color: "#86efac" },
  failed:      { label: "失败",   bg: "#4a1a1a", color: "#f87171" },
} as const;

interface WorkflowStatusBadgeProps {
  status: string;
}

export function WorkflowStatusBadge({ status }: WorkflowStatusBadgeProps) {
  const cfg = (STATUS_CONFIG as Record<string, { label: string; bg: string; color: string }>)[status]
    ?? { label: status, bg: "#2a2a2a", color: "#9ca3af" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{ backgroundColor: cfg.bg, color: cfg.color }}
    >
      {cfg.label}
    </span>
  );
}