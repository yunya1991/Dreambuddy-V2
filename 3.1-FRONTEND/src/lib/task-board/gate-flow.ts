/**
 * GateFlow（SPEC §6.9）：把飞书的「流程定义 + 运行状态机」内化为可校验、可回放的门禁流程。
 *
 * 三层内化：
 * - 制度层：Policy Template（本文件不负责，由 GatePolicy / 版本评审承载）；
 * - 流程层：GateFlow（节点、条件、会签、时限）+ 12 条编译期校验；
 * - 运行层：GateRun（append-only 事件 + 当前节点），只记录实际发生。
 *
 * 红线：流程不得绕过验收；超时/空审批人不得自动通过；退回必须使下游失效。
 */

import type { GateKind } from "@/types/task-board";
import type { GatePolicy, Quorum } from "./gate-policy";
import {
  resolveApprovalPlan,
  tallySeatVotes,
  type GateSeat,
  type ProducerIdentity,
  type SeatVote,
} from "./gate-governance";

export type GateNodeType =
  | "gate"
  | "condition"
  | "parallel"
  | "cc"
  | "timer"
  | "terminate";

export type FactField =
  | "risk_level"
  | "task_type"
  | "change_class"
  | "evidence_count"
  | "kr_verdict";

export interface ConditionExpr {
  /** 只允许事实字段，禁止自由文本或 LLM 判定 */
  field: FactField;
  op: "eq" | "neq" | "gt" | "lt" | "in";
  value: string | number | string[];
}

export type GateFlowNode =
  | { id: string; type: "gate"; gate: GatePolicy; next: string | null }
  | {
      id: string;
      type: "condition";
      when: ConditionExpr;
      then: string;
      else: string;
    }
  | {
      id: string;
      type: "parallel";
      branches: string[];
      join: "all" | "any";
      next: string;
    }
  | { id: string; type: "cc"; to: string[]; next: string }
  | {
      id: string;
      type: "timer";
      hours: number;
      on_timeout: "remind" | "escalate" | "block";
      next: string;
    }
  | { id: string; type: "terminate"; reason: string; admin_only: true };

export interface GateFlow {
  flow_id: string;
  version: number;
  status: "draft" | "active" | "archived";
  applies_to: {
    task_types: string[];
    risk_levels: ("low" | "medium" | "high" | "critical")[];
  };
  entry: string;
  nodes: GateFlowNode[];
  guardrails: {
    must_end_with: "acceptance";
    forbid_skip_high_risk: true;
    max_nodes: number;
    max_gates: number;
  };
}

export interface GateFacts {
  risk_level: "low" | "medium" | "high" | "critical";
  task_type: string;
  change_class: "standard" | "normal" | "emergency";
  evidence_count: number;
  kr_verdict?: string;
}

export interface FlowIssue {
  level: "error" | "warning";
  code: string;
  message: string;
  node_id?: string;
}

const FACT_FIELDS: FactField[] = [
  "risk_level",
  "task_type",
  "change_class",
  "evidence_count",
  "kr_verdict",
];

function targets(node: GateFlowNode): string[] {
  switch (node.type) {
    case "gate":
      return node.next ? [node.next] : [];
    case "cc":
    case "timer":
      return [node.next];
    case "condition":
      return [node.then, node.else];
    case "parallel":
      return [...node.branches, node.next];
    case "terminate":
      return [];
  }
}

function gateNodes(flow: GateFlow): Extract<GateFlowNode, { type: "gate" }>[] {
  return flow.nodes.filter(
    (node): node is Extract<GateFlowNode, { type: "gate" }> =>
      node.type === "gate",
  );
}

function isHighRiskFlow(flow: GateFlow): boolean {
  return flow.applies_to.risk_levels.some(
    (risk) => risk === "high" || risk === "critical",
  );
}

/** 某节点的祖先门（含间接），用于退回校验 */
function ancestorGates(
  flow: GateFlow,
  nodeId: string,
): Extract<GateFlowNode, { type: "gate" }>[] {
  const parents = new Map<string, string[]>();
  for (const node of flow.nodes) {
    for (const target of targets(node)) {
      const list = parents.get(target) ?? [];
      list.push(node.id);
      parents.set(target, list);
    }
  }

  const seen = new Set<string>();
  const stack = [...(parents.get(nodeId) ?? [])];
  const result: Extract<GateFlowNode, { type: "gate" }>[] = [];
  while (stack.length > 0) {
    const current = stack.pop()!;
    if (seen.has(current)) continue;
    seen.add(current);
    const node = flow.nodes.find((item) => item.id === current);
    if (node?.type === "gate") result.push(node);
    stack.push(...(parents.get(current) ?? []));
  }
  return result;
}

