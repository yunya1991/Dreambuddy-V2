import type { Artifact } from "./types.js";

export type WorkflowType = "legacy_chain" | "trading_v2";

export function isLegacyChain(workflowType: string | undefined): boolean {
  return workflowType === "legacy_chain" || workflowType === undefined || workflowType === "";
}

export function isTradingV2(workflowType: string | undefined): boolean {
  return workflowType === "trading_v2";
}

export function normalizeWorkflowType(raw: string | undefined): WorkflowType {
  if (raw === "trading_v2") return "trading_v2";
  return "legacy_chain";
}

export function groupByWorkflowType(artifacts: Artifact[]): {
  legacy_chain: Artifact[];
  trading_v2: Artifact[];
} {
  const result: { legacy_chain: Artifact[]; trading_v2: Artifact[] } = {
    legacy_chain: [],
    trading_v2: [],
  };
  for (const a of artifacts) {
    result[normalizeWorkflowType(a.workflow_type)].push(a);
  }
  return result;
}
