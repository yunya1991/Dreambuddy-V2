"use client";

import { WorkflowStatusBadge } from "./WorkflowStatusBadge";
import { WorkflowStepList } from "./WorkflowStepList";
import type { WorkflowStep } from "./WorkflowStepList";

export type WorkflowType = "legacy_chain" | "trading_v2";

const WORKFLOW_META: Record<WorkflowType, { label: string; accent: string; description: string }> = {
  legacy_chain: {
    label: "Legacy Chain",
    accent: "#6366f1",
    description: "经典链路 (A1→A9 执行环)",
  },
  trading_v2: {
    label: "Trading V2",
    accent: "#f59e0b",
    description: "双轨制交易链路 (执行 + 情报)",
  },
};

export type { WorkflowStep as WorkflowCardStep };

export interface WorkflowCardProps {
  workflowId: string;
  workflowType: WorkflowType;
  title?: string;
  executionStatus?: string;
  steps?: WorkflowStep[];
  startedAt?: string;
  finishedAt?: string;
  className?: string;
}

export function WorkflowCard({
  workflowId,
  workflowType,
  title,
  executionStatus,
  steps = [],
  startedAt,
  finishedAt,
  className = "",
}: WorkflowCardProps) {
  const meta = WORKFLOW_META[workflowType];
  return (
    <div
      className={`rounded-lg border p-4 flex flex-col gap-3 ${className}`}
      style={{ borderColor: meta.accent + "44", backgroundColor: "#111827" }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-xs font-semibold px-1.5 py-0.5 rounded"
              style={{ backgroundColor: meta.accent + "22", color: meta.accent }}
            >
              {meta.label}
            </span>
            {executionStatus && <WorkflowStatusBadge status={executionStatus} />}
          </div>
          <h3 className="text-sm font-medium text-white mt-1 truncate">
            {title ?? workflowId}
          </h3>
          <p className="text-xs text-gray-500">{meta.description}</p>
        </div>
      </div>
      {steps.length > 0 && (
        <div>
          <p className="text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wide">
            执行步骤
          </p>
          <WorkflowStepList steps={steps} />
        </div>
      )}
      {(startedAt || finishedAt) && (
        <div className="flex gap-4 text-xs text-gray-500 pt-1 border-t border-gray-800">
          {startedAt && <span>开始: {new Date(startedAt).toLocaleString("zh-CN")}</span>}
          {finishedAt && <span>完成: {new Date(finishedAt).toLocaleString("zh-CN")}</span>}
        </div>
      )}
    </div>
  );
}