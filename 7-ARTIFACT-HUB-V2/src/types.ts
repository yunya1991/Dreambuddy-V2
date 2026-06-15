export type ISODateString = string;

export type ArtifactStatus = "completed" | "processing" | "failed" | "unknown";

export type ArtifactType =
  | "knowledge"
  | "trading"
  | "dashboard_task"
  | "dashboard_result"
  | "unknown";

export type WorkflowType = "legacy_chain" | "trading_v2";

export type RouteMode =
  | "DIRECT_RETURN"
  | "INCREMENTAL_UPDATE"
  | "RUN_CHAIN"
  | "NEED_CONFIRMATION";

export type DagNodeStatus = "pending" | "running" | "success" | "error" | "skipped";

export type DagNodeType =
  | "intent_recognition"
  | "artifact_retrieval"
  | "artifact_scoring"
  | "policy_gate"
  | "work_order_emit"
  | "result_ingest"
  | "artifact_publish";

export interface ArtifactIndexItem {
  id: string;
  title: string;
  department: string;
  type: ArtifactType;
  date: ISODateString;
  status: ArtifactStatus;
  chain_phase: string;
  url: string;
  tags: string;
  workflow_id?: string;
  workflow_type?: WorkflowType;
  excerpt?: string;
}

export interface DagNode {
  node_id: string;
  type: DagNodeType;
  status: DagNodeStatus;
  inputs: Array<{ kind: "artifact" | "text"; ref: string; summary?: string }>;
  outputs: Array<{ kind: "artifact" | "text"; ref: string; summary?: string }>;
  metrics?: { latency_ms?: number; cost_tokens?: number };
  evidence?: Array<{ kind: "rule" | "score" | "artifact"; detail: string }>;
}

export interface DagEdge {
  from: string;
  to: string;
}

export interface RoutingPlan {
  trace_id: string;
  mode: RouteMode;
  reason: Record<string, unknown>;
  dag: { nodes: DagNode[]; edges: DagEdge[] };
}

export interface Intent {
  text: string;
  domain?: string;
  task_type?: string;
  entities?: Record<string, unknown>;
  constraints?: Record<string, unknown>;
  risk_score?: number; // 0-1, higher = more risky
}

// Phase 1 governance object model — task-pr9-ahv2-object-model-align-1

export type ExecutionStatus = "in_progress" | "delivered" | "accepted" | "failed";

export type DecisionVerdict = "accepted" | "rework" | "block";

export interface Artifact {
  artifact_id: string;
  title: string;
  department: string;
  category: string;
  type: ArtifactType;
  chain_phase: string;
  workflow_id: string;
  workflow_type: WorkflowType;
  trace_id: string;
  status: ArtifactStatus;
  relative_path: string;
  created_at: ISODateString;
}

export interface Decision {
  decision_id: string;
  trace_id: string;
  intent_id: string;
  department: string;
  policy_version: string;
  selected_route: string;
  reason: string;
  evidence_refs: string[];
  decision_level: string;
  created_at: ISODateString;
}

export interface Execution {
  execution_id: string;
  trace_id: string;
  intent_id: string;
  decision_id: string;
  workflow_id: string;
  workflow_type: WorkflowType;
  department: string;
  status: ExecutionStatus;
  started_at: ISODateString;
  finished_at?: ISODateString;
}

export interface AuditRecord {
  audit_id: string;
  trace_id: string;
  department: string;
  decision_snapshot: unknown;
  execution_snapshot: unknown;
  events: unknown[];
  risk_flags?: string[];
  review_notes?: string;
  created_at: ISODateString;
}

// =============================================================================
// GOVERNANCE_SPEC Phase 1 — task-pr9-ahv2-governance-spec-impl-1
// Based on GOVERNANCE_SPEC.md v1.1 Section 4-8
// =============================================================================

/**
 * Decision Level Tags (GOVERNANCE_SPEC.md Section 4)
 * L1: Department-internal low-risk items
 * L2: Cross-department coordination or co-signature required
 * L3: Must enter human approval gate
 */
