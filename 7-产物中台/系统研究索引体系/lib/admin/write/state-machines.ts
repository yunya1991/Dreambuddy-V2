// ============================================================================
// 状态机白名单（SPEC-7 §6.2 / §14-1 状态机单测）
// ----------------------------------------------------------------------------
// 只放行显式声明的迁移；其余一律 RULE_BLOCKED。系统置位字段（如 LOCKED）永不允许
// 管理员直接写入，避免绕过亏损风控。
// ============================================================================

import { AdminError } from "../errors.ts";

/** 策略：DRAFT → APPROVED → APPLIED ↔ PAUSED；EXPIRED 为终态 */
export const STRATEGY_TRANSITIONS: Record<string, readonly string[]> = {
  DRAFT: ["APPROVED"],
  APPROVED: ["APPLIED", "PAUSED"],
  APPLIED: ["PAUSED"],
  PAUSED: ["APPLIED"],
  EXPIRED: [],
};

/** 任务：ACTIVE ↔ PAUSED，二者均可收敛到 COMPLETED；FAILED 可人工恢复 */
export const TASK_TRANSITIONS: Record<string, readonly string[]> = {
  ACTIVE: ["PAUSED", "COMPLETED"],
  PAUSED: ["ACTIVE", "COMPLETED"],
  FAILED: ["ACTIVE", "PAUSED"],
  COMPLETED: [],
};

/** 订单：仅允许 PENDING→CANCELLED、PAID→COMPLETED（§6.2） */
export const ORDER_TRANSITIONS: Record<string, readonly string[]> = {
  PENDING: ["CANCELLED"],
  PAID: ["COMPLETED"],
};

/**
 * 交易状态：管理员可置 ACTIVE / PAUSED / FROZEN，
 * LOCKED（亏损超限）只能由系统置位，管理员只能从 LOCKED 迁出。
 */
export const TRADING_STATUS_ADMIN_TARGETS = ["ACTIVE", "PAUSED", "FROZEN"] as const;

function assertTransition(
  label: string,
  map: Record<string, readonly string[]>,
  from: string,
  to: string,
): void {
  if (from === to) {
    throw new AdminError("RULE_BLOCKED", `${label}已是 ${to}，无需变更`);
  }
  const allowed = map[from];
  if (!allowed) {
    throw new AdminError("RULE_BLOCKED", `未知的${label}当前状态：${from}`);
  }
  if (!allowed.includes(to)) {
    throw new AdminError(
      "RULE_BLOCKED",
      `${label}不允许从 ${from} 迁移到 ${to}（允许：${allowed.join("/") || "无"}）`,
    );
  }
}

export function assertStrategyTransition(from: string, to: string): void {
  assertTransition("策略状态", STRATEGY_TRANSITIONS, from, to);
}

export function assertTaskTransition(from: string, to: string): void {
  assertTransition("任务状态", TASK_TRANSITIONS, from, to);
}

export function assertOrderTransition(from: string, to: string): void {
  assertTransition("订单状态", ORDER_TRANSITIONS, from, to);
}

export function assertTradingStatusTarget(to: string): void {
  if (!(TRADING_STATUS_ADMIN_TARGETS as readonly string[]).includes(to)) {
    throw new AdminError(
      "RULE_BLOCKED",
      `交易状态仅允许管理员置为 ${TRADING_STATUS_ADMIN_TARGETS.join("/")}；LOCKED 由系统置位`,
    );
  }
}
