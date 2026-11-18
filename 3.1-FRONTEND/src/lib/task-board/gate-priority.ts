/**
 * 门禁风险与 SLA 常量（客户端安全，无 Node 依赖）。
 *
 * 治理抽屉需要在前端判断「这条待办该不该自动弹出」，
 * 因此把纯常量从 gate-policy 中拆出来，避免把服务端策略模块打进客户端包。
 * gate-policy 继续 re-export，保持既有调用方不变。
 */

import type { GateKind } from "@/types/task-board";

export type GateRiskLevel = "low" | "medium" | "high" | "critical";

/** 每道门的固有风险：验收门最高，永远需要人工 */
export const GATE_RISK: Record<GateKind, GateRiskLevel> = {
  intent: "low",
  spec: "medium",
  dispatch: "medium",
  acceptance: "high",
  summary: "low",
};

/** 每道门的确认时限（分钟）；超过阈值即视为紧急 */
export const GATE_SLA_MINUTES: Record<GateKind, number> = {
  intent: 240,
  spec: 480,
  dispatch: 240,
  acceptance: 120,
  summary: 240,
};

/** 距 SLA 到期不足该分钟数时，待办升级为高优先级 */
export const SLA_URGENT_MINUTES = 15;

export function isHighPriorityGate(
  kind: GateKind,
  waitingMinutes: number,
): boolean {
  const risk = GATE_RISK[kind];
  if (risk === "high" || risk === "critical") return true;
  return waitingMinutes >= GATE_SLA_MINUTES[kind] - SLA_URGENT_MINUTES;
}
