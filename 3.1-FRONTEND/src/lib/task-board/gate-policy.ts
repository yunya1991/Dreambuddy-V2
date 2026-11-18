/**
 * 工作门禁策略（DESIGN §11.8 / §十二）。
 *
 * 制度内核：不相容职务分离、分级授权、双人复核、阶段门、变更分级、例外管理、审计。
 * 策略可配，但下面这些不留给配置口子：
 * - Agent / 子代理永不进入审批池；
 * - 超时不允许自动通过；
 * - gate 模型只读、temperature=0；
 * - 高风险门必须至少两人、至少两个异构模型。
 */

import { GATE_TITLE, type GateKind } from "@/types/task-board";
import {
  getModelRegistry,
  isStrictEnvironment,
  validateModelRegistry,
  type ModelRegistry,
  type ModelSpec,
} from "@/lib/model/model-registry";
import {
  GATE_RISK,
  GATE_SLA_MINUTES,
  type GateRiskLevel,
} from "./gate-priority";

export type RiskLevel = GateRiskLevel;
export { GATE_RISK, GATE_SLA_MINUTES };
export type ChangeClass = "standard" | "normal" | "emergency";
export type Quorum = "any" | "all" | "sequential";
export type ModelVoteWeight = "binding" | "advisory";
/** 全权：低/中风险机器自动确认；人工干预：全部人工确认 */
export type GateMode = "autonomy" | "human";

export const GATE_KINDS: GateKind[] = [
  "intent",
  "spec",
  "dispatch",
  "acceptance",
  "summary",
];

export const RISK_LEVELS: RiskLevel[] = ["low", "medium", "high", "critical"];

export function getGateMode(
  env: Record<string, string | undefined> = process.env,
): GateMode {
  const raw = (env.GATE_MODE || "").trim().toLowerCase();
  return raw === "autonomy" || raw === "auto" || raw === "全权"
    ? "autonomy"
    : "human";
}

/** 这些角色永远不能出现在审批池里（权限来自代码，不来自配置） */
export const AGENT_FORBIDDEN_ROLES = [
  "agent",
  "worker",
  "subagent",
  "c_drive",
  "dsh",
  "system",
];

export interface GatePolicy {
  gate_id: string;
  kind: GateKind;
  title: string;
  /** 当前运行模式 */
  mode: GateMode;
  /** 全权模式下低/中风险门可机器自动确认 */
  auto_approve: boolean;
  /** 必须人工确认（人工干预模式，或 high/critical 门） */
  human_required: boolean;
  applies_to: {
    task_types: string[];
    risk_levels: RiskLevel[];
    change_classes: ChangeClass[];
  };
  approver: {
    roles: string[];
    quorum: Quorum;
    min_distinct: number;
    allow_self_approve: boolean;
    allow_delegate: boolean;
    allow_add_signer: boolean;
  };
  gate_model: {
    class: "gate";
    model_ids: string[];
    quorum: Quorum;
    min_distinct_models: number;
    deny_same_provider: boolean;
    deny_same_family: boolean;
    allowed_capabilities: string[];
    temperature: number;
    on_invalid_output: "needs_human";
  };
  model_tickets: {
    model_vote_weight: ModelVoteWeight;
    human_ticket_required_above: RiskLevel;
  };
  sod: {
    deny_same_actor: boolean;
    deny_same_org: boolean;
    forbidden_roles: string[];
  };
  evidence: {
    required: string[];
    min_evidence_count: number;
    must_show_diff: boolean;
  };
  sla: {
    minutes: number;
    on_timeout: "remind" | "escalate";
    remind_max_times: number;
  };
  escalation: {
    after_minutes: number;
    to_roles: string[];
    on_exhausted: "block";
  };
  rejection: {
    require_comment: true;
    rewind_to: GateKind | "none";
  };
  bypass: {
    allowed: boolean;
    roles?: string[];
    max_uses?: number;
    requires_reason: true;
  };
  preauthorized: {
    enabled: boolean;
    ttl_hours?: number;
    max_uses?: number;
    require_regression_evidence: boolean;
  };
  audit: {
    immutable: boolean;
    retention_days: number;
    include_prompt_version: boolean;
  };
  notify: {
    on_request: string[];
    on_approve: string[];
    on_reject: string[];
    on_escalate: string[];
  };
}

