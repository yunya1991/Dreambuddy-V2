/**
 * 服务端调度打点器（O0）。
 *
 * - 每个阶段/能力调用产生一个 span；同一 span_id 会先发 running、再发终态；
 * - sink 未挂载时只进 history，挂载后实时推送（UIMessage data-trace part）；
 * - 任何 sink 异常都吞掉，绝不影响主链路（FAIL-OPEN）。
 */
import { randomUUID } from "crypto";
import type { TraceSpan, TraceStage, TraceStatus } from "@/types/run-trace";

export type TraceSink = (span: TraceSpan) => void;

export interface TraceHandle {
  traceId: string;
  /** 已产生的 span（含 running 与终态），用于流开始前的历史回放 */
  history: TraceSpan[];
  attach: (sink: TraceSink) => void;
  /** 开始一个 span，返回结束函数 */
  start: (
    stage: TraceStage,
    label: string,
    extra?: Partial<Pick<TraceSpan, "role" | "capability_id" | "summary" | "degraded">>,
  ) => (status?: TraceStatus, summary?: string) => void;
  emit: (span: TraceSpan) => void;
}

export function createTraceHandle(traceId: string): TraceHandle {
  let sink: TraceSink | undefined;
  let seq = 0;
  const history: TraceSpan[] = [];

  const emit = (span: TraceSpan) => {
    history.push(span);
    try {
      sink?.(span);
    } catch {
      // FAIL-OPEN：轨迹不能影响主链路
    }
  };

  const start: TraceHandle["start"] = (stage, label, extra = {}) => {
    const span: TraceSpan = {
      span_id: `sp_${seq}_${randomUUID().slice(0, 6)}`,
      trace_id: traceId,
      stage,
      label,
      status: "running",
      started_at: Date.now(),
      seq: seq++,
      ...extra,
    };
    emit(span);
    return (status: TraceStatus = "done", summary?: string) => {
      emit({
        ...span,
        status,
        summary: summary ?? span.summary,
        duration_ms: Date.now() - span.started_at,
      });
    };
  };

  return {
    traceId,
    history,
    attach: (next) => {
      sink = next;
    },
    start,
    emit,
  };
}
