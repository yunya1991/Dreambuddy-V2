/**
 * 对外任务看板契约（T0）。
 *
 * 定位：TraceSpan 是内部打点（粒度过细、含实现细节），不能直接驱动对外看板。
 * 这里定义面向用户的业务事件与快照，由编排侧投影、前端归并，
 * 保证同一 trace_id 无论实时接收还是事后回放都得到同一份快照。
 *
 * 约定：
 * - 事件幂等：同 (task_id, type, entity_id) 只认最大 seq；
 * - 事件有序：回放按 seq 升序；
 * - 数据如实：缺失进 data_quality，禁止用 0 或"中性"冒充。
 */

import type { UncertaintyVerdict } from "@/lib/verdict/uncertainty-verdict";
import type { GateRun } from "@/lib/task-board/gate-flow";

/** 看板六个步骤（对外展示，不出现 SACG 等内部术语） */
export type TaskStage =
  | "intent"
  | "spec"
  | "dispatch"
  | "execute"
  | "accept"
  | "summary";

export const TASK_STAGE_LABEL: Record<TaskStage, string> = {
  intent: "意图识别",
  spec: "生成 SPEC",
  dispatch: "派工",
  execute: "执行中",
  accept: "验收",
  summary: "汇总",
};

export const TASK_STAGE_ORDER: TaskStage[] = [
  "intent",
  "spec",
  "dispatch",
  "execute",
  "accept",
  "summary",
];

export type TaskStatus =
  | "pending"
  | "running"
  | "waiting"
  | "done"
  | "degraded"
  | "failed"
  | "terminated";

/** 验收结论：绿 / 黄 / 红 */
export type Verdict = "pass" | "pending" | "fail";

/**
 * 人工门禁：看板不只是展示，未确认的节点必须阻断下游。
 * 门禁与证据版本绑定，证据变化后旧确认自动失效，防止 AI 带着过期授权继续跑。
 */
export type GateKind = "intent" | "spec" | "dispatch" | "acceptance" | "summary";

export type GateStatus = "waiting" | "approved" | "rejected";

export interface TaskGate {
  /** 固定为 kind，保证同一任务同一道门只有一个状态 */
  gate_id: string;
  kind: GateKind;
  title: string;
  status: GateStatus;
  required: boolean;
  /** 本次确认所依据的证据版本（如 spec:v2） */
  evidence_ref: string;
  /** 不允许匿名确认 */
  decided_by?: string;
  decided_at?: number;
  /** 驳回时必填 */
  comment?: string;
  /** 驳回后回转到的门；缺省按策略默认回转 */
  rewind_to?: GateKind;
  /** 门禁进入 waiting 的时间；SLA 从这里起算 */
  requested_at?: number;
  /** 已提醒次数（限流，避免审批疲劳） */
  remind_count?: number;
  reminded_at?: number;
  escalated_at?: number;
}

export const GATE_TITLE: Record<GateKind, string> = {
  intent: "意图确认",
  spec: "SPEC 确认",
  dispatch: "派工确认",
  acceptance: "验收确认",
  summary: "交付确认",
};

/** 门禁对应的工作步骤 */
export const GATE_STAGE: Record<GateKind, TaskStage> = {
  intent: "intent",
  spec: "spec",
  dispatch: "dispatch",
  acceptance: "accept",
  summary: "summary",
};

export type IntentGateKey = "brainstorm" | "reverse_parse" | "external_collect";

export interface IntentGate {
  key: IntentGateKey;
  label: string;
  hit: boolean;
  reason?: string;
}

export interface IntentDecision {
  raw_input: string;
  gates: IntentGate[];
  /** 判定结论，如「直接生成 SPEC，无需多 Agent 辩论」 */
  decision: string;
  /**
   * 是否需要用户当场确认。
   * 只有「意图澄清」与「写操作」两类需要打断对话；普通问答不产生人工门。
   */
  requires_confirmation?: boolean;
}

export interface SpecField {
  key: string;
  label: string;
  value: string;
}

export interface TaskSpec {
  spec_id: string;
  version: number;
  status: "draft" | "confirmed";
  fields: SpecField[];
}

/** 与 okr_ticket_bridge.py 的三种完成策略一一对应 */
export type VerifyKind = "evidence_backed" | "gap_closed" | "c_action";

export interface OkrNode {
  node_id: string;
  objective: string;
  criteria: string;
  verify: VerifyKind;
  owner?: string;
  /** evidence_backed 策略所需的证据锚点 */
  evidence_id?: string;
  evidence_count: number;
  verdict: Verdict;
  reason?: string;
}

