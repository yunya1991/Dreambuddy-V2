import type { WorkflowContractV1 } from "../workflowAdapter.js";

export const mockWorkflow: WorkflowContractV1 = {
  workflow_id: "wf_demo_001",
  workflow_type: "legacy_chain",
  chain_phase: "A3",
  status: "running",
  latest_trace_id: "trace_demo_001",
};