/** 12 条编译期校验；有 error 不得 active */
export function validateGateFlow(flow: GateFlow): FlowIssue[] {
  const issues: FlowIssue[] = [];
  const nodeById = new Map<string, GateFlowNode>();
  const duplicate = new Set<string>();

  for (const node of flow.nodes) {
    if (nodeById.has(node.id)) duplicate.add(node.id);
    nodeById.set(node.id, node);
  }

  // 12：审批席位不得重复
  for (const node of gateNodes(flow)) {
    const roles = node.gate.approver.roles;
    if (new Set(roles).size !== roles.length) {
      issues.push({
        level: "error",
        code: "duplicate_approver_seat",
        message: `${node.id} 的审批席位重复`,
        node_id: node.id,
      });
    }
  }

  if (duplicate.size > 0) {
    issues.push({
      level: "error",
      code: "duplicate_node_id",
      message: `节点 id 重复：${[...duplicate].join(", ")}`,
    });
  }
  if (!nodeById.has(flow.entry)) {
    issues.push({
      level: "error",
      code: "entry_missing",
      message: `入口节点不存在：${flow.entry}`,
    });
  }

  // 3：节点/门数上限 + 悬空引用
  const gates = gateNodes(flow);
  if (flow.nodes.length > flow.guardrails.max_nodes) {
    issues.push({
      level: "error",
      code: "too_many_nodes",
      message: `节点数 ${flow.nodes.length} 超过上限 ${flow.guardrails.max_nodes}`,
    });
  }
  if (gates.length > flow.guardrails.max_gates) {
    issues.push({
      level: "error",
      code: "too_many_gates",
      message: `门数 ${gates.length} 超过上限 ${flow.guardrails.max_gates}`,
    });
  }
  for (const node of flow.nodes) {
    for (const target of targets(node)) {
      if (!nodeById.has(target)) {
        issues.push({
          level: "error",
          code: "dangling_edge",
          message: `${node.id} 指向不存在的节点 ${target}`,
          node_id: node.id,
        });
      }
    }
  }

  // 3：无环
  const colors = new Map<string, 1 | 2>();
  const visit = (id: string): boolean => {
    if (colors.get(id) === 1) return true;
    if (colors.get(id) === 2) return false;
    colors.set(id, 1);
    const node = nodeById.get(id);
    for (const target of node ? targets(node) : []) {
      if (visit(target)) return true;
    }
    colors.set(id, 2);
    return false;
  };
  if (visit(flow.entry)) {
    issues.push({
      level: "error",
      code: "cycle_detected",
      message: "GateFlow 存在环，审批可能永不收敛",
    });
  }

  // 1：所有非终止路径必须终于验收门
  const reachable = new Set<string>();
  const walk = (id: string) => {
    if (reachable.has(id)) return;
    reachable.add(id);
    const node = nodeById.get(id);
    for (const target of node ? targets(node) : []) walk(target);
  };
  walk(flow.entry);

  for (const node of flow.nodes) {
    if (!reachable.has(node.id)) continue;
    const outs = targets(node);
    if (outs.length > 0 || node.type === "terminate") continue;
    if (node.type !== "gate" || node.gate.kind !== "acceptance") {
      issues.push({
        level: "error",
        code: "flow_must_end_with_acceptance",
        message: `${node.id} 是终点但不是验收门`,
        node_id: node.id,
      });
    }
  }

  for (const node of flow.nodes) {
    if (node.type === "condition") {
      // 4：条件只能读事实字段
      if (!FACT_FIELDS.includes(node.when.field)) {
        issues.push({
          level: "error",
          code: "condition_uses_non_fact_field",
          message: `${node.id} 的条件引用了非事实字段`,
          node_id: node.id,
        });
      }
    }

    if (node.type === "timer") {
      // 10：超时不得自动通过
      const onTimeout = node.on_timeout as string;
      if (!["remind", "escalate", "block"].includes(onTimeout)) {
        issues.push({
          level: "error",
          code: "timer_cannot_auto_approve",
          message: `${node.id} 的超时策略不得自动通过`,
          node_id: node.id,
        });
      }
      if (!(node.hours > 0) || node.hours > 31 * 24) {
        issues.push({
          level: "error",
          code: "timer_out_of_range",
          message: `${node.id} 的时限必须在 1 小时到 31 天之间`,
          node_id: node.id,
        });
      }
    }

    if (node.type === "cc") {
      // 11：抄送不计票、不阻塞
      if (node.to.length === 0) {
        issues.push({
          level: "error",
          code: "cc_must_not_vote",
          message: `${node.id} 的抄送对象为空`,
          node_id: node.id,
        });
      }
    }

    if (node.type === "terminate") {
      // 8：终止仅管理员
      if (node.admin_only !== true) {
        issues.push({
          level: "error",
          code: "terminate_requires_admin_only",
          message: `${node.id} 的终止只能由管理员触发`,
          node_id: node.id,
        });
      }
    }

    if (node.type === "parallel") {
      if (node.branches.length === 0) {
        issues.push({
          level: "error",
          code: "parallel_without_branch",
          message: `${node.id} 没有分支`,
          node_id: node.id,
        });
      }
      const nested = node.branches.some(
        (branch) => nodeById.get(branch)?.type === "parallel",
      );
      if (nested) {
        issues.push({
          level: "error",
          code: "nested_parallel_unsupported",
          message: `${node.id} 不支持嵌套并行`,
          node_id: node.id,
        });
      }
    }

    if (node.type === "gate") {
      const policy = node.gate;
      const high =
        policy.applies_to.risk_levels.some(
          (risk) => risk === "high" || risk === "critical",
        ) || (isHighRiskFlow(flow) && policy.kind === "acceptance");

      // 9：审批人/升级链不得为空
      if (policy.approver.roles.length === 0) {
        issues.push({
          level: "error",
          code: "approver_or_escalation_empty",
          message: `${node.id} 没有审批角色`,
          node_id: node.id,
        });
      }
      if (policy.escalation.to_roles.length === 0) {
        issues.push({
          level: "error",
          code: "approver_or_escalation_empty",
          message: `${node.id} 没有升级角色，空审批人将无人兜底`,
          node_id: node.id,
        });
      }

      // 2：高风险路径必须有人工门
      if (isHighRiskFlow(flow) && node.gate.kind === "acceptance") {
        if (policy.auto_approve || !policy.human_required) {
          issues.push({
            level: "error",
            code: "high_risk_requires_human_gate",
            message: `${node.id} 是高风险验收门，必须保留人工确认`,
            node_id: node.id,
          });
        }
      }
      if (high && policy.approver.min_distinct < 2) {
        issues.push({
          level: "error",
          code: "high_risk_requires_human_gate",
          message: `${node.id} 的高风险门至少需要 2 个不同席位`,
          node_id: node.id,
        });
      }

      // 5：高风险验收禁止转交
      if (high && node.gate.kind === "acceptance" && policy.approver.allow_delegate) {
        issues.push({
          level: "error",
          code: "delegate_forbidden_on_high_acceptance",
          message: `${node.id} 的高风险验收禁止转交`,
          node_id: node.id,
        });
      }

      // 6：加签必须会签（否则既有批准失效没有意义）
      if (policy.approver.allow_add_signer && policy.approver.quorum !== "all") {
        issues.push({
          level: "error",
          code: "add_signer_requires_quorum_all",
          message: `${node.id} 开启加签时必须使用会签（all）`,
          node_id: node.id,
        });
      }

      // 7：退回只能退到祖先门
      if (policy.rejection.rewind_to !== "none") {
        const ancestors = ancestorGates(flow, node.id);
        if (!ancestors.some((gate) => gate.gate.kind === policy.rejection.rewind_to)) {
          issues.push({
            level: "error",
            code: "rewind_target_not_ancestor",
            message: `${node.id} 的退回目标 ${policy.rejection.rewind_to} 不是祖先门`,
            node_id: node.id,
          });
        }
      }
    }
  }

  if (flow.guardrails.must_end_with !== "acceptance") {
    issues.push({
      level: "error",
      code: "flow_must_end_with_acceptance",
      message: "guardrails.must_end_with 必须为 acceptance",
    });
  }

  return issues;
}

