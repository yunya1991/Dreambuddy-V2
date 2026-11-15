// ============================================================================
// 确认令牌（SPEC-7 §8.2）
// ----------------------------------------------------------------------------
// 无状态 HMAC + nonce 唯一落库实现「一次性确认」：
//   token = base64url(payload) + "." + hex(HMAC-SHA256(secret, base64url(payload)))
//   payload = { uid, action, targetId, payloadHash, nonce, exp }
// 校验顺序：签名 → exp → 字段匹配 → nonce 未被使用（由 admin_operation_logs.nonce
// 唯一索引兜底，插入冲突即重放，拒绝）。
// ============================================================================

import { createHmac, randomBytes, createHash, timingSafeEqual } from "node:crypto";
import { AdminError } from "./errors.ts";
import { ADMIN_CONFIRM_TOKEN_TTL_SEC, ENV_ADMIN_CONFIRM_SECRET } from "./constants.ts";

export interface ConfirmTokenPayload {
  uid: string;
  action: string;
  targetId: string;
  payloadHash: string;
  nonce: string;
  exp: number;
}

function getConfirmSecret(): string {
  const secret = process.env[ENV_ADMIN_CONFIRM_SECRET];
  if (!secret || secret.length < 32) {
    throw new AdminError(
      "WRITE_DISABLED",
      `${ENV_ADMIN_CONFIRM_SECRET} 未配置或长度不足 32 位，确认令牌不可用`,
    );
  }
  return secret;
}

function sign(payloadB64: string): string {
  return createHmac("sha256", getConfirmSecret()).update(payloadB64).digest("hex");
}

/**
 * 规范化 JSON（键名递归排序），保证「同一份载荷」在任何键序下指纹一致。
 * 确认令牌签发端与校验端必须用同一个函数计算 payloadHash。
 */
export function canonicalStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalStringify(item)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort();
  return `{${keys
    .map((key) => `${JSON.stringify(key)}:${canonicalStringify(record[key])}`)
    .join(",")}}`;
}

/** 计算请求体指纹，绑定 token 与本次载荷，防止换 body 重放 */
export function hashPayload(body: unknown): string {
  return createHash("sha256")
    .update(canonicalStringify(body ?? null))
    .digest("hex");
}

export function createConfirmToken(input: {
  uid: string;
  action: string;
  targetId: string;
  payloadHash: string;
}): { token: string; nonce: string; exp: number } {
  const nonce = randomBytes(16).toString("hex");
  const exp = Math.floor(Date.now() / 1000) + ADMIN_CONFIRM_TOKEN_TTL_SEC;
  const payload: ConfirmTokenPayload = { ...input, nonce, exp };
  const payloadB64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return { token: `${payloadB64}.${sign(payloadB64)}`, nonce, exp };
}

/** 校验签名 + 有效期 + 绑定字段；nonce 一次性由调用方落库时保证 */
export function verifyConfirmToken(
  token: string,
  expected: { uid: string; action: string; targetId: string; payloadHash: string },
): ConfirmTokenPayload {
  const [payloadB64, signature] = (token || "").split(".");
  if (!payloadB64 || !signature) {
    throw new AdminError("VALIDATION_FAILED", "确认令牌格式不正确");
  }

  const expectedSig = sign(payloadB64);
  const a = Buffer.from(signature, "utf8");
  const b = Buffer.from(expectedSig, "utf8");
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    throw new AdminError("VALIDATION_FAILED", "确认令牌签名无效");
  }

  let payload: ConfirmTokenPayload;
  try {
    payload = JSON.parse(Buffer.from(payloadB64, "base64url").toString("utf8"));
  } catch {
    throw new AdminError("VALIDATION_FAILED", "确认令牌内容损坏");
  }

  if (typeof payload.exp !== "number" || payload.exp * 1000 <= Date.now()) {
    throw new AdminError("VALIDATION_FAILED", "确认令牌已过期，请重新确认");
  }
  if (
    payload.uid !== expected.uid ||
    payload.action !== expected.action ||
    payload.targetId !== expected.targetId ||
    payload.payloadHash !== expected.payloadHash
  ) {
    throw new AdminError("VALIDATION_FAILED", "确认令牌与本次操作不匹配");
  }
  if (!payload.nonce) {
    throw new AdminError("VALIDATION_FAILED", "确认令牌缺少 nonce");
  }

  return payload;
}
