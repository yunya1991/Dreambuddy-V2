/**
 * A2 派发器：把已通过 dispatch 门的 KR 转成子 Agent 执行计划。
 *
 * 硬约束：
 * - 1 KR = 1 AgentRun，role 唯一（同域多 KR 也不合并）；
 * - 门未通过时只允许 waiting，永不写 running；
 * - 子 Agent 的能力白名单直接继承 KR.capability_ids，越界即失败（由执行侧校验）。
 */

import type { AgentRun, OkrNode, TaskBoardEvent } from "@/types/task-board";
import type { DispatchGateDecision } from "./okr-gate";

export interface DispatchOptions {
  decision: DispatchGateDecision;
  /** 阻塞说明（门未通过时写入 agent.summary） */
  blocker?: string;
}

function roleFor(kr: OkrNode): string {
  const base = kr.owner_agent?.trim() || kr.owner_domain?.trim() || "agent:generic";
  // 同一能力域会承接多个 KR，角色必须带 KR 后缀，避免看板按 role 归并丢卡片
  return `${base}#${kr.node_id}`;
}

/** 生成派发计划：门通过 → pending；门未通过 → waiting（绝不 running） */
export function planAgentRuns(krs: OkrNode[], options: DispatchOptions): AgentRun[] {
  const approved = options.decision.status === "approved";
  return krs.map((kr) => ({
    role: roleFor(kr),
    label: kr.objective,
    state: approved ? "pending" : "waiting",
    capability_ids: [...(kr.capability_ids ?? [])],
    summary: approved
      ? undefined
      : options.blocker ||
        `dispatch 门未通过：${options.decision.detail.join("；") || "待人工确认"}`,
    evidence_count: 0,
  }));
}

/** 投影为 agent.updated 事件（seq 由服务端统一分配） */
export function buildAgentDispatchEvents(
  taskId: string,
  traceId: string,
  runs: AgentRun[],
  now: number = Date.now(),
): TaskBoardEvent[] {
  return runs.map((run) => ({
    task_id: taskId,
    trace_id: traceId,
    seq: 0,
    ts: now,
    type: "agent.updated" as const,
    payload: run,
  }));
}