export function assertGateFlow(flow: GateFlow): void {
  const errors = validateGateFlow(flow).filter(
    (issue) => issue.level === "error",
  );
  if (errors.length > 0) {
    throw new Error(
      `GateFlow 校验失败：\n${errors
        .map((issue) => `- [${issue.code}] ${issue.message}`)
        .join("\n")}`,
    );
  }
}

/* ------------------------------------------------------------------ */
/* 运行层：GateRun 状态机                                              */
/* ------------------------------------------------------------------ */

export type GateRunStatus =
  | "running"
  | "waiting_human"
  | "waiting_timer"
  | "completed"
  | "terminated";

export type GateRunEventType =
  | "flow.started"
  | "node.entered"
  | "node.approved"
  | "node.rejected"
  | "node.rewound"
  | "node.signer_added"
  | "node.cc"
  | "timer.waiting"
  | "timer.fired"
  | "flow.completed"
  | "flow.terminated";

export interface GateRunEvent {
  type: GateRunEventType;
  node_id?: string;
  at: number;
  detail?: Record<string, unknown>;
}

interface JoinState {
  next: string;
  remaining: string[];
  join: "all" | "any";
}

export interface GateRun {
  run_id: string;
  flow_id: string;
  flow_version: number;
  task_id: string;
  trace_id: string;
  status: GateRunStatus;
  node_id: string | null;
  facts: GateFacts;
  /** node_id → 该门收到的席位票 */
  approvals: Record<string, SeatVote[]>;
  joins: Record<string, JoinState>;
  cc: string[];
  visited: string[];
  events: GateRunEvent[];
  terminated?: { reason: string };
}