export interface TaskObjective {
  title: string;
  owner: string;
  mode: "judge" | "supervise";
  deadline?: string;
  confidence_threshold: number;
  /** 0-1 */
  progress: number;
  /** 待验证命题（T3.1）：验收门按 required_verdict_level 检查 */
  claims?: string[];
  /** 所需裁决级别；U2 起必须有沙箱/回测证据 */
  required_verdict_level?: "U0" | "U1" | "U2" | "U3";
  /** 是否因等待裁决而挂起（waiting_verdict） */
  waiting_verdict?: boolean;
}

export type AgentState =
  | "pending"
  | "running"
  | "waiting"
  | "done"
  | "degraded"
  | "failed";

export interface AgentRun {
  role: string;
  label: string;
  state: AgentState;
  capability_ids: string[];
  summary?: string;
  evidence_count: number;
  duration_ms?: number;
}

export interface AcceptanceRecord {
  role: string;
  node_id: string;
  verdict: Verdict;
  reason?: string;
  evidence_refs: string[];
  ts: number;
}

export interface DataQualityItem {
  item: string;
  status: "missing" | "partial" | "stale";
}

export interface TaskSummary {
  conclusion: string;
  key_points: string[];
  /** 编排侧未给出时为 undefined，前端显示"—"，不得填 0 冒充 */
  confidence?: number;
  data_quality: DataQualityItem[];
}

/** 执行步骤的汇报与独立评审结果（每步必须先汇报、再评审、后推进） */
export interface TaskStep {
  step_id: string;
  index: number;
  title: string;
  summary: string;
  /** pass=评审通过；fail=被驳回；pending=评审模型不可用（不阻塞但显式标注） */
  verdict: "pass" | "fail" | "pending";
  reviewer?: string;
  comment?: string;
  ts: number;
}

export interface TaskBoardSnapshot {
  task_id: string;
  trace_id: string;
  status: TaskStatus;
  stage: TaskStage;
  intent?: IntentDecision;
  spec?: TaskSpec;
  objective?: TaskObjective;
  krs: OkrNode[];
  agents: AgentRun[];
  /** 逐步执行记录：右栏按顺序点亮，评审未过不进入下一步 */
  steps?: TaskStep[];
  acceptance: AcceptanceRecord[];
  /** 人工门禁：由证据自动生成，确认动作只能由 gate.updated 事件写入 */
  gates: TaskGate[];
  summary?: TaskSummary;
  /** GateFlow 运行实例：流程节点、当前停留位置与审批事件（append-only） */
  flow?: GateRun;
  /** 管理员终止：终止后不再接受任何门禁推进 */
  terminated?: { reason: string; by: string; at: number };
  /** 已应用事件游标：`${type}:${entityId}` → seq */
  cursors: Record<string, number>;
  seq: number;
  updated_at: number;
}

interface TaskEventBase {
  task_id: string;
  trace_id: string;
  /** 单调递增，用于排序与幂等判定 */
  seq: number;
  /** epoch ms */
  ts: number;
}

export type TaskBoardEvent =
  | (TaskEventBase & { type: "intent.decided"; payload: IntentDecision })
  | (TaskEventBase & { type: "spec.updated"; payload: TaskSpec })
  | (TaskEventBase & {
      type: "okr.updated";
      payload: { objective: TaskObjective; krs: OkrNode[] };
    })
  | (TaskEventBase & { type: "agent.updated"; payload: AgentRun })
  | (TaskEventBase & { type: "acceptance.recorded"; payload: AcceptanceRecord })
  | (TaskEventBase & { type: "step.reported"; payload: TaskStep })
  | (TaskEventBase & { type: "gate.updated"; payload: TaskGate })
  | (TaskEventBase & { type: "verdict.updated"; payload: UncertaintyVerdict })
  | (TaskEventBase & { type: "flow.updated"; payload: GateRun })
  | (TaskEventBase & {
      type: "task.terminated";
      payload: { reason: string; by: string; at: number };
    })
  | (TaskEventBase & { type: "summary.ready"; payload: TaskSummary });

export const TASK_EVENT_TYPES: TaskBoardEvent["type"][] = [
  "intent.decided",
  "spec.updated",
  "okr.updated",
  "agent.updated",
  "acceptance.recorded",
  "step.reported",
  "gate.updated",
  "verdict.updated",
  "flow.updated",
  "task.terminated",
  "summary.ready",
];

