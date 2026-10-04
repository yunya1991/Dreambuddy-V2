"use client";

const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  in_progress: { label: "执行中", className: "bg-blue-500/20 text-blue-400" },
  delivered:   { label: "已交付", className: "bg-green-500/20 text-green-400" },
  accepted:    { label: "已接受", className: "bg-green-700/20 text-green-300" },
  failed:      { label: "失败",   className: "bg-red-500/20 text-red-400" },
};

interface WorkflowStatusBadgeProps {
  status: string;
}

export function WorkflowStatusBadge({ status }: WorkflowStatusBadgeProps) {
  const cfg = STATUS_CONFIG[status] ?? { label: status, className: "bg-slate-800 text-slate-400" };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cfg.className}`}
    >
      {cfg.label}
    </span>
  );
}
