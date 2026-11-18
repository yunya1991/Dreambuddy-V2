/**
 * A 层 OKR 校验与 dispatch 门（T5）。
 *
 * 制度内核：**OKR 不清 = 不开工**。
 * - 完整性校验不过 / 能力域匹配不到 → 硬阻断（fail-closed）；
 * - standard 默认自动过门；命中高不确定性才转人工；
 * - 门决策只依赖事实字段（评分、能力匹配、证据锚点、预检、Debate 结论），
 *   不接受自由文本或 LLM 直接判定。
 */

import type { ComplexityLevel } from "@/lib/planner/planner-types";
import type {
  OkrNode,
  TaskGate,
  TaskObjective,
} from "@/types/task-board";
import { GATE_TITLE } from "@/types/task-board";
import { DOMAINS, type CapabilityDomain } from "./capability-domain";
import { readVerifyThreshold } from "./decompose";

export type OkrIssueCode =
  | "objective_missing"
  | "krs_empty"
  | "kr_criteria_missing"
  | "kr_verify_invalid"
  | "kr_owner_domain_missing"
  | "kr_owner_domain_unknown"
  | "kr_capability_missing"
  | "kr_capability_unmatched";

export interface OkrIssue {
  node_id?: string;
  code: OkrIssueCode;
  message: string;
}

export interface OkrValidationResult {
  ok: boolean;
  /** 失败时统一对外错误码 */
  code?: "OKR_INCOMPLETE";
  issues: OkrIssue[];
}

export type UncertaintyReason =
  | "okr_incomplete"
  | "complexity_boundary"
  | "capability_gap"
  | "missing_evidence_anchor"
  | "acceptance_precheck_pending"
  | "debate_inconclusive"
  | "debate_degraded";

export interface AcceptancePrecheck {
  verdict: "pass" | "pending" | "fail";
  /** 验收模型自评置信度（0-1） */
  confidence?: number;
}

export interface DispatchGateInput {
  objective?: TaskObjective;
  krs: OkrNode[];
  level: ComplexityLevel;
  /** 复杂度评分：deep 阈值 4，score=3 视为边界 */
  score?: number;
  /** 验收模型对 criteria 的预检结果（可选） */
  precheck?: AcceptancePrecheck;
  debateVerdict?: "WIN" | "LOSE" | "INCONCLUSIVE";
  debateDegraded?: boolean;
  /** 能力域注册表（默认使用 capability-domain 的 DOMAINS） */
  domains?: Record<string, CapabilityDomain>;
}

export interface DispatchGateDecision {
  status: "approved" | "waiting";
  /** waiting 即代表需要人工确认 */
  required: boolean;
  reasons: UncertaintyReason[];
  /** 人类可读说明，写入 gate.comment */
  detail: string[];
  validation: OkrValidationResult;
}

const VERIFY_KINDS = new Set(["evidence_backed", "gap_closed", "c_action"]);

/** 校验 OKR 是否明确到可以派发；任何硬缺口都会返回 ok=false */
export function validateOkr(
  objective: TaskObjective | undefined,
  krs: OkrNode[],
  domains: Record<string, CapabilityDomain> = defaultDomains(),
): OkrValidationResult {
  const issues: OkrIssue[] = [];

  if (!objective || !objective.title?.trim() || !objective.owner?.trim()) {
    issues.push({
      code: "objective_missing",
      message: "缺少任务目标（objective.title / owner）",
    });
  }
  if (!Array.isArray(krs) || krs.length === 0) {
    issues.push({ code: "krs_empty", message: "至少需要 1 个可验收的 KR" });
    return { ok: false, code: "OKR_INCOMPLETE", issues };
  }

  for (const kr of krs) {
    if (!kr.criteria?.trim()) {
      issues.push({
        node_id: kr.node_id,
        code: "kr_criteria_missing",
        message: `${kr.node_id} 缺少验收判据 criteria`,
      });
    }
    if (!VERIFY_KINDS.has(kr.verify)) {
      issues.push({
        node_id: kr.node_id,
        code: "kr_verify_invalid",
        message: `${kr.node_id} 的 verify 非法：${String(kr.verify)}`,
      });
    }
    const domainId = kr.owner_domain?.trim();
    if (!domainId) {
      issues.push({
        node_id: kr.node_id,
        code: "kr_owner_domain_missing",
        message: `${kr.node_id} 未归属能力域 owner_domain`,
      });
      continue;
    }
    const domain = domains[domainId];
    if (!domain) {
      issues.push({
        node_id: kr.node_id,
        code: "kr_owner_domain_unknown",
        message: `${kr.node_id} 的能力域未注册：${domainId}`,
      });
      continue;
    }
    const capabilities = kr.capability_ids ?? [];
    if (capabilities.length === 0) {
      issues.push({
        node_id: kr.node_id,
        code: "kr_capability_missing",
        message: `${kr.node_id} 未声明可调用能力 capability_ids`,
      });
      continue;
    }
    const unmatched = capabilities.filter(
      (capability) => !domain.capabilities.includes(capability),
    );
    if (unmatched.length > 0) {
      issues.push({
        node_id: kr.node_id,
        code: "kr_capability_unmatched",
        message: `${kr.node_id} 存在能力缺口：${unmatched.join(", ")}`,
      });
    }
  }

  return issues.length === 0
    ? { ok: true, issues }
    : { ok: false, code: "OKR_INCOMPLETE", issues };
}

