"use client";

/**
 * 定时任务（工作台左栏，会话下方，可折叠）。
 *
 * “＋”不在这里填表，而是新开一个会话：用户在对话里描述需求，
 * AI 协助改写，确认后由对话头部「设为定时任务」落库。
 * 到期任务由 /api/scheduled-tasks/run 触发现有任务中台执行。
 */

import { useCallback, useEffect, useState } from "react";
import type { ScheduledTask } from "@/lib/scheduled-tasks";

const POLL_MS = 60_000;

function formatInterval(minutes: number): string {
  if (minutes < 60) return `每 ${minutes} 分钟`;
  if (minutes % 60 === 0) return `每 ${minutes / 60} 小时`;
  return `每 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}

export function ScheduledTasksPanel({
  onStartDraft,
}: {
  /** 新开一个「定时任务」会话，由对话完成需求描述与确认 */
  onStartDraft: () => void;
}) {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [open, setOpen] = useState(true);
  const [running, setRunning] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/scheduled-tasks", {
        cache: "no-store",
      });
      const data = (await response.json().catch(() => null)) as
        | { success?: boolean; tasks?: ScheduledTask[] }
        | null;
      if (response.ok && data?.success && Array.isArray(data.tasks)) {
        setTasks(data.tasks);
      }
    } catch {
      // 列表不可达不阻塞工作台
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 到期自动执行（工作台打开期间）
  useEffect(() => {
    const tick = async () => {
      try {
        await fetch("/api/scheduled-tasks/run", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({}),
        });
        void load();
      } catch {
        // 失败等下一轮
      }
    };
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const toggle = async (task: ScheduledTask) => {
    await fetch("/api/scheduled-tasks", {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ id: task.id, enabled: !task.enabled }),
    }).catch(() => null);
    void load();
  };

  const remove = async (task: ScheduledTask) => {
    await fetch(`/api/scheduled-tasks?id=${encodeURIComponent(task.id)}`, {
      method: "DELETE",
    }).catch(() => null);
    void load();
  };

  const runNow = async (task: ScheduledTask) => {
    setRunning(task.id);
    try {
      await fetch("/api/scheduled-tasks/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ id: task.id }),
      });
      void load();
    } finally {
      setRunning(null);
    }
  };

  return (
    <section className="shrink-0 border-t border-slate-800 bg-slate-950/30">
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span
            className="h-1.5 w-1.5 shrink-0 rounded-full bg-slate-600"
            aria-hidden
          />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            定时任务
          </span>
          {tasks.length > 0 && (
            <span className="rounded-full bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
              {tasks.length}
            </span>
          )}
          <span className="ml-auto text-[10px] text-slate-500">
            {open ? "收起" : "展开"}
          </span>
        </button>
        <button
          type="button"
          onClick={onStartDraft}
          className="rounded px-1.5 py-0.5 text-xs text-indigo-300 hover:bg-slate-800"
          aria-label="新建定时任务"
          title="新开对话描述定时任务"
        >
          ＋
        </button>
      </div>

      {open && (
        <div className="space-y-1.5 border-t border-slate-800/70 p-2">
          {tasks.length === 0 && (
            <p className="px-1 py-2 text-[10px] text-slate-600">
              还没有定时任务。点「＋」新开对话，描述后由 AI 协助设置。
            </p>
          )}

          {tasks.map((task) => (
            <div
              key={task.id}
              className="rounded-lg border border-slate-800 bg-slate-900/40 px-2 py-1.5"
            >
              <div className="flex items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    task.enabled ? "bg-emerald-400" : "bg-slate-600"
                  }`}
                  aria-hidden
                />
                <span className="min-w-0 flex-1 truncate text-[11px] text-slate-200">
                  {task.title}
                </span>
                <span className="shrink-0 text-[9px] text-slate-500">
                  {formatInterval(task.interval_minutes)}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => void toggle(task)}
                  className="rounded border border-slate-700 px-1.5 py-0.5 text-[9px] text-slate-400 hover:text-slate-200"
                >
                  {task.enabled ? "暂停" : "启用"}
                </button>
                <button
                  type="button"
                  disabled={running === task.id}
                  onClick={() => void runNow(task)}
                  className="rounded border border-slate-700 px-1.5 py-0.5 text-[9px] text-slate-400 hover:text-slate-200 disabled:opacity-50"
                >
                  {running === task.id ? "执行中…" : "立即执行"}
                </button>
                <button
                  type="button"
                  onClick={() => void remove(task)}
                  className="ml-auto text-[9px] text-slate-500 hover:text-red-400"
                >
                  删除
                </button>
              </div>
            </div>
          ))}

          <p className="px-1 text-[9px] text-slate-600">
            到期任务在工作台打开期间自动执行；关闭页面后暂停。
          </p>
        </div>
      )}
    </section>
  );
}
