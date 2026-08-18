"use client";

export interface WorkflowStep {
  id: string;
  label: string;
  status: "pending" | "running" | "success" | "error" | "skipped";
  description?: string;
}

const ICON: Record<WorkflowStep["status"], string> = {
  pending: "○", running: "◌", success: "✓", error: "✗", skipped: "—",
};

const COLOR: Record<WorkflowStep["status"], string> = {
  pending: "#6b7280", running: "#60a5fa", success: "#4ade80",
  error: "#f87171", skipped: "#9ca3af",
};

interface WorkflowStepListProps {
  steps: WorkflowStep[];
}

export function WorkflowStepList({ steps }: WorkflowStepListProps) {
  if (steps.length === 0) {
    return <div className="text-xs text-gray-500 italic py-2">暂无步骤数据</div>;
  }
  return (
    <ol className="space-y-1">
      {steps.map((step) => (
        <li key={step.id} className="flex items-start gap-2 text-sm">
          <span
            className="mt-0.5 w-4 shrink-0 text-center text-xs font-bold"
            style={{ color: COLOR[step.status] }}
          >
            {ICON[step.status]}
          </span>
          <div className="min-w-0">
            <span
              className="font-medium"
              style={{ color: step.status === "skipped" ? "#6b7280" : "#e5e7eb" }}
            >
              {step.label}
            </span>
            {step.description && (
              <p className="text-xs text-gray-500 mt-0.5 truncate">{step.description}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}