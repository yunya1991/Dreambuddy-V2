import type { WorkflowType } from "../types.js";

export interface FeedEntranceItem {
  label: string;
  count: number;
  href: string;
}

export interface FeedHomepageSummary {
  departmentEntries: FeedEntranceItem[];
  stageEntries: FeedEntranceItem[];
}

export interface FeedListItem {
  id: string;
  category: string;
  artifactId: string;
  filename?: string; // actual filename on disk (may differ from artifactId.md)
  title: string;
  department: string;
  departmentLabel?: string;
  type: string;
  typeLabel?: string;
  status: string;
  date: string;
  chainPhase: string;
  tags: string[];
  excerpt?: string;
  url: string;
  workflowId?: string;
  workflowType?: WorkflowType;
  traceId?: string;
}

export interface FeedGovernanceContext {
  workflowId: string;
  workflowType: WorkflowType;
  traceId: string;
  chainPhase: string;
}

export interface FeedDetail extends FeedListItem {
  content: string;
  rawPath: string;
  governanceContext?: FeedGovernanceContext;
}

export interface FeedStats {
  total: number;
  byDepartment: Record<string, number>;
  byType: Record<string, number>;
  byStatus: Record<string, number>;
  byChainPhase: Record<string, number>;
}

export interface FeedQuery {
  category?: string;
  q?: string;
  department?: string;
  status?: string;
  chainPhase?: string;
  limit?: number;
  offset?: number;
}