interface KindBase {
  roles: string[];
  evidence: string[];
  rewind_to: GateKind | "none";
  sla_minutes: number;
}

const KIND_BASE: Record<GateKind, KindBase> = {
  intent: {
    roles: ["owner"],
    evidence: ["intent:decision"],
    rewind_to: "none",
    sla_minutes: GATE_SLA_MINUTES.intent,
  },
  spec: {
    roles: ["owner"],
    evidence: ["spec:fields"],
    rewind_to: "intent",
    sla_minutes: GATE_SLA_MINUTES.spec,
  },
  dispatch: {
    roles: ["team_lead"],
    evidence: ["okr:krs"],
    rewind_to: "spec",
    sla_minutes: GATE_SLA_MINUTES.dispatch,
  },
  acceptance: {
    roles: ["risk_reviewer", "team_lead"],
    evidence: ["acceptance:records", "data_quality:declared"],
    rewind_to: "dispatch",
    sla_minutes: GATE_SLA_MINUTES.acceptance,
  },
  summary: {
    roles: ["team_lead"],
    evidence: ["summary:conclusion"],
    rewind_to: "acceptance",
    sla_minutes: GATE_SLA_MINUTES.summary,
  },
};

const RISK_RULES: Record<
  RiskLevel,
  {
    quorum: Quorum;
    min_distinct: number;
    min_models: number;
    model_vote: ModelVoteWeight;
    human_required_above: RiskLevel;
  }
> = {
  low: {
    quorum: "any",
    min_distinct: 1,
    min_models: 1,
    model_vote: "binding",
    human_required_above: "medium",
  },
  medium: {
    quorum: "any",
    min_distinct: 1,
    min_models: 1,
    model_vote: "advisory",
    human_required_above: "medium",
  },
  high: {
    quorum: "all",
    min_distinct: 2,
    min_models: 2,
    model_vote: "advisory",
    human_required_above: "medium",
  },
  critical: {
    quorum: "all",
    min_distinct: 2,
    min_models: 2,
    model_vote: "advisory",
    human_required_above: "medium",
  },
};

export function buildGatePolicy(
  kind: GateKind,
  risk: RiskLevel = "medium",
  changeClass: ChangeClass = "normal",
  mode: GateMode = "human",
): GatePolicy {
  const base = KIND_BASE[kind];
  const rule = RISK_RULES[risk];
  const preauthorized = risk === "low" && changeClass === "standard";
  const autoApprove =
    mode === "autonomy" && (risk === "low" || risk === "medium");
  const humanRequired = !autoApprove;

  return {
    gate_id: kind,
    kind,
    title: GATE_TITLE[kind],
    mode,
    auto_approve: autoApprove,
    human_required: humanRequired,
    applies_to: {
      task_types: ["*"],
      risk_levels: [risk],
      change_classes: [changeClass],
    },
    approver: {
      roles: base.roles,
      quorum: rule.quorum,
      min_distinct: rule.min_distinct,
      allow_self_approve: false,
      allow_delegate: false,
      allow_add_signer: false,
    },
    gate_model: {
      class: "gate",
      model_ids: [],
      quorum: rule.quorum,
      min_distinct_models: rule.min_models,
      deny_same_provider: true,
      deny_same_family: true,
      allowed_capabilities: [],
      temperature: 0,
      on_invalid_output: "needs_human",
    },
    model_tickets: {
      model_vote_weight: rule.model_vote,
      human_ticket_required_above: rule.human_required_above,
    },
    sod: {
      deny_same_actor: true,
      deny_same_org: false,
      forbidden_roles: [...AGENT_FORBIDDEN_ROLES],
    },
    evidence: {
      required: base.evidence,
      min_evidence_count: 1,
      must_show_diff: kind === "spec",
    },
    sla: {
      minutes: base.sla_minutes,
      on_timeout: "escalate",
      remind_max_times: 1,
    },
    escalation: {
      after_minutes: base.sla_minutes * 2,
      to_roles: ["team_lead"],
      on_exhausted: "block",
    },
    rejection: {
      require_comment: true,
      rewind_to: base.rewind_to,
    },
    bypass: {
      allowed: false,
      requires_reason: true,
    },
    preauthorized: {
      enabled: preauthorized,
      ttl_hours: preauthorized ? 24 : undefined,
      max_uses: preauthorized ? 1 : undefined,
      require_regression_evidence: true,
    },
    audit: {
      immutable: true,
      retention_days: 730,
      include_prompt_version: true,
    },
    notify: {
      on_request: base.roles,
      on_approve: [],
      on_reject: ["owner"],
      on_escalate: ["team_lead"],
    },
  };
}