/** 事件的幂等实体：同一实体只保留最大 seq */
export function taskEventEntityId(event: TaskBoardEvent): string {
  switch (event.type) {
    case "intent.decided":
      return "intent";
    case "spec.updated":
      return event.payload.spec_id || "spec";
    case "okr.updated":
      return "okr";
    case "agent.updated":
      return event.payload.role;
    case "acceptance.recorded":
      return `${event.payload.role}:${event.payload.node_id}`;
    case "step.reported":
      return event.payload.step_id;
    case "gate.updated":
      return event.payload.gate_id;
    case "verdict.updated":
      return event.payload.verdict_id || "verdict";
    case "flow.updated":
      return "flow";
    case "task.terminated":
      return "terminated";
    case "summary.ready":
      return "summary";
  }
}

export function emptyTaskBoard(
  taskId: string,
  traceId: string,
): TaskBoardSnapshot {
  return {
    task_id: taskId,
    trace_id: traceId,
    status: "pending",
    stage: "intent",
    krs: [],
    agents: [],
    steps: [],
    acceptance: [],
    gates: [],
    cursors: {},
    seq: -1,
    updated_at: 0,
  };
}

/** 各道门当前绑定的证据版本：证据变了，旧确认必须失效 */
function gateEvidenceRefs(
  snapshot: TaskBoardSnapshot,
): Partial<Record<GateKind, string>> {
  const refs: Partial<Record<GateKind, string>> = {};
  // 意图与 SPEC 都不自动设门：SPEC 每次任务都会生成，确认只在
  // 「写操作 / 意图澄清」时通过对话内弹窗发生，避免每轮对话都产生待办。
  // 只有已存在的 SPEC 门（历史记录或显式写操作）才继续参与证据一致性重算。
  if (snapshot.spec && snapshot.gates.some((gate) => gate.kind === "spec")) {
    refs.spec = `spec:${snapshot.spec.spec_id}:v${snapshot.spec.version}`;
  }
  if (snapshot.objective && snapshot.krs.length > 0) {
    refs.dispatch = `okr:${snapshot.cursors["okr.updated:okr"] ?? 0}`;
  }
  if (snapshot.acceptance.length > 0) {
    const latest = Math.max(...snapshot.acceptance.map((item) => item.ts));
    refs.acceptance = `acceptance:${snapshot.acceptance.length}:${latest}`;
  }
  if (snapshot.summary) {
    refs.summary = `summary:${snapshot.cursors["summary.ready:summary"] ?? 0}`;
  }
  return refs;
}

/**
 * 用事实重算门禁列表：只保留与当前证据一致的确认结果。
 * 任何新证据都会把对应门重置为 waiting，防止带着过期授权继续执行。
 */
function reconcileGates(snapshot: TaskBoardSnapshot): TaskGate[] {
  const refs = gateEvidenceRefs(snapshot);
  const prev = new Map(snapshot.gates.map((gate) => [gate.kind, gate]));
  return (Object.keys(refs) as GateKind[]).map((kind) => {
    const evidenceRef = refs[kind] as string;
    const old = prev.get(kind);
    const keep = old?.evidence_ref === evidenceRef && old.status !== "waiting";
    return {
      gate_id: kind,
      kind,
      title: GATE_TITLE[kind],
      required: true,
      evidence_ref: evidenceRef,
      status: keep ? (old as TaskGate).status : "waiting",
      decided_by: keep ? (old as TaskGate).decided_by : undefined,
      decided_at: keep ? (old as TaskGate).decided_at : undefined,
      comment: keep ? (old as TaskGate).comment : undefined,
      rewind_to: keep ? (old as TaskGate).rewind_to : undefined,
      requested_at: keep
        ? (old as TaskGate).requested_at
        : snapshot.updated_at,
      remind_count: keep ? (old as TaskGate).remind_count : 0,
      reminded_at: keep ? (old as TaskGate).reminded_at : undefined,
      escalated_at: keep ? (old as TaskGate).escalated_at : undefined,
    };
  });
}

/**
 * 由已发生的事实推导当前步骤（只看已收到的事件，不做文本推断）。
 *
 * 门禁不篡改进度：stage 永远反映「实际做到哪」，待确认状态由 status=waiting
 * 与 gates 表达。否则已发生的执行会被回退成"未派工"，看板会说谎。
 */
function deriveStage(snapshot: TaskBoardSnapshot): TaskStage {
  if (snapshot.summary) return "summary";
  if (snapshot.acceptance.length > 0) return "accept";
  if (snapshot.agents.some((agent) => agent.state !== "pending")) {
    return "execute";
  }
  if (snapshot.krs.length > 0) return "dispatch";
  if (snapshot.spec) return "spec";
  return "intent";
}

