// ============================================================================
// 确认令牌单测（SPEC-7 §8.2 / §14-1 的 confirmToken 重放）
// 覆盖：正常签发校验、签名篡改、过期、绑定字段不匹配、指纹规范化
// ============================================================================

import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import {
  canonicalStringify,
  createConfirmToken,
  hashPayload,
  verifyConfirmToken,
} from "./confirm-token.ts";
import { AdminError } from "./errors.ts";

process.env.ADMIN_CONFIRM_SECRET = "unit-test-confirm-secret-0123456789abcdef";

const EXPECTED = {
  uid: "U-admin-1",
  action: "credits.adjust",
  targetId: "U-target-1",
  payloadHash: "hash-of-payload",
};

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

test("签发后可校验，nonce 唯一且带有效期", () => {
  const first = createConfirmToken(EXPECTED);
  const second = createConfirmToken(EXPECTED);
  assert.notEqual(first.nonce, second.nonce, "两次签发 nonce 必须不同");
  assert.ok(first.exp * 1000 > Date.now());

  const payload = verifyConfirmToken(first.token, EXPECTED);
  assert.equal(payload.uid, EXPECTED.uid);
  assert.equal(payload.action, EXPECTED.action);
  assert.equal(payload.targetId, EXPECTED.targetId);
  assert.equal(payload.payloadHash, EXPECTED.payloadHash);
  assert.equal(payload.nonce, first.nonce);
});

test("签名被篡改 → VALIDATION_FAILED", () => {
  const { token } = createConfirmToken(EXPECTED);
  const [body] = token.split(".");
  expectCode(
    () => verifyConfirmToken(`${body}.${"0".repeat(64)}`, EXPECTED),
    "VALIDATION_FAILED",
    "篡改签名",
  );
});

test("绑定字段不匹配（换 targetId / 换 payload）→ VALIDATION_FAILED", () => {
  const { token } = createConfirmToken(EXPECTED);
  expectCode(
    () => verifyConfirmToken(token, { ...EXPECTED, targetId: "U-other" }),
    "VALIDATION_FAILED",
    "换 targetId",
  );
  expectCode(
    () => verifyConfirmToken(token, { ...EXPECTED, payloadHash: "another-hash" }),
    "VALIDATION_FAILED",
    "换 payloadHash",
  );
});

test("过期令牌 → VALIDATION_FAILED", () => {
  const payload = {
    ...EXPECTED,
    nonce: "nonce-expired",
    exp: Math.floor(Date.now() / 1000) - 10,
  };
  const payloadB64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = createHmac("sha256", process.env.ADMIN_CONFIRM_SECRET as string)
    .update(payloadB64)
    .digest("hex");
  expectCode(
    () => verifyConfirmToken(`${payloadB64}.${signature}`, EXPECTED),
    "VALIDATION_FAILED",
    "过期",
  );
});

test("指纹规范化：键序不影响 payloadHash", () => {
  const a = { action: "credits.adjust", targetId: "U-1", delta: 500 };
  const b = { delta: 500, action: "credits.adjust", targetId: "U-1" };
  assert.equal(canonicalStringify(a), canonicalStringify(b));
  assert.equal(hashPayload(a), hashPayload(b));
  assert.notEqual(hashPayload(a), hashPayload({ ...a, delta: 501 }));
});

test("密钥缺失时签发失败（FAIL-CLOSED）", () => {
  const original = process.env.ADMIN_CONFIRM_SECRET;
  delete process.env.ADMIN_CONFIRM_SECRET;
  try {
    expectCode(() => createConfirmToken(EXPECTED), "WRITE_DISABLED", "缺密钥");
  } finally {
    process.env.ADMIN_CONFIRM_SECRET = original;
  }
});
