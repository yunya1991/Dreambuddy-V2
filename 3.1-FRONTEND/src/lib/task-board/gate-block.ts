/**
 * 对话侧门禁拦截：任务存在未确认门禁时，拒绝继续推进。
 *
 * 只看必需门：approved 放行；waiting / rejected 都算阻塞。
 * 全权模式下低/中风险门应已被自动确认，剩余阻塞门即人工门。
 */

import type { TaskBoardSnapshot, TaskGate } from "@/types/task-board";
import type { GateMode } from "./gate-policy";

export function blockingGates(snapshot: TaskBoardSnapshot): TaskGate[] {
  return snapshot.gates.filter(
    (gate) => gate.required && gate.status !== "approved",
  );
}

export interface GatePendingPayload {
  ok: false;
  error: {
    code: "GATE_PENDING";
    message: string;
  };
  task_id: string;
  mode: GateMode;
  pending_gates: Array<{
    gate_id: string;
    kind: TaskGate["kind"];
    title: string;
    status: TaskGate["status"];
    evidence_ref: string;
    comment?: string;
  }>;
}

export function buildGatePendingPayload(
  snapshot: TaskBoardSnapshot,
  mode: GateMode,
): GatePendingPayload {
  const pending = blockingGates(snapshot);
  return {
    ok: false,
    error: {
      code: "GATE_PENDING",
      message: `任务有 ${pending.length} 道门禁待确认，确认后才能继续。`,
    },
    task_id: snapshot.task_id,
    mode,
    pending_gates: pending.map((gate) => ({
      gate_id: gate.gate_id,
      kind: gate.kind,
      title: gate.title,
      status: gate.status,
      evidence_ref: gate.evidence_ref,
      comment: gate.comment,
    })),
  };
}
