"use client";

/**
 * O0 调度轨迹面板：右侧时间线，展示一次对话的 S→C→A→G 实际调度。
 * 数据来自 UIMessage 的 data-trace part（服务端 run-trace 打点），与 reasoning 同流。
 */

import React, { useMemo } from "react";
import type { TraceSpan, TraceStatus } from "@/types/run-trace";
import { TRACE_STAGE_LABEL } from "@/types/run-trace";

const STATUS_META: Record<
  TraceStatus,
  { dot: string; text: string; label: string }
> = {
  running: { dot: "bg-indigo-400 animate-pulse", text: "text-indigo-300", label: "进行中" },
  done: { dot: "bg-emerald-400", text: "text-emerald-300", label: "完成" },
  degraded: { dot: "bg-amber-400", text: "text-amber-300", label: "降级" },
  failed: { dot: "bg-red-400", text: "text-red-300", label: "失败" },
  skipped: { dot: "bg-slate-500", text: "text-slate-400", label: "跳过" },
};

function fmtDuration(ms?: number): string {
  if (ms === undefined) return "…";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function clip(text: string, max = 56): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function TracePanel({
  spans,
  onClose,
}: {
  spans: TraceSpan[];
  onClose?: () => void;
}) {
  // 同一 span 会先发 running 再发终态：按 span_id 保留最新，再按时间排序
  const rows = useMemo(() => {
    const map = new Map<string, TraceSpan>();
    for (const span of spans) map.set(span.span_id, span);
    return [...map.values()].sort(
      (a, b) => a.started_at - b.started_at || a.seq - b.seq,
    );
  }, [spans]);

  const totalMs = useMemo(() => {
    if (rows.length === 0) return 0;
    const start = Math.min(...rows.map((r) => r.started_at));
    const end = Math.max(...rows.map((r) => r.started_at + (r.duration_ms ?? 0)));
    return end - start;
  }, [rows]);

  const traceId = rows[0]?.trace_id;

  return (
    <aside
      data-testid="agent-trace-panel"
      className="flex w-[340px] shrink-0 flex-col border-l border-slate-800 bg-slate-950/60"
    >
      <div className="flex shrink-0 items-center gap-2 border-b border-slate-800 px-3 py-2">
        <span className="text-xs font-medium text-slate-300">调度轨迹</span>
        <span className="rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-[10px] text-slate-500">
          O0
        </span>
        <span className="text-[10px] text-slate-500">
          {rows.length} 步 · {fmtDuration(totalMs)}
        </span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="ml-auto rounded px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-slate-800 hover:text-slate-300"
            aria-label="隐藏调度轨迹"
          >
            隐藏
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {rows.length === 0 ? (
          <p className="text-[11px] leading-5 text-slate-600">
            发起一次分析后，这里会显示真实的 S→C→A→G 调度步骤、耗时与降级项。
          </p>
        ) : (
          <ol className="relative space-y-3 border-l border-slate-800 pl-3">
            {rows.map((row) => {
              const meta = STATUS_META[row.status] ?? STATUS_META.skipped;
              return (
                <li key={row.span_id} className="relative" data-testid="trace-row">
                  <span
                    className={`absolute -left-[17px] top-1.5 h-2 w-2 rounded-full ${meta.dot}`}
                    aria-hidden
                  />
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[11px] text-slate-300">
                      {row.label}
                    </span>
                    <span className="shrink-0 text-[10px] text-slate-500">
                      {fmtDuration(row.duration_ms)}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]">
                    <span className="rounded bg-slate-800 px-1 py-0.5 text-slate-400">
                      {TRACE_STAGE_LABEL[row.stage] ?? row.stage}
                    </span>
                    <span className={meta.text}>{meta.label}</span>
                    {row.capability_id && (
                      <span className="truncate text-slate-600">
                        {row.capability_id}
                      </span>
                    )}
                    {row.summary && (
                      <span className="w-full text-slate-500">
                        {clip(row.summary)}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>

      {traceId && (
        <div className="shrink-0 border-t border-slate-800 px-3 py-2 text-[10px] text-slate-600">
          trace: {traceId.slice(0, 18)}
        </div>
      )}
    </aside>
  );
}

export default TracePanel;