function cloneRun(run: GateRun): GateRun {
  return {
    ...run,
    approvals: Object.fromEntries(
      Object.entries(run.approvals).map(([key, votes]) => [key, [...votes]]),
    ),
    joins: Object.fromEntries(
      Object.entries(run.joins).map(([key, state]) => [
        key,
        { ...state, remaining: [...state.remaining] },
      ]),
    ),
    cc: [...run.cc],
    visited: [...run.visited],
    events: [...run.events],
  };
}

function event(
  run: GateRun,
  type: GateRunEventType,
  nodeId: string | undefined,
  now: number,
  detail?: Record<string, unknown>,
): void {
  run.events.push({ type, node_id: nodeId, at: now, detail });
}

function branchAdvance(run: GateRun, nodeId: string, next: string): string {
  for (const [parallelId, join] of Object.entries(run.joins)) {
    if (next !== parallelId) continue;
    if (join.join === "any" || join.remaining.length === 0) {
      delete run.joins[parallelId];
      return join.next;
    }
    return join.remaining.shift() as string;
  }
  return next;
}

function evalCondition(expr: ConditionExpr, facts: GateFacts): boolean {
  const actual = facts[expr.field];
  switch (expr.op) {
    case "eq":
      return actual === expr.value;
    case "neq":
      return actual !== expr.value;
    case "gt":
      return typeof actual === "number" && actual > Number(expr.value);
    case "lt":
      return typeof actual === "number" && actual < Number(expr.value);
    case "in":
      return Array.isArray(expr.value) && expr.value.includes(String(actual));
  }
}

export function startGateRun(
  flow: GateFlow,
  opts: {
    taskId: string;
    traceId: string;
    facts: GateFacts;
    seats?: GateSeat[];
    producer?: ProducerIdentity;
    now?: number;
  },
): GateRun {
  const now = opts.now ?? Date.now();
  const run: GateRun = {
    run_id: `${flow.flow_id}:${opts.taskId}:${now}`,
    flow_id: flow.flow_id,
    flow_version: flow.version,
    task_id: opts.taskId,
    trace_id: opts.traceId,
    status: "running",
    node_id: flow.entry,
    facts: opts.facts,
    approvals: {},
    joins: {},
    cc: [],
    visited: [],
    events: [],
  };
  event(run, "flow.started", undefined, now, { entry: flow.entry });
  return driveGateRun(flow, run, {
    now,
    seats: opts.seats,
    producer: opts.producer,
  });
}

export interface DriveOptions {
  seats?: GateSeat[];
  producer?: ProducerIdentity;
  now?: number;
}

/**
 * 推进到下一个需要外部动作的位置：
 * - condition/cc 自动通过；
 * - timer 停在 waiting_timer，必须显式 fire；
 * - gate 需要足够票才会通过；不足则 waiting_human；
 * - 驳回 → 退回目标门并清空后续票。
 */
