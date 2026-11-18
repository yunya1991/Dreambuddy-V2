import type { TaskStage, TaskStatus } from "@/types/task-board";
import { TASK_STAGE_LABEL } from "@/types/task-board";
import { TaskStatusBadge } from "./primitives";

function fmtTime(ts?: number): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });
}

export interface TaskBoardHeaderProps {
  taskId: string;
  traceId?: string;
  /** 目标标题；目标尚未生成时由调用方给出统一的占位文案 */
  title: string;
  status: TaskStatus;
  stage: TaskStage;
  doneCount: number;
  totalCount: number;
  updatedAt?: number;
}

export function TaskBoardHeader({
  taskId,
  traceId,
  title,
  status,
  stage,
  doneCount,
  totalCount,
  updatedAt,
}: TaskBoardHeaderProps) {
  return (
    <header className="rounded-xl border border-slate-800 bg-slate-900/50 px-5 py-4">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-slate-400">
          任务 {taskId.slice(0, 18)}
        </span>
        {traceId && (
          <span className="font-mono text-slate-600">
            trace {traceId.slice(0, 12)}
          </span>
        )}
        <span className="ml-auto">
          <TaskStatusBadge status={status} />
        </span>
      </div>
      <h1 className="mt-2 text-xl font-semibold text-slate-100">{title}</h1>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
        <span>
          当前步骤：<span className="text-slate-200">{TASK_STAGE_LABEL[stage]}</span>
        </span>
        <span>
          OKR 通过：
          <span className="text-slate-200">
            {doneCount}/{totalCount}
          </span>
        </span>
        <span>更新于 {fmtTime(updatedAt)}</span>
      </div>
    </header>
  );
}
