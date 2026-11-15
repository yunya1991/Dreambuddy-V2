// ============================================================================
// 积分调账规则（SPEC-7 §6.3 / D3 定稿）
// ----------------------------------------------------------------------------
// 纯函数，不依赖 Prisma，便于 node --test 直接覆盖分档边界：
//   |delta| ≤ 500   → L0
//   501 ~ 5000      → L1
//   > 5000          → 拒绝（RULE_BLOCKED，P1 起转 27 审批）
//   单用户日累计 ≤ 20000
//   余额不足（balance + delta < 0）→ 拒绝
// ============================================================================

import { AdminError } from "../errors.ts";
import {
  CREDITS_ADJUST_DAILY_MAX,
  CREDITS_ADJUST_L0_MAX,
  CREDITS_ADJUST_L1_MAX,
} from "../constants.ts";

export type CreditsAdjustLevel = "L0" | "L1";

/** 金额比较统一保留 2 位小数，避免浮点尾差影响边界判定 */
function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

export function creditsAdjustMagnitude(delta: number): number {
  return round2(Math.abs(delta));
}

/** 分档：只接受已通过 assertCreditsDeltaAllowed 的入参 */
export function resolveCreditsAdjustLevel(delta: number): CreditsAdjustLevel {
  return creditsAdjustMagnitude(delta) <= CREDITS_ADJUST_L0_MAX ? "L0" : "L1";
}

/** 数值合法性 + 单次上限（>5000 直接拒绝，不走审批） */
export function assertCreditsDeltaAllowed(delta: unknown): number {
  if (typeof delta !== "number" || !Number.isFinite(delta)) {
    throw new AdminError("VALIDATION_FAILED", "调账数量必须是有效数字");
  }
  const magnitude = creditsAdjustMagnitude(delta);
  if (magnitude === 0) {
    throw new AdminError("VALIDATION_FAILED", "调账数量不能为 0");
  }
  if (magnitude > CREDITS_ADJUST_L1_MAX) {
    throw new AdminError(
      "RULE_BLOCKED",
      `单次调账不得超过 ${CREDITS_ADJUST_L1_MAX}，超过请走 27 审批`,
    );
  }
  return round2(delta);
}

/** 日累计上限：已用额度 + 本次绝对值不能超过 20000 */
export function assertDailyCap(usedToday: number, delta: number): void {
  const total = round2(round2(usedToday) + creditsAdjustMagnitude(delta));
  if (total > CREDITS_ADJUST_DAILY_MAX) {
    throw new AdminError(
      "RULE_BLOCKED",
      `该用户当日调账累计将达 ${total}，超过上限 ${CREDITS_ADJUST_DAILY_MAX}`,
    );
  }
}

/** 余额不得为负：扣减时 delta 为负数 */
export function assertBalanceSufficient(balance: number, delta: number): void {
  if (round2(balance + delta) < 0) {
    throw new AdminError(
      "RULE_BLOCKED",
      `余额不足：当前 ${round2(balance)}，本次扣减 ${creditsAdjustMagnitude(delta)}`,
    );
  }
}

/** 调账流水描述：统一前缀用于日累计归集 */
export function buildAdjustDescription(prefix: string, reason: string | null): string {
  return `${prefix}${reason || "手工调账"}`;
}
