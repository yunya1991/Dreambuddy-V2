export interface ChainAnomaly {
  kind: "missing_task" | "missing_result" | "orphan_artifact" | "broken_trace_link";
  artifactId: string;
  workflowType: "legacy_chain" | "trading_v2";
}

export interface ChainWorkflowItem {
  artifactId: string;
  title: string;
  category: string;
  department: string;
  workflowType: "legacy_chain" | "trading_v2";
  chainPhase: string;
  status: string;
  feedUrl: string;
}

export interface ChainOverviewViewModel {
  workflowGroups: {
    legacy_chain: ChainWorkflowItem[];
    trading_v2: ChainWorkflowItem[];
  };
  anomalies: ChainAnomaly[];
}
