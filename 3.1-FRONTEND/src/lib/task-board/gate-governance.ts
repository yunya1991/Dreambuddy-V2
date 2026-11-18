/**
 * Agent 治理协作（SPEC §6.9.8 / §6.9.9）。
 *
 * 核心立场：Agent 是持席位、有角色、要担责的数字员工，不是"被审批的工单"。
 * 三个不可协商的约束：
 * 1. 不得自批：Agent 不能批准自己 / 同一 run 的产出；
 * 2. 不得同源会签：同 provider + family 的 Agent 席位只计 1 票；
 * 3. 不得越权：Agent 席位只读证据，高风险验收保留至少 1 个人类责任人。
 *
 * P0 只实现最小闭环：席位解析、空审批人兜底、超时提醒/升级、退回生效；
 * GateFlow 的条件/并行/加签节点留给 P1。
 */

import type { GateKind, TaskGate } from "@/types/task-board";
import type {
  GatePolicy,
  Quorum,
} from "./gate-policy";
import { parseEmailList } from "./roles";

export type SeatKind = "human" | "agent";

export interface GateSeat {
  /** human 用 email；agent 用 `agent:<id>` */
  seat_id: string;
  kind: SeatKind;
  roles: string[];
  model_id?: string;
  model_family?: string;
  active?: boolean;
}

export interface ProducerIdentity {
  agent_id?: string;
  model_family?: string;
  /** 同一 run 的产出不可由该 run 的 Agent 批准 */
  run_id?: string;
  run_agent_ids?: string[];
}

export interface ApprovalPlan {
  seats: GateSeat[];
  human_seats: GateSeat[];
  agent_seats: GateSeat[];
  min_distinct: number;
  blocked: boolean;
  reason?: "empty_approver" | "no_eligible_seat" | "human_chair_required";
  escalated_to: string[];
}

const ALL_GATE_KINDS: GateKind[] = [
  "intent",
  "spec",
  "dispatch",
  "acceptance",
  "summary",
];

