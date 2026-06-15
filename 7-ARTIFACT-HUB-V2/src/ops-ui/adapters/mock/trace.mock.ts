import type { TraceContractV1 } from "../traceAdapter.js";

export const mockTrace: TraceContractV1 = {
  trace_id: "trace_demo_001",
  status: "completed",
  workflow_id: "wf_demo_001",
  workflow_type: "legacy_chain",
  department: "governance",
  started_at: "2026-05-16T00:00:00Z",
  finished_at: "2026-05-16T00:02:30Z",
};