export function driveGateRun(
  flow: GateFlow,
  input: GateRun,
  opts: DriveOptions = {},
): GateRun {
  const run = cloneRun(input);
  const now = opts.now ?? Date.now();
  const seats = opts.seats ?? [];
  const nodeById = new Map(flow.nodes.map((node) => [node.id, node]));
  let guard = 0;

  while (run.node_id && guard++ < flow.nodes.length * 3) {
    const node = nodeById.get(run.node_id);
    if (!node) {
      run.status = "terminated";
      run.terminated = { reason: `unknown_node:${run.node_id}` };
      break;
    }
    if (!run.visited.includes(node.id)) run.visited.push(node.id);

    if (node.type === "terminate") {
      run.status = "terminated";
      run.terminated = { reason: node.reason };
      event(run, "flow.terminated", node.id, now, { reason: node.reason });
      return run;
    }

    if (node.type === "condition") {
      event(run, "node.entered", node.id, now);
      run.node_id = evalCondition(node.when, run.facts) ? node.then : node.else;
      continue;
    }

    if (node.type === "cc") {
      event(run, "node.entered", node.id, now);
      run.cc.push(...node.to);
      event(run, "node.cc", node.id, now, { to: node.to });
      run.node_id = node.next;
      continue;
    }

    if (node.type === "timer") {
      event(run, "node.entered", node.id, now);
      run.status = "waiting_timer";
      event(run, "timer.waiting", node.id, now, {
        hours: node.hours,
        on_timeout: node.on_timeout,
      });
      return run;
    }

    if (node.type === "parallel") {
      event(run, "node.entered", node.id, now);
      if (node.branches.length === 0) {
        run.node_id = node.next;
        continue;
      }
      run.joins[node.id] = {
        next: node.next,
        join: node.join,
        remaining: node.branches.slice(1),
      };
      run.node_id = node.branches[0];
      continue;
    }

    // gate：只有票够了才推进
    event(run, "node.entered", node.id, now);
    const plan = resolveApprovalPlan(node.gate, seats, opts.producer);
    if (plan.blocked) {
      run.status = "waiting_human";
      event(run, "node.entered", node.id, now, {
        blocked: plan.reason,
        escalated_to: plan.escalated_to,
      });
      return run;
    }

    const votes = run.approvals[node.id] ?? [];
    const tally = tallySeatVotes(
      votes,
      plan,
      node.gate.approver.quorum as Quorum,
    );
    if (votes.some((vote) => vote.verdict === "rejected")) {
      const rewindTo = node.gate.rejection.rewind_to;
      const target =
        ancestorGates(flow, node.id).find(
          (item) => item.gate.kind === rewindTo,
        ) ??
        flow.nodes.find(
          (item) => item.type === "gate" && item.gate.kind === rewindTo,
        );
      if (rewindTo !== "none" && target) {
        for (const key of Object.keys(run.approvals)) delete run.approvals[key];
        event(run, "node.rejected", node.id, now, { rewind_to: rewindTo });
        event(run, "node.rewound", target.id, now, { from: node.id });
        run.node_id = target.id;
        run.status = "running";
        continue;
      }
      run.status = "waiting_human";
      event(run, "node.rejected", node.id, now, { rewind_to: "none" });
      return run;
    }

    if (tally.approved) {
      event(run, "node.approved", node.id, now, {
        seats: tally.approved_seats,
      });
      if (!node.next) {
        run.node_id = null;
        run.status = "completed";
        event(run, "flow.completed", undefined, now);
        return run;
      }
      run.node_id = branchAdvance(run, node.id, node.next);
      continue;
    }

    run.status = "waiting_human";
    return run;
  }

  if (!run.node_id) {
    run.status = "completed";
    event(run, "flow.completed", undefined, now);
  }
  return run;
}

/** 提交某个门的席位票；不足则停在 waiting_human */
export function decideGateRun(
  flow: GateFlow,
  input: GateRun,
  nodeId: string,
  votes: SeatVote[],
  opts: DriveOptions = {},
): GateRun {
  const run = cloneRun(input);
  run.approvals[nodeId] = [...(run.approvals[nodeId] ?? []), ...votes];
  run.node_id = nodeId;
  run.status = "running";
  return driveGateRun(flow, run, opts);
}

/** 加签：既有批准立即失效，必须重新计票 */
export function addSigner(
  flow: GateFlow,
  input: GateRun,
  nodeId: string,
  now: number = Date.now(),
): GateRun {
  const run = cloneRun(input);
  run.approvals[nodeId] = [];
  run.node_id = nodeId;
  run.status = "running";
  event(run, "node.signer_added", nodeId, now, { invalidated: true });
  return driveGateRun(flow, run, { now });
}

/** 定时器到点：只推进到下一节点，绝不自动批准任何门 */
export function fireGateTimer(
  flow: GateFlow,
  input: GateRun,
  opts: DriveOptions = {},
): GateRun {
  const run = cloneRun(input);
  const now = opts.now ?? Date.now();
  if (run.status !== "waiting_timer" || !run.node_id) return run;
  const node = flow.nodes.find((item) => item.id === run.node_id);
  if (node?.type !== "timer") return run;
  event(run, "timer.fired", node.id, now, { on_timeout: node.on_timeout });
  run.node_id = node.next;
  run.status = "running";
  return driveGateRun(flow, run, { ...opts, now });
}

export function gateRunToGateKind(flow: GateFlow, nodeId: string): GateKind | null {
  const node = flow.nodes.find((item) => item.id === nodeId);
  return node?.type === "gate" ? node.gate.kind : null;
}