function asRoles(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function envJson<T>(raw: string | undefined, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

interface RawAgentSeat {
  id?: string;
  roles?: unknown;
  model_id?: string;
  model_family?: string;
  active?: boolean;
}

/**
 * 席位来源：
 * - 人类：GATE_TEAM_LEADS / GATE_RISK_REVIEWERS / GATE_ADMINS；
 * - Agent：GATE_AGENT_SEATS（JSON 数组），未配置时用三类模型的默认席位。
 *   `GATE_AGENT_SEATS=off` 可整体关闭 Agent 席位。
 */
export function defaultGateSeats(
  env: Record<string, string | undefined> = process.env,
): GateSeat[] {
  const seats: GateSeat[] = [];

  for (const email of parseEmailList(env.GATE_TEAM_LEADS)) {
    seats.push({ seat_id: email, kind: "human", roles: ["team_lead"] });
  }
  for (const email of parseEmailList(env.GATE_RISK_REVIEWERS)) {
    seats.push({ seat_id: email, kind: "human", roles: ["risk_reviewer"] });
  }
  for (const email of parseEmailList(env.GATE_ADMINS)) {
    seats.push({
      seat_id: email,
      kind: "human",
      roles: ["admin", "team_lead", "risk_reviewer"],
    });
  }

  if ((env.GATE_AGENT_SEATS || "").trim().toLowerCase() === "off") {
    return seats;
  }

  const raw = envJson<RawAgentSeat[]>(env.GATE_AGENT_SEATS, []);
  const configured: GateSeat[] = raw
    .filter((item) => typeof item?.id === "string" && item.id.trim())
    .map((item) => ({
      seat_id: `agent:${String(item.id).trim()}`,
      kind: "agent" as const,
      roles: asRoles(item.roles),
      model_id: item.model_id,
      model_family: item.model_family,
      active: item.active !== false,
    }));

  const defaults: GateSeat[] =
    configured.length > 0
      ? []
      : [
          {
            seat_id: "agent:judge",
            kind: "agent",
            roles: ["team_lead"],
            model_id: "deepseek-v4.1-flash",
            model_family: "deepseek",
          },
          {
            seat_id: "agent:gate-qwen",
            kind: "agent",
            roles: ["risk_reviewer"],
            model_id: "qwen4-max",
            model_family: "qwen",
          },
          {
            seat_id: "agent:gate-jev",
            kind: "agent",
            roles: ["risk_reviewer"],
            model_id: "jev-latest",
            model_family: "typesafe",
          },
        ];

  return [...seats, ...configured, ...defaults];
}

function isHighRisk(policy: GatePolicy): boolean {
  return policy.applies_to.risk_levels.some(
    (risk) => risk === "high" || risk === "critical",
  );
}

/** 席位是否有资格批准该门（角色 + SoD + 模型异构） */
export function canSeatApprove(
  seat: GateSeat,
  policy: GatePolicy,
  producer: ProducerIdentity = {},
): boolean {
  if (seat.active === false) return false;

  const roleOk =
    policy.approver.roles.length === 0 ||
    seat.roles.some((role) => policy.approver.roles.includes(role));
  if (!roleOk) return false;

  if (seat.kind === "agent") {
    const agentId = seat.seat_id.replace(/^agent:/, "");
    if (producer.agent_id && producer.agent_id === agentId) return false;
    if (producer.run_agent_ids?.includes(agentId)) return false;
    if (
      producer.model_family &&
      seat.model_family &&
      producer.model_family === seat.model_family
    ) {
      return false;
    }
    // Agent 席位不能持有写能力（只读证据），由 GatePolicy 统一约束
    if (policy.gate_model.allowed_capabilities.length > 0) return false;
  }

  return true;
}

/**
 * 解析本次门禁的有效审批席位。
 * 空审批人绝不自动通过：先升级到 escalation 角色，仍然为空则阻塞。
 */
export function resolveApprovalPlan(
  policy: GatePolicy,
  seats: GateSeat[],
  producer: ProducerIdentity = {},
): ApprovalPlan {
  const eligible = seats.filter((seat) =>
    canSeatApprove(seat, policy, producer),
  );
  const humanSeats = eligible.filter((seat) => seat.kind === "human");
  const agentSeats = eligible.filter((seat) => seat.kind === "agent");

  if (eligible.length === 0) {
    const fallback = seats.filter(
      (seat) =>
        seat.active !== false &&
        seat.roles.some((role) => policy.escalation.to_roles.includes(role)),
    );
    return {
      seats: fallback,
      human_seats: fallback.filter((seat) => seat.kind === "human"),
      agent_seats: fallback.filter((seat) => seat.kind === "agent"),
      min_distinct: policy.approver.min_distinct,
      blocked: fallback.length === 0,
      reason: fallback.length === 0 ? "empty_approver" : "no_eligible_seat",
      escalated_to: policy.escalation.to_roles,
    };
  }

  if (isHighRisk(policy) && humanSeats.length === 0) {
    return {
      seats: eligible,
      human_seats: humanSeats,
      agent_seats: agentSeats,
      min_distinct: policy.approver.min_distinct,
      blocked: true,
      reason: "human_chair_required",
      escalated_to: policy.escalation.to_roles,
    };
  }

  return {
    seats: eligible,
    human_seats: humanSeats,
    agent_seats: agentSeats,
    min_distinct: policy.approver.min_distinct,
    blocked: false,
    escalated_to: [],
  };
}

export interface SeatVote {
  seat_id: string;
  verdict: "approved" | "rejected";
  model_family?: string;
}

export interface SeatTally {
  approved: boolean;
  approved_seats: number;
  distinct_families: number;
  reason?: string;
}

/**
 * 混合计票：一人一票；Agent 按席位计票，但同 family 只计 1 票。
 * 空审批人或缺少人类责任人时，永远不返回 approved。
 */
export function tallySeatVotes(
  votes: SeatVote[],
  plan: ApprovalPlan,
  quorum: Quorum,
): SeatTally {
  if (plan.blocked) {
    return {
      approved: false,
      approved_seats: 0,
      distinct_families: 0,
      reason: plan.reason,
    };
  }

  const allowed = new Map(plan.seats.map((seat) => [seat.seat_id, seat]));
  const approvals = new Set<string>();
  const families = new Set<string>();
  let rejected = false;

  for (const vote of votes) {
    const seat = allowed.get(vote.seat_id);
    if (!seat) continue;
    if (vote.verdict === "rejected") {
      rejected = true;
      continue;
    }
    if (seat.kind === "agent") {
      const family = vote.model_family || seat.model_family || seat.seat_id;
      if (families.has(family)) continue;
      families.add(family);
    }
    approvals.add(vote.seat_id);
  }

  const distinct = approvals.size;
  const familyCount = families.size + plan.human_seats.length;
  const required = Math.max(plan.min_distinct, 1);

  let approved = false;
  if (quorum === "all") {
    approved = !rejected && distinct >= Math.max(required, plan.seats.length);
  } else {
    approved = !rejected && distinct >= required;
  }

  return {
    approved,
    approved_seats: distinct,
    distinct_families: familyCount,
    reason: approved ? undefined : rejected ? "seat_rejected" : "quorum_not_met",
  };
}

/** 门禁顺序；用于退回时计算失效范围 */
export const GATE_ORDER = ALL_GATE_KINDS;

/**
 * 退回生效：目标门到链尾全部失效（下游不得带着旧批准继续跑）。
 * 返回需要重置为 waiting 的门；被驳回的门本身保持 rejected。
 */
export function computeRewind(
  rejected: GateKind,
  rewindTo: GateKind | "none" | undefined,
  defaultTarget: GateKind | "none",
): GateKind[] {
  const target = rewindTo ?? defaultTarget;
  if (target === "none") return [];
  const from = GATE_ORDER.indexOf(target);
  const to = GATE_ORDER.indexOf(rejected);
  if (from < 0 || to < 0 || from > to) return [];

  const scope = GATE_ORDER.slice(from, to + 1).filter(
    (kind) => kind !== rejected,
  );
  // 下游（rejected 之后）已批准的门也必须失效
  const downstream = GATE_ORDER.slice(to + 1);
  return [...scope, ...downstream];
}

export interface GateSlaAction {
  type: "gate.reminded" | "gate.escalated";
  gate_id: string;
  kind: GateKind;
  at: number;
  to_roles: string[];
}

/**
 * 超时评估：只提醒 / 升级，永不自动通过。
 * 每道门最多提醒 remind_max_times 次，升级只发生一次。
 */
export function evaluateGateSla(
  gates: TaskGate[],
  resolvePolicy: (kind: GateKind) => GatePolicy,
  now: number,
): GateSlaAction[] {
  const actions: GateSlaAction[] = [];

  for (const gate of gates) {
    if (!gate.required || gate.status !== "waiting") continue;
    if (!gate.requested_at) continue;

    const policy = resolvePolicy(gate.kind);
    const remindCount = gate.remind_count ?? 0;
    const remindDue = gate.requested_at + policy.sla.minutes * 60_000;
    const escalateDue =
      gate.requested_at + policy.escalation.after_minutes * 60_000;

    if (
      now >= remindDue &&
      remindCount < policy.sla.remind_max_times &&
      !gate.reminded_at
    ) {
      actions.push({
        type: "gate.reminded",
        gate_id: gate.gate_id,
        kind: gate.kind,
        at: now,
        to_roles: policy.notify.on_request,
      });
    }

    if (now >= escalateDue && !gate.escalated_at) {
      actions.push({
        type: "gate.escalated",
        gate_id: gate.gate_id,
        kind: gate.kind,
        at: now,
        to_roles: policy.escalation.to_roles,
      });
    }
  }

  return actions;
}
