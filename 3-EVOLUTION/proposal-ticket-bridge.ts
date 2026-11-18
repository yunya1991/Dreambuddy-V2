/**
 * 进化提案 → Ticket 桥（W4 T4.3）。
 * 原则：提案只能生成 Ticket，由五道门与验收门决定能否进生产；禁止直改。
 * 纯函数，无 IO。
 */

import type { EvolutionProposal } from "./types";
import { isPreregIntact, type ExperimentPrereg } from "./experiment-prereg";

export type ProposalTicketBlocker =
  | "not_code_change"
  | "missing_prereg"
  | "prereg_not_locked"
  | "prereg_tampered"
  | "missing_rollback"
  | "missing_evidence"
  | "already_implemented"
  | "direct_production_forbidden"
  | "missing_acceptance_gate"
  | "missing_verdict_level";

export interface ProposalTicketDraft {
  ticket_id: string;
  trace_id: string;
  task_type: "code_change" | "architecture_change";
  source: {
    kind: "evolution_proposal";
    proposal_id: string;
    finding_id: string;
  };
  claims: string[];
  required_verdict_level: "U2";
  risk_level: "high";
  gates: string[];
  prereg_id: string;
  rollback_plan_id: string;
  evidence_refs: string[];
  direct_write: false;
  status: "live";
}

export type BuildTicketResult =
  | { ok: true; ticket: ProposalTicketDraft }
  | { ok: false; blockers: ProposalTicketBlocker[] };

const REQUIRED_GATES = ["intent", "spec", "dispatch", "acceptance", "summary"];

export function buildProposalTicket(
  proposal: EvolutionProposal,
  prereg: ExperimentPrereg | null | undefined,
  options: { trace_id?: string; claims?: string[] } = {},
): BuildTicketResult {
  const blockers: ProposalTicketBlocker[] = [];
  const p = proposal as EvolutionProposal & {
    direct_production?: boolean;
    ticket_id?: string;
  };

  if (!p.requires_code && p.change_type !== "architecture_change") {
    blockers.push("not_code_change");
  }
  if (p.status === "implemented") blockers.push("already_implemented");
  if (p.direct_production === true) blockers.push("direct_production_forbidden");
  if (!p.rollback_plan_id) blockers.push("missing_rollback");
  if (!p.evidence_refs || p.evidence_refs.length === 0) blockers.push("missing_evidence");
  if (!p.prereg_id || !prereg) blockers.push("missing_prereg");

  if (prereg) {
    if (!prereg.locked) blockers.push("prereg_not_locked");
    else if (!isPreregIntact(prereg)) blockers.push("prereg_tampered");
  }

  if (blockers.length > 0) return { ok: false, blockers };

  const taskType =
    p.change_type === "architecture_change" ? "architecture_change" : "code_change";

  const ticket: ProposalTicketDraft = {
    ticket_id: `TK-EVO-${p.id}`,
    trace_id: options.trace_id || `trace-${p.id}`,
    task_type: taskType,
    source: {
      kind: "evolution_proposal",
      proposal_id: p.id,
      finding_id: p.finding_id,
    },
    claims: options.claims?.length ? [...options.claims] : [p.title],
    required_verdict_level: "U2",
    risk_level: "high",
    gates: [...REQUIRED_GATES],
    prereg_id: String(p.prereg_id),
    rollback_plan_id: p.rollback_plan_id,
    evidence_refs: [...p.evidence_refs],
    direct_write: false,
    status: "live",
  };

  if (!ticket.gates.includes("acceptance")) blockers.push("missing_acceptance_gate");
  if (!ticket.required_verdict_level) blockers.push("missing_verdict_level");
  if (blockers.length > 0) return { ok: false, blockers };

  return { ok: true, ticket };
}

/** 任何“直接写生产”的提案都必须被拒绝。 */
export function isDirectProductionChange(proposal: EvolutionProposal): boolean {
  const p = proposal as EvolutionProposal & { direct_production?: boolean };
  return p.direct_production === true;
}
