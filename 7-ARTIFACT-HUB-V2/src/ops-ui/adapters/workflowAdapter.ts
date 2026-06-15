// Strictly typed against workflow-summary.v1 (L1 frozen, owner: solo)

export type ChainPhase = "A0" | "A1" | "A2" | "A3" | "A4" | "A5" | "A6" | "A7" | "A8" | "A9";

export interface WorkflowContractV1 {
  workflow_id: string;
  workflow_type: string;
  chain_phase: ChainPhase;
  status: "pending" | "running" | "completed" | "failed";
  latest_trace_id: string | null;
}

export interface WorkflowViewModel {
  workflowId: string;
  workflowType: string;
  chainPhase: ChainPhase;
  status: "pending" | "running" | "completed" | "failed";
  latestTraceId: string | null;
}

export function toWorkflowViewModel(data: WorkflowContractV1): WorkflowViewModel {
  return {
    workflowId: data.workflow_id,
    workflowType: data.workflow_type,
    chainPhase: data.chain_phase,
    status: data.status,
    latestTraceId: data.latest_trace_id,
  };
}
