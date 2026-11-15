// ============================================================================
// 脱敏与差异单测（SPEC-7 §5.3-2 / §14-1）
// 覆盖：白名单投影、密文掩码、差异计算、L1 原因长度校验
// ============================================================================

import test from "node:test";
import assert from "node:assert/strict";
import { assertReason, buildDiff, projectSafe } from "./diff.ts";
import { AdminError } from "../errors.ts";

test("白名单投影：未声明字段一律丢弃", () => {
  const source = {
    uid: "U-1",
    balance: 100,
    passwordHash: "$2b$10$xxxx",
    encryptedData: "cipher",
  };
  const safe = projectSafe(source, ["uid", "balance"]);
  assert.deepEqual(safe, { uid: "U-1", balance: 100 });
});

test("兜底掩码：即使误把密文字段加入白名单也不会落盘", () => {
  const safe = projectSafe(
    { uid: "U-1", passwordHash: "$2b$10$xxxx", authTag: "tag", apiKey: "sk-xxx" },
    ["uid", "passwordHash", "authTag", "apiKey"],
  );
  assert.equal(safe?.uid, "U-1");
  assert.equal(safe?.passwordHash, "••••");
  assert.equal(safe?.authTag, "••••");
  assert.equal(safe?.apiKey, "••••");
});

test("空对象与 null 输入", () => {
  assert.equal(projectSafe(null, ["uid"]), null);
  assert.deepEqual(projectSafe({}, ["uid"]), {});
  assert.deepEqual(buildDiff(null, null), {});
});

test("差异计算：只输出变化的字段", () => {
  const diff = buildDiff(
    { uid: "U-1", balance: 100, totalEarned: 100 },
    { uid: "U-1", balance: 600, totalEarned: 600 },
  );
  assert.deepEqual(diff, {
    balance: { from: 100, to: 600 },
    totalEarned: { from: 100, to: 600 },
  });
});

test("L1 原因不少于 10 字，L0 可空", () => {
  assert.equal(assertReason(undefined, "L0"), null);
  assert.equal(assertReason("  ", "L0"), null);
  assert.equal(assertReason("补偿用户", "L0"), "补偿用户");
  assert.equal(
    assertReason("  补偿用户损失，人工核对后调整  ", "L1"),
    "补偿用户损失，人工核对后调整",
  );
  assert.throws(
    () => assertReason("太短", "L1"),
    (error: unknown) =>
      error instanceof AdminError && (error as AdminError).code === "VALIDATION_FAILED",
  );
  assert.throws(
    () => assertReason(undefined, "L2"),
    (error: unknown) => error instanceof AdminError,
  );
});