function deriveStatus(snapshot: TaskBoardSnapshot): TaskStatus {
  if (snapshot.terminated) return "terminated";
  const required = snapshot.gates.filter((gate) => gate.required);
  // 门禁优先：未确认就绝不显示为完成
  if (required.some((gate) => gate.status === "waiting")) return "waiting";
  if (required.some((gate) => gate.status === "rejected")) return "degraded";
  if (snapshot.summary) return "done";
  if (snapshot.agents.some((agent) => agent.state === "failed")) return "failed";
  if (snapshot.agents.some((agent) => agent.state === "degraded")) {
    return "degraded";
  }
  if (snapshot.agents.some((agent) => agent.state === "running")) {
    return "running";
  }
  if (snapshot.acceptance.some((item) => item.verdict === "fail")) {
    return "degraded";
  }
  return "pending";
}

/** 同一角色的多次能力调用归并到一张卡：能力取并集，状态取最新 */
function upsertAgent(agents: AgentRun[], next: AgentRun): AgentRun[] {
  const index = agents.findIndex((agent) => agent.role === next.role);
  if (index < 0) return [...agents, next];
  const prev = agents[index];
  const merged: AgentRun = {
    ...prev,
    ...next,
    capability_ids: [...new Set([...prev.capability_ids, ...next.capability_ids])],
    evidence_count: Math.max(prev.evidence_count, next.evidence_count),
  };
  const copy = [...agents];
  copy[index] = merged;
  return copy;
}

/**
 * 归并单个业务事件。
 *
 * - 事件 task_id 不匹配：原样返回（防止串任务）；
 * - 同实体旧 seq：原样返回同一引用（幂等，便于 React 侧引用比较）；
 * - acceptance.recorded 同时回写对应 KR 的 verdict。
 */
export function applyTaskEvent(
  snapshot: TaskBoardSnapshot,
  event: TaskBoardEvent,
): TaskBoardSnapshot {
  if (snapshot.task_id !== event.task_id) return snapshot;

  const cursorKey = `${event.type}:${taskEventEntityId(event)}`;
  const applied = snapshot.cursors[cursorKey];
  if (typeof applied === "number" && applied >= event.seq) return snapshot;

  const next: TaskBoardSnapshot = {
    ...snapshot,
    cursors: { ...snapshot.cursors, [cursorKey]: event.seq },
    seq: Math.max(snapshot.seq, event.seq),
    updated_at: Math.max(snapshot.updated_at, event.ts),
  };

  switch (event.type) {
    case "intent.decided":
      next.intent = event.payload;
      break;
    case "spec.updated":
      next.spec = event.payload;
      break;
    case "okr.updated":
      next.objective = event.payload.objective;
      next.krs = event.payload.krs;
      break;
    case "agent.updated":
      next.agents = upsertAgent(snapshot.agents, event.payload);
      break;
    case "step.reported": {
      const steps = snapshot.steps ?? [];
      const exists = steps.some((step) => step.step_id === event.payload.step_id);
      next.steps = exists
        ? steps.map((step) =>
            step.step_id === event.payload.step_id ? event.payload : step,
          )
        : [...steps, event.payload].sort((a, b) => a.index - b.index);
      break;
    }
    case "acceptance.recorded": {
      const record = event.payload;
      next.acceptance = [...snapshot.acceptance, record];
      next.krs = snapshot.krs.map((kr) =>
        kr.node_id === record.node_id
          ? {
              ...kr,
              verdict: record.verdict,
              reason: record.reason,
              evidence_count: Math.max(kr.evidence_count, record.evidence_refs.length),
              evidence_id: record.evidence_refs[0] ?? kr.evidence_id,
            }
          : kr,
      );
      break;
    }
    case "gate.updated": {
      const incoming = event.payload;
      const exists = snapshot.gates.some((gate) => gate.gate_id === incoming.gate_id);
      next.gates = exists
        ? snapshot.gates.map((gate) =>
            gate.gate_id === incoming.gate_id ? { ...gate, ...incoming } : gate,
          )
        : [...snapshot.gates, incoming];
      break;
    }
    case "verdict.updated":
      // 裁决权威副本经 appendTaskEvents 落 L0 事件流；快照只推进游标与时间
      break;
    case "flow.updated":
      next.flow = event.payload;
      break;
    case "task.terminated":
      next.terminated = event.payload;
      break;
    case "summary.ready":
      next.summary = event.payload;
      break;
  }

  // 证据变化会让旧确认失效；门禁状态永远是「事实 + 最近一次确认」的交集
  next.gates = reconcileGates(next);
  next.stage = deriveStage(next);
  next.status = deriveStatus(next);
  return next;
}

/** 按 seq 升序回放一组事件 */
export function buildTaskBoard(
  taskId: string,
  traceId: string,
  events: TaskBoardEvent[],
): TaskBoardSnapshot {
  return [...events]
    .sort((a, b) => a.seq - b.seq)
    .reduce(applyTaskEvent, emptyTaskBoard(taskId, traceId));
}