/** 全量默认策略：五道门 × 四种风险（常规变更） */
export const DEFAULT_GATE_POLICIES: GatePolicy[] = GATE_KINDS.flatMap((kind) =>
  RISK_LEVELS.map((risk) => buildGatePolicy(kind, risk, "normal")),
);

export function resolveGatePolicy(
  kind: GateKind,
  risk: RiskLevel = "medium",
  changeClass: ChangeClass = "normal",
  mode: GateMode = "human",
): GatePolicy {
  return buildGatePolicy(kind, risk, changeClass, mode);
}

export interface PolicyIssue {
  level: "error" | "warning";
  code: string;
  message: string;
}

/** 纯策略校验：不依赖环境，便于单测与配置审查 */
export function validateGatePolicies(policies: GatePolicy[]): PolicyIssue[] {
  const issues: PolicyIssue[] = [];
  const seen = new Set<GateKind>();
  const seenCombos = new Set<string>();
  const forbidden = new Set(
    AGENT_FORBIDDEN_ROLES.map((role) => role.toLowerCase()),
  );

  for (const policy of policies) {
    const combo = `${policy.kind}:${[...policy.applies_to.risk_levels]
      .sort()
      .join("|")}:${[...policy.applies_to.change_classes].sort().join("|")}`;
    if (seenCombos.has(combo)) {
      issues.push({
        level: "error",
        code: "duplicate_gate_policy",
        message: `门禁 ${policy.kind} 在相同风险/变更分级下存在多条策略`,
      });
    }
    seenCombos.add(combo);
    seen.add(policy.kind);

    if (policy.approver.roles.length === 0) {
      issues.push({
        level: "error",
        code: "approver_empty",
        message: `${policy.kind} 没有配置任何审批角色`,
      });
    }

    for (const role of policy.approver.roles) {
      if (forbidden.has(role.toLowerCase())) {
        issues.push({
          level: "error",
          code: "agent_in_approver",
          message: `${policy.kind} 的审批池出现 Agent 角色「${role}」`,
        });
      }
    }

    if (
      policy.approver.roles.some((role) => forbidden.has(role.toLowerCase()))
    ) {
      // 已在上面报错，继续检查其余规则
    }

    const onTimeout = policy.sla.on_timeout as string;
    if (onTimeout !== "remind" && onTimeout !== "escalate") {
      issues.push({
        level: "error",
        code: "timeout_auto_approve",
        message: `${policy.kind} 的超时策略只能提醒或升级，不允许自动放行`,
      });
    }

    if (policy.gate_model.allowed_capabilities.length > 0) {
      issues.push({
        level: "error",
        code: "gate_has_capabilities",
        message: `${policy.kind} 的 gate 模型不允许拥有能力授权`,
      });
    }
    if (policy.gate_model.temperature !== 0) {
      issues.push({
        level: "error",
        code: "gate_temperature_nonzero",
        message: `${policy.kind} 的 gate 模型 temperature 必须为 0`,
      });
    }
    if (policy.gate_model.on_invalid_output !== "needs_human") {
      issues.push({
        level: "error",
        code: "gate_invalid_output_not_blocking",
        message: `${policy.kind} 的 gate 输出不合规时必须降级为 needs_human`,
      });
    }

    const high = policy.applies_to.risk_levels.some(
      (risk) => risk === "high" || risk === "critical",
    );
    if (high && policy.approver.min_distinct < 2) {
      issues.push({
        level: "error",
        code: "high_risk_single_approver",
        message: `${policy.kind} 的高风险门至少需要 2 个不同审批人`,
      });
    }
    if (high && policy.gate_model.min_distinct_models < 2) {
      issues.push({
        level: "error",
        code: "high_risk_single_gate_model",
        message: `${policy.kind} 的高风险门至少需要 2 个异构 gate 模型会签`,
      });
    }

    if (policy.auto_approve && policy.human_required) {
      issues.push({
        level: "error",
        code: "mode_conflict",
        message: `${policy.kind} 不能同时要求自动确认与人工确认`,
      });
    }
    if (high && policy.auto_approve) {
      issues.push({
        level: "error",
        code: "high_risk_auto_approve",
        message: `${policy.kind} 的 high/critical 门禁止自动确认`,
      });
    }
    if (high && !policy.human_required) {
      issues.push({
        level: "error",
        code: "high_risk_without_human",
        message: `${policy.kind} 的 high/critical 门必须保留人工确认`,
      });
    }
    if (policy.mode === "human" && policy.auto_approve) {
      issues.push({
        level: "error",
        code: "human_mode_auto_approve",
        message: `${policy.kind} 在人工干预模式下不能自动确认`,
      });
    }

    if (policy.model_tickets.model_vote_weight === "binding") {
      const onlyLow = policy.applies_to.risk_levels.every(
        (risk) => risk === "low",
      );
      if (!onlyLow) {
        issues.push({
          level: "error",
          code: "model_vote_binding_above_low",
          message: `${policy.kind} 只有低风险门允许模型票绑定结论`,
        });
      }
    }

    if (policy.bypass.allowed && !policy.bypass.requires_reason) {
      issues.push({
        level: "error",
        code: "bypass_without_reason",
        message: `${policy.kind} 的旁路必须填写理由`,
      });
    }

    if (
      policy.preauthorized.enabled &&
      !policy.applies_to.change_classes.every((cls) => cls === "standard")
    ) {
      issues.push({
        level: "error",
        code: "preauthorized_non_standard",
        message: `${policy.kind} 的预授权只能用于标准变更`,
      });
    }

    if (
      !Number.isFinite(policy.sla.minutes) ||
      policy.sla.minutes <= 0 ||
      policy.sla.minutes > 31 * 24 * 60
    ) {
      issues.push({
        level: "error",
        code: "sla_out_of_range",
        message: `${policy.kind} 的 SLA 必须在 1 分钟到 31 天之间`,
      });
    }
  }

  for (const kind of GATE_KINDS) {
    if (!seen.has(kind)) {
      issues.push({
        level: "error",
        code: "missing_gate_policy",
        message: `缺少门禁策略：${kind}`,
      });
    }
  }

  return issues;
}

