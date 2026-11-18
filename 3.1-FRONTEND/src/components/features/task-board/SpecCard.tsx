"use client";

/**
 * SPEC 摘要卡（工作台右栏）。
 *
 * 每个任务都会生成 SPEC；这里只做「看得见 + 可确认」，
 * 完整字段仍在看板 SpecPanel。确认是对话内动作，不产生治理待办。
 */

import { useState } from "react";
import type { TaskBoardSnapshot } from "@/types/task-board";

export function SpecCard({
  snapshot,
  onConfirm,
  busy,
}: {
  snapshot: TaskBoardSnapshot;
  onConfirm: () => void;
  busy?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const spec = snapshot.spec;
  if (!spec) return null;

  const confirmed = spec.status === "confirmed";

  return (
    <section className="mx-3 mt-3 rounded-lg border border-slate-800 bg-slate-900/40">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <span className="text-[11px] font-medium text-slate-200">SPEC</span>
        <span className="text-[10px] text-slate-500">v{spec.version}</span>
        <span
          className={`rounded border px-1.5 py-0.5 text-[9px] ${
            confirmed
              ? "border-emerald-700/60 text-emerald-300"
              : "border-amber-700/60 text-amber-300"
          }`}
        >
          {confirmed ? "已确认" : "草稿"}
        </span>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="ml-auto text-[10px] text-slate-500 hover:text-slate-300"
        >
          {open ? "收起" : "展开"}
        </button>
        {!confirmed && (
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className="rounded bg-indigo-500 px-2 py-0.5 text-[10px] font-medium text-white disabled:opacity-50"
          >
            {busy ? "确认中…" : "确认 SPEC"}
          </button>
        )}
      </div>
      {open && (
        <dl className="space-y-1.5 border-t border-slate-800/70 px-2.5 py-2">
          {spec.fields.map((field) => (
            <div key={field.key}>
              <dt className="text-[9px] uppercase tracking-wider text-slate-500">
                {field.label}
              </dt>
              <dd className="mt-0.5 text-[10px] leading-relaxed text-slate-300 break-words">
                {field.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
