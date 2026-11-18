import Link from "next/link";
import { listPendingGateTasks } from "@/lib/task-board/server-store";
import { GATE_RISK, getGateMode } from "@/lib/task-board/gate-policy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const STATUS_LABEL: Record<string, string> = {
  waiting: "待确认",
  rejected: "已驳回",
  approved: "已确认",
};

const STATUS_STYLE: Record<string, string> = {
  waiting: "border-amber-800/60 bg-amber-950/30 text-amber-300",
  rejected: "border-red-800/60 bg-red-950/30 text-red-300",
  approved: "border-emerald-800/60 bg-emerald-950/30 text-emerald-300",
};

function formatTime(ts: number): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleString("zh-CN", { hour12: false });
}

export default async function GatesPage() {
  const tasks = await listPendingGateTasks();
  const mode = getGateMode();

  return (
    <div className="mx-auto w-full max-w-5xl space-y-4 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">门禁待办</h1>
          <p className="mt-1 text-xs text-slate-500">
            未确认门禁会阻塞对话与后续执行；高风险门始终需要人工确认。
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span
            className={`rounded-full border px-2 py-0.5 ${
              mode === "autonomy"
                ? "border-indigo-700/60 bg-indigo-950/30 text-indigo-300"
                : "border-slate-600/60 bg-slate-800/40 text-slate-300"
            }`}
          >
            {mode === "autonomy" ? "全权模式" : "人工干预"}
          </span>
          <span className="text-slate-400">{tasks.length} 个任务待处理</span>
        </div>
      </header>

      {tasks.length === 0 ? (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-8 text-center">
          <p className="text-sm text-slate-300">没有待确认门禁</p>
          <p className="mt-1 text-xs text-slate-500">
            新任务产生门禁后会出现在这里。
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {tasks.map((task) => (
            <li
              key={task.task_id}
              className="rounded-lg border border-slate-800 bg-slate-900/40 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-100">
                    {task.title}
                  </p>
                  <p className="mt-1 font-mono text-[11px] text-slate-500">
                    {task.task_id} · 更新于 {formatTime(task.updated_at)}
                  </p>
                </div>
                <Link
                  href={`/dashboard/task/${encodeURIComponent(task.task_id)}`}
                  className="rounded-md border border-indigo-700/60 bg-indigo-950/30 px-3 py-1 text-[11px] text-indigo-300 transition-colors hover:bg-indigo-900/40"
                >
                  进入任务
                </Link>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {task.pending_gates.map((gate) => (
                  <span
                    key={gate.gate_id}
                    className={`rounded border px-2 py-1 text-[11px] ${
                      STATUS_STYLE[gate.status] ?? STATUS_STYLE.waiting
                    }`}
                    title={`证据版本：${gate.evidence_ref}`}
                  >
                    {gate.title}
                    <span className="ml-1 opacity-70">
                      {STATUS_LABEL[gate.status] ?? gate.status}
                    </span>
                    <span className="ml-1 opacity-60">
                      风险 {GATE_RISK[gate.kind]}
                    </span>
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
