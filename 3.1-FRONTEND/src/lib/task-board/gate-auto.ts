/**
 * 运行模式落地：全权模式自动确认低/中风险门。
 *
 * - 人工干预模式：不产生任何自动确认；
 * - 全权模式：仅 intent / spec / dispatch / summary 可自动确认；
 * - acceptance 属 high 风险，任何模式都必须人工确认。
 */

import type {
  GateKind,
  TaskBoardEvent,
  TaskBoardSnapshot,
} from "@/types/task-board";
import { GATE_RISK, type GateMode } from "./gate-policy";

export function isAutoApprovable(kind: GateKind): boolean {
  const risk = GATE_RISK[kind];
  return risk !== "high" && risk !== "critical";
}

export function autoApproveGates(
  snapshot: TaskBoardSnapshot,
  mode: GateMode,
  now: number = Date.now(),
): TaskBoardEvent[] {
  if (mode !== "autonomy") return [];

  return snapshot.gates
    .filter(
      (gate) =>
        gate.required &&
        gate.status === "waiting" &&
        isAutoApprovable(gate.kind),
    )
    .map((gate) => ({
      task_id: snapshot.task_id,
      trace_id: snapshot.trace_id,
      seq: 0, // 服务端重新分配
      ts: now,
      type: "gate.updated" as const,
      payload: {
        ...gate,
        status: "approved" as const,
        decided_by: "mode:autonomy",
        decided_at: now,
        comment: `全权模式自动确认（${GATE_RISK[gate.kind]}）`,
      },
    }));
}