export type DecisionLevel = "L1" | "L2" | "L3";

/**
 * L1 Decision Context (GOVERNANCE_SPEC.md Section 4.1)
 * Typical scenarios: content label corrections, non-core routing adjustments
 */
export interface L1DecisionContext {
  decision_level: "L1";
  department: string;
  category: "content_correction" | "routing_adjustment" | "summary_archive" | "retry" | "other";
  description: string;
}

/**
 * L2 Decision Context (GOVERNANCE_SPEC.md Section 4.2)
 * Typical scenarios: cross-department flow changes, priority adjustments, visibility changes
 */
export interface L2DecisionContext {
  decision_level: "L2";
  departments: string[];
  category: "flow_rearrangement" | "priority_adjustment" | "visibility_change" | "distribution_switch" | "other";
  description: string;
  co_signatures?: string[]; // Agent IDs who co-signed
}

/**
 * L3 Decision Context (GOVERNANCE_SPEC.md Section 4.3)
 * Typical scenarios: core strategy changes, high-risk fund actions, major organization changes
 */
export interface L3DecisionContext {
  decision_level: "L3";
  departments: string[];
  category: "strategy_change" | "fund_action" | "external_distribution" | "restructuring" | "permission_change" | "other";
  description: string;
  approval_required: true;
  approval_status?: ApprovalStatus;
  evidence_refs: string[];
  rollback_plan: string;
}

/**
 * Six-Person Governing Board (GOVERNANCE_SPEC.md Section 5)
 * Responsible for: oversight, coordination, issue handling, major proposals
 */
export enum MinisterAgent {
  RESEARCH = "research_minister_agent",
  TRADING = "trading_minister_agent",
  GOVERNANCE = "governance_minister_agent",
  OPERATIONS = "operations_minister_agent",
  HR = "hr_minister_agent",
  MARKETING = "marketing_minister_agent",
}

export interface GoverningBoard {
  members: MinisterAgent[];
  meeting_notes?: string;
  last_updated: ISODateString;
}

/**
 * Approval Status (GOVERNANCE_SPEC.md Section 6)
 */
export type ApprovalStatus = "pending" | "approved" | "rejected" | "needs_more_evidence";

/**
 * Approval Ticket Minimum Fields (GOVERNANCE_SPEC.md Section 6.2)
 */
export interface ApprovalTicket {
  proposal_id: string;
  source_department: string;
  initiator_agent_id: string;
  decision_level: DecisionLevel;
  problem_summary: string;
  evidence_refs: string[];
  recommended_action: string;
  expected_impact: string;
  rollback_plan: string;
  approval_status: ApprovalStatus;
  approved_at?: ISODateString;
  rejected_reason?: string;
}

/**
 * Fail-Closed Check Result (GOVERNANCE_SPEC.md Section 8)
 * Reason codes for failed checks
 */
export type FailClosedReasonCode =
  | "missing_trace_id"
  | "missing_workflow_id"
  | "missing_policy_version"
  | "approval_required"
  | "evidence_incomplete"
  | "rollback_plan_required"
  | "distribution_scope_denied";

export interface FailClosedResult {
  passed: boolean;
  reason_codes: FailClosedReasonCode[];
  blocked_actions?: string[];
}

/**
 * Fail-Closed Check Function (GOVERNANCE_SPEC.md Section 8.3)
 * Checks critical conditions before allowing high-risk actions
 */