function defaultDomains(): Record<string, CapabilityDomain> {
  return DOMAINS;
}

const CAPABILITY_GAP_CODES = new Set<OkrIssueCode>([
  "kr_owner_domain_missing",
  "kr_owner_domain_unknown",
  "kr_capability_missing",
  "kr_capability_unmatched",
]);

const REASON_DETAIL: Record<UncertaintyReason, string> = {
  okr_incomplete: "OKR 不完整：存在缺失判据或能力缺口",
  complexity_boundary: "复杂度评分处于边界（score=3，deep 阈值 4）",
  capability_gap: "KR 能力域匹配存在缺口",
  missing_evidence_anchor: "evidence_backed 的 KR 未声明证据锚点",
  acceptance_precheck_pending: "验收预检未通过或置信度低于阈值",
  debate_inconclusive: "Debate 裁决 INCONCLUSIVE",
  debate_degraded: "Debate 超时或降级",
};

/** 计算 dispatch 门：无不确定性 → system:auto 通过；否则 waiting 等人工 */
export function resolveDispatchGate(
  input: DispatchGateInput,
): DispatchGateDecision {
  const domains = input.domains ?? defaultDomains();
  const validation = validateOkr(input.objective, input.krs, domains);
  const reasons = new Set<UncertaintyReason>();

  if (!validation.ok) reasons.add("okr_incomplete");

  // 1) 复杂度评分边界（deep 阈值 4，score=3）
  if (input.score === 3) reasons.add("complexity_boundary");

  // 2) 能力缺口（fail-closed）
  if (validation.issues.some((issue) => CAPABILITY_GAP_CODES.has(issue.code))) {
    reasons.add("capability_gap");
  }

  // 3) evidence_backed 必须有证据锚点
  if (
    input.krs.some(
      (kr) => kr.verify === "evidence_backed" && !kr.evidence_id?.trim(),
    )
  ) {
    reasons.add("missing_evidence_anchor");
  }

  // 4) 验收预检 pending 或置信度低于阈值
  const threshold =
    input.objective?.confidence_threshold ?? readVerifyThreshold();
  const precheck = input.precheck;
  if (
    precheck &&
    (precheck.verdict === "pending" ||
      (typeof precheck.confidence === "number" && precheck.confidence < threshold))
  ) {
    reasons.add("acceptance_precheck_pending");
  }

  // 5) Debate 结论未定 / 降级
  if (input.debateVerdict === "INCONCLUSIVE") reasons.add("debate_inconclusive");
  if (input.debateDegraded) reasons.add("debate_degraded");

  const list = [...reasons];
  return {
    status: list.length === 0 ? "approved" : "waiting",
    required: list.length > 0,
    reasons: list,
    detail: list.map((reason) => REASON_DETAIL[reason]),
    validation,
  };
}

/** 与看板证据重算规则一致：dispatch 门绑定当前 okr.updated 的 seq */
export function dispatchGateEvidenceRef(okrSeq: number): string {
  return `okr:${okrSeq}`;
}

/**
 * 构造 gate.updated 的 dispatch 门。
 * evidence_ref 必须与 buildTaskBoard 的重算规则一致，否则自动通过会被重置为 waiting。
 */
export function buildDispatchGate(
  decision: DispatchGateDecision,
  evidenceRef: string,
  now: number = Date.now(),
): TaskGate {
  const approved = decision.status === "approved";
  return {
    gate_id: "dispatch",
    kind: "dispatch",
    title: GATE_TITLE.dispatch,
    status: decision.status,
    required: true,
    evidence_ref: evidenceRef,
    decided_by: approved ? "system:auto" : undefined,
    decided_at: approved ? now : undefined,
    comment: approved
      ? "OKR 明确且无高不确定性，自动通过"
      : decision.detail.join("；"),
    requested_at: now,
    remind_count: 0,
  };
}
