// Strictly typed against trace-summary.v1 (L1 frozen, owner: solo)

export interface TraceContractV1 {
  trace_id: string;
  status: "running" | "completed" | "failed";
  workflow_id: string;
  workflow_type: string;
  department: string;
  started_at: string;
  finished_at: string | null;
}

export interface TraceViewModel {
  traceId: string;
  status: "running" | "completed" | "failed";
  workflowId: string;
  workflowType: string;
  department: string;
  startedAt: string;
  finishedAt: string | null;
  durationMs: number | null;
}

export function toTraceViewModel(data: TraceContractV1): TraceViewModel {
  const durationMs =
    data.finished_at
      ? new Date(data.finished_at).getTime() - new Date(data.started_at).getTime()
      : null;

  return {
    traceId: data.trace_id,
    status: data.status,
    workflowId: data.workflow_id,
    workflowType: data.workflow_type,
    department: data.department,
    startedAt: data.started_at,
    finishedAt: data.finished_at,
    durationMs,
  };
}
