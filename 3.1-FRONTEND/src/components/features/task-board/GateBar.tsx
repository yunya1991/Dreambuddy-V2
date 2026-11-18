"use client";

/**
 * 门禁条：看板顶部的人工确认入口。
 *
 * 只展示事实，不推导结论；未确认的门禁必须阻断下游。
 * 驳回必须填原因，并可指定回转门。
 */

import { useEffect, useState } from "react";
import {
  GATE_STAGE,
  GATE_TITLE,
  TASK_STAGE_LABEL,
  type GateKind,
  type TaskGate,
} from "@/types/task-board";
import type { GateDecisionInput } from "@/lib/task-board/use-task-board";

const REWIND_OPTIONS: GateKind[] = [
  "intent",
  "spec",
  "dispatch",
  "acceptance",
  "summary",
];

interface PrecheckVote {
  model_id: string;
  family: string;
  verdict: "pass" | "fail" | "needs_human";
  confidence: number | null;
  latency_ms: number;
  degraded: boolean;
}

interface PrecheckResult {
  verdict: "pass" | "fail" | "needs_human";
  quorum: { reasons: string[]; votes: PrecheckVote[] };
}

const VERDICT_LABEL: Record<PrecheckVote["verdict"], string> = {
  pass: "建议通过",
  fail: "建议驳回",
  needs_human: "需人工",
};

const VERDICT_STYLE: Record<PrecheckVote["verdict"], string> = {
  pass: "border-emerald-800/60 bg-emerald-950/30 text-emerald-300",
  fail: "border-red-800/60 bg-red-950/30 text-red-300",
  needs_human: "border-amber-800/60 bg-amber-950/30 text-amber-300",
};

