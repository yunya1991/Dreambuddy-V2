"use client";

/**
 * 治理待办抽屉（工作台左栏下半部分）。
 *
 * 收起时只留一条角标栏，把空间让给会话列表；
 * 有新消息时自动展开并标亮对应条目。
 *
 * 数据来自治理类模块：门禁待办 / Agent 工作监控 / 记忆管理 / 人工审批 / 报告。
 * 当前对话窗口的确认走对话内弹窗，不在这里重复出现。
 */

import { useRouter } from "next/navigation";
import type {
  GovernanceInbox,
  GovernanceItem,
  GovernanceSource,
} from "@/lib/task-board/use-governance-inbox";

const SOURCE_STYLE: Record<GovernanceSource, string> = {
  gate: "border-amber-700/60 text-amber-300",
  monitor: "border-red-700/60 text-red-300",
  memory: "border-violet-700/60 text-violet-300",
  approval: "border-sky-700/60 text-sky-300",
  report: "border-emerald-700/60 text-emerald-300",
};

function formatWaiting(minutes: number): string {
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时`;
  return `${Math.floor(hours / 24)} 天`;
}

function ItemRow({
  item,
  active,
  isNew,
  onSelect,
}: {
  item: GovernanceItem;
  active: boolean;
  isNew: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-lg border px-2.5 py-2 text-left transition-colors ${
        active
          ? "border-indigo-700/70 bg-indigo-950/30"
          : isNew
            ? "border-amber-600/60 bg-amber-950/20"
            : "border-slate-800 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-900"
      }`}
    >
      <div className="flex items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-slate-200">
          {item.title}
        </span>
        {isNew && (
          <span className="shrink-0 rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-amber-300">
            新
          </span>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-500">
        <span
          className={`rounded border px-1.5 py-0.5 ${
            SOURCE_STYLE[item.source]
          }`}
        >
          {item.source_label}
        </span>
        {item.detail && (
          <span className="max-w-[9rem] truncate text-slate-500">
            {item.detail}
          </span>
        )}
        <span className="ml-auto text-slate-500">
          已等 {formatWaiting(item.waiting_minutes)}
        </span>
      </div>
    </button>
  );
}

export function GovernanceDrawer({
  inbox,
  open,
  onToggle,
  activeTaskId,
  onSelectTask,
}: {
  inbox: GovernanceInbox;
  open: boolean;
  onToggle: () => void;
  activeTaskId?: string | null;
  onSelectTask: (taskId: string) => void;
}) {
  const router = useRouter();
  const { items, total, highCount, newKeys } = inbox;

  return (
    <section
      className={`shrink-0 border-t ${
        total > 0
          ? "border-amber-800/50 bg-amber-950/10"
          : "border-slate-800 bg-slate-950/40"
      }`}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-900/60"
      >
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${
            highCount > 0
              ? "animate-pulse bg-amber-400"
              : total > 0
                ? "bg-sky-400"
                : "bg-slate-600"
          }`}
          aria-hidden
        />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          治理待办
        </span>
        {total > 0 ? (
          <span
            className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
              highCount > 0
                ? "bg-amber-500/20 text-amber-300"
                : "bg-slate-800 text-slate-300"
            }`}
          >
            {total}
          </span>
        ) : (
          <span className="text-[10px] text-slate-600">暂无待办</span>
        )}
        <span className="ml-auto text-[10px] text-slate-500">
          {open ? "收起" : "展开"}
        </span>
      </button>

      {open && (
        <div className="flex max-h-[42vh] flex-col border-t border-slate-800/70">
          <div className="flex-1 space-y-1.5 overflow-y-auto p-2">
            {items.length === 0 ? (
              <p className="px-1 py-3 text-[11px] text-slate-600">
                其它任务与系统告警暂无待办。当前对话的确认会直接弹窗，不占用这里。
              </p>
            ) : (
              items.map((item) => (
                <ItemRow
                  key={item.key}
                  item={item}
                  active={Boolean(
                    item.task_id && item.task_id === activeTaskId,
                  )}
                  isNew={newKeys.includes(item.key)}
                  onSelect={() => {
                    if (item.task_id && item.gate_id) {
                      onSelectTask(item.task_id);
                    } else {
                      router.push(item.href);
                    }
                  }}
                />
              ))
            )}
          </div>
          <div className="flex items-center gap-2 border-t border-slate-800/70 px-2 py-1.5">
            <button
              type="button"
              onClick={() => {
                inbox.snooze();
                onToggle();
              }}
              className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            >
              稍后（30 分钟）
            </button>
            <button
              type="button"
              onClick={() => inbox.refresh()}
              className="ml-auto text-[10px] text-slate-500 hover:text-slate-300"
            >
              刷新
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