export function failClosedCheck(params: {
  trace_id?: string;
  workflow_id?: string;
  policy_version?: string;
  decision_level?: DecisionLevel;
  approval_status?: ApprovalStatus;
  evidence_refs?: string[];
  rollback_plan?: string;
  is_distribution?: boolean;
}): FailClosedResult {
  const reason_codes: FailClosedReasonCode[] = [];

  // Required field checks
  if (!params.trace_id) {
    reason_codes.push("missing_trace_id");
  }
  if (!params.workflow_id) {
    reason_codes.push("missing_workflow_id");
  }
  if (!params.policy_version) {
    reason_codes.push("missing_policy_version");
  }

  // L3 decision requires approval
  if (params.decision_level === "L3") {
    if (!params.approval_status || params.approval_status !== "approved") {
      reason_codes.push("approval_required");
    }
  }

  // High-risk actions require evidence
  if (reason_codes.length === 0) {
    if (!params.evidence_refs || params.evidence_refs.length === 0) {
      reason_codes.push("evidence_incomplete");
    }
  }

  // Major actions require rollback plan
  if (params.decision_level === "L3" || params.is_distribution) {
    if (!params.rollback_plan) {
      reason_codes.push("rollback_plan_required");
    }
  }

  // External distribution requires approval
  if (params.is_distribution) {
    if (params.decision_level === "L3" && params.approval_status !== "approved") {
      reason_codes.push("distribution_scope_denied");
    }
  }

  return {
    passed: reason_codes.length === 0,
    reason_codes,
    blocked_actions: reason_codes.length > 0
      ? ["Cannot proceed: fail-closed triggered"]
      : undefined,
  };
}

// ─── Phase 3 Governance Objects (OBJECT_MODEL.md §6) ───────────────────────

export type BoardProposalStatus = 'draft' | 'submitted' | 'under_review' | 'approved' | 'rejected' | 'withdrawn';

export interface BoardProposal {
  proposal_id: string;
  trace_id: string;
  department: string;
  decision_level: DecisionLevel;
  title: string;
  summary: string;
  proposer_agent: MinisterAgent;
  status: BoardProposalStatus;
  created_at: ISODateString;
  resolved_at?: ISODateString;
}

export interface ApprovalGate {
  gate_id: string;
  proposal_id: string;
  required_approvers: MinisterAgent[];
  received_approvals: MinisterAgent[];
  status: ApprovalStatus;
  decided_at?: ISODateString;
}

export interface ExecutionReview {
  review_id: string;
  trace_id: string;
  execution_id: string;
  reviewer_agent: MinisterAgent;
  verdict: 'pass' | 'pass_with_notes' | 'fail' | 'escalate';
  findings: string;
  recommendations: string;
  reviewed_at: ISODateString;
}


// =============================================================================
// Phase 6 Objects: Distribution / Performance / MarketIntel
// task-ahv2-impl-20260518-dist-obj-6a / perf-obj-6b / market-intel-6c
// =============================================================================

export type DistributionStatus = "pending" | "sent" | "failed" | "cancelled";
export type DistributionChannel = "email" | "webhook" | "push" | "internal" | "other";

export interface Distribution {
  distribution_id: string;
  trace_id: string;
  artifact_id: string;
  channel: DistributionChannel;
  recipient: string;
  status: DistributionStatus;
  policy_version: string;
  sent_at?: ISODateString;
  created_at: ISODateString;
}

export interface Performance {
  perf_id: string;
  trace_id: string;
  workflow_id: string;
  workflow_type: WorkflowType;
  department: string;
  total_trades: number;
  win_rate: number;
  pnl: number;
  latency_ms: number;
  recorded_at: ISODateString;
}

export interface MarketIntel {
  intel_id: string;
  trace_id: string;
  department: string;
  symbol: string;
  direction: "long" | "short" | "neutral";
  confidence: number;
  regime: string;
  source: string;
  summary: string;
  created_at: ISODateString;
}

// =============================================================================
// Trading Bridge: Hub ↔ 6-TRADING 双向连通
// task-connectivity-gap-trading-hub-001
// =============================================================================

export interface TradingBridgeStatus {
  online: boolean;
  latency_ms: number;
  error?: string;
}

export interface MailboxScanPayload {
  source: "mailbox_scanner";
  scanned_at: ISODateString;
  screen1: {
    direction: "LONG" | "SHORT" | "NEUTRAL";
    confidence?: number;
    inst_id?: string;
    date?: string;
  } | null;
  screen2: Record<string, unknown> | null;
  signals: Array<{
    skill: string;
    confidence?: number;
    inst_id?: string;
    date?: string;
  }>;
  execution_log: Array<{
    filename: string;
    date?: string;
    title?: string;
  }>;
}