export function GateBar({
  taskId,
  gates,
  busyGateId,
  mode = "human",
  onDecide,
}: {
  taskId: string;
  gates: TaskGate[];
  busyGateId?: string | null;
  mode?: "autonomy" | "human";
  onDecide: (
    decision: GateDecisionInput,
  ) => Promise<{ ok: boolean; error?: string }>;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [comment, setComment] = useState("");
  const [rewindTo, setRewindTo] = useState<GateKind | "">("");
  const [error, setError] = useState<string | null>(null);
  const [precheck, setPrecheck] = useState<PrecheckResult | null>(null);
  const [prechecking, setPrechecking] = useState(false);
  const [precheckError, setPrecheckError] = useState<string | null>(null);

  const pending = gates.filter(
    (gate) => gate.required && gate.status !== "approved",
  );
  const current = pending[0];

  useEffect(() => {
    setPrecheck(null);
    setPrecheckError(null);
    setRejecting(false);
  }, [current?.gate_id]);

  if (!current) {
    return (
      <div
        data-testid="gate-bar"
        className="flex items-center gap-2 rounded-xl border border-emerald-900/50 bg-emerald-950/20 px-4 py-2.5 text-xs text-emerald-300"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden />
        门禁已全部确认
        {gates.length > 0 && (
          <span className="text-emerald-500/70">共 {gates.length} 道</span>
        )}
      </div>
    );
  }

  const busy = busyGateId === current.gate_id;
  const title = current.title || GATE_TITLE[current.kind];
  // 做减法：低/中风险门可一次批量确认；验收门永远单独确认
  const batchable = pending.filter((gate) => gate.kind !== "acceptance");

  async function runPrecheck() {
    setPrechecking(true);
    setPrecheckError(null);
    try {
      const response = await fetch(
        `/api/task/${encodeURIComponent(taskId)}/gate/precheck`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ gate_id: current.gate_id }),
        },
      );
      const data = (await response.json().catch(() => null)) as
        | { success?: boolean; error?: string; precheck?: PrecheckResult }
        | null;
      if (!response.ok || !data?.success || !data.precheck) {
        setPrecheckError(data?.error || "预审失败");
        return;
      }
      setPrecheck(data.precheck);
    } catch {
      setPrecheckError("network_error");
    } finally {
      setPrechecking(false);
    }
  }

  async function submit(status: "approved" | "rejected") {
    setError(null);
    if (status === "rejected" && !comment.trim()) {
      setError("驳回必须填写原因");
      return;
    }
    const result = await onDecide({
      gateId: current.gate_id,
      status,
      comment: status === "rejected" ? comment.trim() : undefined,
      rewindTo:
        status === "rejected" && rewindTo ? (rewindTo as GateKind) : undefined,
    });
    if (!result.ok) {
      setError(result.error || "提交失败");
      return;
    }
    setRejecting(false);
    setComment("");
    setRewindTo("");
  }

  return (
    <div
      data-testid="gate-bar"
      className="rounded-xl border border-amber-800/60 bg-amber-950/20"
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-amber-900/40 px-4 py-2.5">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" aria-hidden />
        <h2 className="text-sm font-semibold text-amber-200">工作门禁</h2>
        <span
          className={`rounded-full border px-2 py-0.5 text-[10px] ${
            mode === "autonomy"
              ? "border-indigo-700/60 bg-indigo-950/30 text-indigo-300"
              : "border-slate-600/60 bg-slate-800/40 text-slate-300"
          }`}
          title={
            mode === "autonomy"
              ? "低/中风险门自动确认；验收门仍需人工"
              : "所有门禁均需人工确认"
          }
        >
          {mode === "autonomy" ? "全权模式" : "人工干预"}
        </span>
        <span className="rounded-full border border-amber-700/60 bg-amber-900/30 px-2 py-0.5 text-[10px] text-amber-300">
          {title}
        </span>
        <span className="text-[11px] text-amber-500/80">
          步骤：{TASK_STAGE_LABEL[GATE_STAGE[current.kind]]}
        </span>
        <span className="ml-auto text-[11px] text-amber-500/80">
          待确认 {pending.length} / 共 {gates.length} 道
        </span>
      </header>

      <div className="space-y-3 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
          <span className="rounded border border-slate-700 bg-slate-800/60 px-2 py-0.5 font-mono text-[10px] text-slate-300">
            {current.evidence_ref}
          </span>
          <span>确认只对当前证据版本有效；证据更新后需重新确认。</span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={prechecking}
            onClick={runPrecheck}
            className="rounded-md border border-slate-600 bg-slate-800/60 px-3 py-1 text-[11px] text-slate-300 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {prechecking ? "预审中…" : "机器预审"}
          </button>
          {precheck && (
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] ${
                VERDICT_STYLE[precheck.verdict]
              }`}
            >
              预审：{VERDICT_LABEL[precheck.verdict]}
            </span>
          )}
          {precheckError && (
            <span className="text-[11px] text-amber-400">
              预审不可用：{precheckError}
            </span>
          )}
          {precheck?.quorum.votes.map((vote) => (
            <span
              key={vote.model_id}
              title={vote.family}
              className={`rounded border px-2 py-0.5 text-[10px] ${
                VERDICT_STYLE[vote.verdict]
              }`}
            >
              {vote.model_id.split(":").pop()} · {VERDICT_LABEL[vote.verdict]}
              {vote.confidence !== null &&
                ` ${(vote.confidence * 100).toFixed(0)}%`}
              {` · ${vote.latency_ms}ms`}
            </span>
          ))}
        </div>
        {precheck && (
          <p className="text-[10px] text-slate-500">
            模型票仅为预审意见；high / critical 门必须人工确认。
          </p>
        )}

        {!rejecting ? (
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => submit("approved")}
              className="rounded-md border border-emerald-700 bg-emerald-900/40 px-3 py-1.5 text-xs font-medium text-emerald-200 transition-colors hover:bg-emerald-900/60 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "提交中…" : "通过"}
            </button>
            {batchable.length > 1 && (
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  setError(null);
                  const result = await onDecide({
                    gateId: current.gate_id,
                    gateIds: batchable.map((gate) => gate.gate_id),
                    status: "approved",
                  });
                  if (!result.ok) setError(result.error || "批量确认失败");
                }}
                className="rounded-md border border-sky-700 bg-sky-950/40 px-3 py-1.5 text-xs font-medium text-sky-200 transition-colors hover:bg-sky-900/60 disabled:cursor-not-allowed disabled:opacity-50"
                title="同一证据版本下，一次确认所有低/中风险门"
              >
                批量确认 {batchable.length} 道
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setRejecting(true);
                setError(null);
              }}
              className="rounded-md border border-red-800 bg-red-950/30 px-3 py-1.5 text-xs font-medium text-red-300 transition-colors hover:bg-red-950/50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              驳回
            </button>
            {error && <span className="text-[11px] text-red-400">{error}</span>}
          </div>
        ) : (
          <div className="space-y-2">
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={2}
              placeholder="填写驳回原因（必填）"
              className="w-full rounded-md border border-slate-700 bg-slate-900/80 px-3 py-2 text-xs text-slate-200 outline-none focus:border-amber-700"
            />
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-[11px] text-slate-400">回转至</label>
              <select
                value={rewindTo}
                onChange={(event) =>
                  setRewindTo(event.target.value as GateKind | "")
                }
                className="rounded-md border border-slate-700 bg-slate-900/80 px-2 py-1 text-[11px] text-slate-200"
              >
                <option value="">按默认策略</option>
                {REWIND_OPTIONS.filter((kind) => kind !== current.kind).map(
                  (kind) => (
                    <option key={kind} value={kind}>
                      {GATE_TITLE[kind]}
                    </option>
                  ),
                )}
              </select>
              <button
                type="button"
                disabled={busy || !comment.trim()}
                onClick={() => submit("rejected")}
                className="rounded-md border border-red-800 bg-red-950/40 px-3 py-1.5 text-xs font-medium text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? "提交中…" : "确认驳回"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setRejecting(false);
                  setComment("");
                  setError(null);
                }}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300"
              >
                取消
              </button>
              {error && <span className="text-[11px] text-red-400">{error}</span>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
