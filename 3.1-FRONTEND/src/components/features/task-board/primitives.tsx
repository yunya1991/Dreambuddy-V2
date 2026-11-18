/**
 * 任务看板共用视觉原子。
 *
 * 只做展示，不推导业务结论；缺失值显示「—」或空态，不填 0 冒充。
 */

import type { ReactNode } from "react";
import type { TaskStatus, Verdict, VerifyKind } from "@/types/task-board";

export const VERDICT_META: Record<
  Verdict,
  { label: string; badge: string; dot: string; text: string }
> = {
  pass: {
    label: "通过",
    badge: "border-emerald-700/60 bg-emerald-950/40 text-emerald-300",
    dot: "bg-emerald-400",
    text: "text-emerald-300",
  },
  pending: {
    label: "待复核",
    badge: "border-amber-700/60 bg-amber-950/40 text-amber-300",
    dot: "bg-amber-400",
    text: "text-amber-300",
  },
  fail: {
    label: "驳回",
    badge: "border-red-800/60 bg-red-950/40 text-red-300",
    dot: "bg-red-400",
    text: "text-red-300",
  },
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const meta = VERDICT_META[verdict] ?? VERDICT_META.pending;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${meta.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden />
      {meta.label}
    </span>
  );
}

export const TASK_STATUS_META: Record<
  TaskStatus,
  { label: string; badge: string; dot: string }
> = {
  pending: {
    label: "待启动",
    badge: "border-slate-700 bg-slate-800/60 text-slate-300",
    dot: "bg-slate-500",
  },
  running: {
    label: "执行中",
    badge: "border-indigo-700/60 bg-indigo-950/40 text-indigo-300",
    dot: "bg-indigo-400 animate-pulse",
  },
  waiting: {
    label: "待人工确认",
    badge: "border-amber-700/60 bg-amber-950/40 text-amber-300",
    dot: "bg-amber-400 animate-pulse",
  },
  done: {
    label: "已完成",
    badge: "border-emerald-700/60 bg-emerald-950/40 text-emerald-300",
    dot: "bg-emerald-400",
  },
  degraded: {
    label: "降级",
    badge: "border-amber-700/60 bg-amber-950/40 text-amber-300",
    dot: "bg-amber-400",
  },
  failed: {
    label: "失败",
    badge: "border-red-800/60 bg-red-950/40 text-red-300",
    dot: "bg-red-400",
  },
  terminated: {
    label: "已终止",
    badge: "border-slate-600/60 bg-slate-900/60 text-slate-400",
    dot: "bg-slate-500",
  },
};

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const meta = TASK_STATUS_META[status] ?? TASK_STATUS_META.pending;
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${meta.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden />
      {meta.label}
    </span>
  );
}

export const VERIFY_LABEL: Record<VerifyKind, string> = {
  evidence_backed: "证据匹配",
  gap_closed: "缺口关闭",
  c_action: "决策动作",
};

export function SectionCard({
  title,
  meta,
  children,
  testId,
}: {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section
      data-testid={testId}
      className="rounded-xl border border-slate-800 bg-slate-900/50"
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-800 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
        {meta && <div className="ml-auto flex items-center gap-2">{meta}</div>}
      </header>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

export function EmptyHint({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-xs leading-5 text-slate-500">
      {children}
    </p>
  );
}

/** 0-1 进度；传入非法值时不显示数字，避免把缺失当成 0% */
export function ProgressBar({ value }: { value: number }) {
  const safe = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(safe * 100)}
      className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800"
    >
      <div
        className="h-full rounded-full bg-indigo-500 transition-[width] duration-200"
        style={{ width: `${Math.round(safe * 100)}%` }}
      />
    </div>
  );
}