/**
 * 启动期联合校验：策略 + 模型注册表。
 * 生产环境存在 error 即拒绝启动；开发环境只告警（门禁退化为纯人工）。
 */
export function assertGatePolicySet(
  policies: GatePolicy[] = DEFAULT_GATE_POLICIES,
  registry: ModelRegistry = getModelRegistry(),
  opts: { strict?: boolean } = {},
): PolicyIssue[] {
  const strict = opts.strict ?? isStrictEnvironment();
  const issues: PolicyIssue[] = [
    ...validateGatePolicies(policies),
    ...validateModelRegistry(registry, { strict }),
  ];

  // 主副门禁都参与会签；同源/同 ID 的情况由 validateModelRegistry 单独报错
  const gateModels = [registry.gate, registry.gate_secondary].filter(
    (spec): spec is ModelSpec => Boolean(spec),
  );
  for (const policy of policies) {
    const high = policy.applies_to.risk_levels.some(
      (risk) => risk === "high" || risk === "critical",
    );
    if (high && gateModels.length < 2) {
      issues.push({
        level: "warning",
        code: "gate_models_insufficient_for_quorum",
        message: `${policy.kind} 的高风险门需要 2 个异构 gate 模型，当前只有 ${gateModels.length} 个，将退化为「单模型预审 + 人工确认」`,
      });
    }
  }

  const errors = issues.filter((issue) => issue.level === "error");
  if (strict && errors.length > 0) {
    throw new Error(
      `工作门禁启动校验失败：\n${errors
        .map((issue) => `- [${issue.code}] ${issue.message}`)
        .join("\n")}`,
    );
  }

  if (!strict) {
    for (const issue of issues) {
      // 开发环境显式暴露问题，不静默
      // eslint-disable-next-line no-console
      console.warn(`[gate-policy] ${issue.level} ${issue.code}: ${issue.message}`);
    }
  }

  return issues;
}
