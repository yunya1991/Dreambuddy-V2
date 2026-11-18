/**
 * TraceSpan → 业务事件（降级投影）。
 *
 * 用途：当编排侧只留下 O0 打点、没有业务事件时，用已发生的 span 尽量还原看板。
 * 原则：**只投影能确证的事实，推导不出来的字段宁可不展示，也不编造**。
 *
 * 可投影：
 * - C2（能力/子代理调用）→ agent.updated
 * - A1（验收门禁）      → acceptance.recorded
 * - G1（汇总输出，且 span 带 summary）→ summary.ready
 *
 * 不可投影（必须由编排侧显式给出业务事件）：
 * - intent.decided：需要用户原话与三判定结论
 * - spec.updated：需要 SPEC 六字段
 * - okr.updated：需要 O 与 KR 判据
 */
import type { TraceSpan, TraceStatus } from "@/types/run-trace";
import {
  buildTaskBoard,
  type AcceptanceRecord,
  type AgentRun,
  type AgentState,
  type TaskBoardEvent,
  type TaskBoardSnapshot,
  type TaskSummary,
  type Verdict,
} from "@/types/task-board";

export interface ProjectMeta {
  taskId: string;
  traceId: string;
}

const AGENT_STATE: Record<Exclude<TraceStatus, "running">, AgentState> = {
  done: "done",
  failed: "failed",
  degraded: "degraded",
  skipped: "pending",
};

const VERDICT: Record<Exclude<TraceStatus, "running">, Verdict> = {
  done: "pass",
  failed: "fail",
  degraded: "pending",
  skipped: "pending",
};

/** 同一 span_id 会先发 running、再发终态：保留最后一次 */
function finalSpans(spans: TraceSpan[]): TraceSpan[] {
  const byId = new Map<string, TraceSpan>();
  for (const span of spans) byId.set(span.span_id, span);
  return [...byId.values()]
    .filter((span) => span.status !== "running")
    .sort((a, b) => a.started_at - b.started_at || a.seq - b.seq);
}

function agentFromSpan(span: TraceSpan): AgentRun {
  return {
    role: span.role || span.capability_id || span.label,
    label: span.label,
    state: AGENT_STATE[span.status as Exclude<TraceStatus, "running">],
    capability_ids: span.capability_id ? [span.capability_id] : [],
    summary: span.summary,
    evidence_count: 0,
    duration_ms: span.duration_ms,
  };
}

function acceptanceFromSpan(span: TraceSpan): AcceptanceRecord {
  return {
    role: span.role || "okr_verifier",
    node_id: span.label,
    verdict: VERDICT[span.status as Exclude<TraceStatus, "running">],
    reason: span.summary,
    evidence_refs: [],
    ts: span.started_at + (span.duration_ms ?? 0),
  };
}

/** G1 无摘要时不投影，避免空结论把看板点亮 */
function summaryFromSpan(span: TraceSpan): TaskSummary | null {
  if (!span.summary) return null;
  return {
    conclusion: span.summary,
    key_points: [],
    data_quality: [{ item: "summary.key_points", status: "missing" }],
  };
}

export function projectTaskEvents(
  meta: ProjectMeta,
  spans: TraceSpan[],
): TaskBoardEvent[] {
  const events: TaskBoardEvent[] = [];
  const base = { task_id: meta.taskId, trace_id: meta.traceId };
  let seq = 0;

  for (const span of finalSpans(spans)) {
    const ts = span.started_at + (span.duration_ms ?? 0);
    if (span.stage === "C2") {
      events.push({ ...base, type: "agent.updated", seq: seq++, ts, payload: agentFromSpan(span) });
      continue;
    }
    if (span.stage === "A1") {
      events.push({
        ...base,
        type: "acceptance.recorded",
        seq: seq++,
        ts,
        payload: acceptanceFromSpan(span),
      });
      continue;
    }
    if (span.stage === "G1") {
      const summary = summaryFromSpan(span);
      if (!summary) continue;
      events.push({ ...base, type: "summary.ready", seq: seq++, ts, payload: summary });
    }
  }

  return events;
}

export function projectFromSpans(
  meta: ProjectMeta,
  spans: TraceSpan[],
): TaskBoardSnapshot {
  return buildTaskBoard(meta.taskId, meta.traceId, projectTaskEvents(meta, spans));
}
