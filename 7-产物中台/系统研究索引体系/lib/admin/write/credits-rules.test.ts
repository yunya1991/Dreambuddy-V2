// ============================================================================
// 积分调账规则单测（SPEC-7 §6.3 / G1 边界矩阵）
// 覆盖：500→L0 / 501→L1 / 5001→拒绝 / 日累计 20001→拒绝 / 余额不足→拒绝
// ============================================================================

import test from "node:test";
import assert from "node:assert/strict";
import {
  assertBalanceSufficient,
  assertCreditsDeltaAllowed,
  assertDailyCap,
  buildAdjustDescription,
  creditsAdjustMagnitude,
  resolveCreditsAdjustLevel,
} from "./credits-rules.ts";
import { AdminError } from "../errors.ts";

function expectCode(fn: () => void, code: string, label: string) {
  assert.throws(
    fn,
    (error: unknown) => {
      assert.ok(error instanceof AdminError, `${label} 应抛 AdminError`);
      assert.equal((error as AdminError).code, code, `${label} 错误码应为 ${code}`);
      return true;
    },
    label,
  );
}

test("分档边界：500 → L0，501 → L1，5000 → L1", () => {
  assert.equal(resolveCreditsAdjustLevel(500), "L0");
  assert.equal(resolveCreditsAdjustLevel(-500), "L0");
  assert.equal(resolveCreditsAdjustLevel(501), "L1");
  assert.equal(resolveCreditsAdjustLevel(5000), "L1");
  assert.equal(resolveCreditsAdjustLevel(-5000), "L1");
});

test("单次上限：5001 直接 RULE_BLOCKED，5000 放行", () => {
  assert.equal(assertCreditsDeltaAllowed(5000), 5000);
  assert.equal(assertCreditsDeltaAllowed(-5000), -5000);
  expectCode(() => assertCreditsDeltaAllowed(5001), "RULE_BLOCKED", "5001");
  expectCode(() => assertCreditsDeltaAllowed(-5001), "RULE_BLOCKED", "-5001");
});

test("数值合法性：0 / NaN / 非数字 → VALIDATION_FAILED", () => {
  expectCode(() => assertCreditsDeltaAllowed(0), "VALIDATION_FAILED", "0");
  expectCode(() => assertCreditsDeltaAllowed(Number.NaN), "VALIDATION_FAILED", "NaN");
  expectCode(
    () => assertCreditsDeltaAllowed("100" as unknown as number),
    "VALIDATION_FAILED",
    "字符串",
  );
});

test("日累计上限：20000 内放行，超过即 RULE_BLOCKED", () => {
  assert.doesNotThrow(() => assertDailyCap(15000, 5000));
  assert.doesNotThrow(() => assertDailyCap(0, 5000));
  expectCode(() => assertDailyCap(19500, 501), "RULE_BLOCKED", "19500+501");
  expectCode(() => assertDailyCap(20000, 1), "RULE_BLOCKED", "20000+1");
  expectCode(() => assertDailyCap(19999.99, 1), "RULE_BLOCKED", "浮点边界");
});

test("余额不得为负：扣减等于余额放行，超出即 RULE_BLOCKED", () => {
  assert.doesNotThrow(() => assertBalanceSufficient(100, -100));
  assert.doesNotThrow(() => assertBalanceSufficient(0, 0));
  expectCode(() => assertBalanceSufficient(100, -100.01), "RULE_BLOCKED", "余额不足");
  expectCode(() => assertBalanceSufficient(0, -1), "RULE_BLOCKED", "零余额扣减");
});

test("辅助函数：绝对值与流水描述", () => {
  assert.equal(creditsAdjustMagnitude(-321.456), 321.46);
  assert.equal(buildAdjustDescription("管理台调账：", null), "管理台调账：手工调账");
  assert.equal(buildAdjustDescription("管理台调账：", "补偿用户"), "管理台调账：补偿用户");
});
