import Link from "next/link";
import { listTaskBoards } from "@/lib/task-board/server-store";
import {
  TaskStatusBadge,
  EmptyHint,
} from "@/components/features/task-board/primitives";
import type { TaskStage } from "@/types/task-board";

export const dynamic = "force-dynamic";

const STAGE_LABEL: Record<TaskStage, string> = {
  intent: "意图识别",
  spec: "SPEC",
  dispatch: "派工",
  execute: "执行中",
  accept: "验收",
  summary: "汇总",
};

function formatTime(ts: number): string {
  if (!ts) return "—";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", { hour12: false });
}

export default async function TaskListPage() {
  const tasks = await listTaskBoards();

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 p-6">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="text-base font-bold text-slate-100">任务看板</h1>
        <span className="text-[11px] text-slate-500">
          共 {tasks.length} 个任务 · 由对话与编排事件实时生成
        </span>
        <Link
          href="/dashboard/agent"
          className="ml-auto rounded-md border border-slate-700 px-2.5 py-1 text-[11px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
        >
          回到工作台 →
        </Link>
      </header>

      {tasks.length === 0 ? (
        <EmptyHint>
          还没有任务。在 Agent 工作台发起一次对话后，看板会按意图 / SPEC / OKR /
          子代理 / 验收逐段点亮。
        </EmptyHint>
      ) : (
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {tasks.map((task) => (
            <li key={task.task_id}>
              <Link
                href={`/dashboard/task/${encodeURIComponent(task.task_id)}`}
                className="block rounded-xl border border-slate-800 bg-slate-900/50 p-4 transition-colors hover:border-indigo-700/60 hover:bg-slate-900"
              >
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-slate-100">
                    {task.title}
                  </span>
                  <span className="ml-auto shrink-0">
                    <TaskStatusBadge status={task.status} />
                  </span>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
                  <span className="font-mono text-slate-600">
                    {task.task_id}
                  </span>
                  <span>
                    阶段 {STAGE_LABEL[task.stage] ?? task.stage}
                  </span>
                  <span>
                    验收 {task.done_count}/{task.total_count || "—"}
                  </span>
                  {task.pending_gates > 0 && (
                    <span className="text-amber-300">
                      待确认 {task.pending_gates}
                    </span>
                  )}
                  <span className="ml-auto">{formatTime(task.updated_at)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
