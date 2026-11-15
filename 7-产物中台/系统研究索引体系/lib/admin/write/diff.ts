// ============================================================================
// 审计数据脱敏与差异计算（SPEC-7 §5.3-2）
// ----------------------------------------------------------------------------
// 采用「白名单投影」而非黑名单：只有显式声明为可审计的字段才会进入
// before/after/diff，其余字段一律丢弃；同时叠加一层密文兜底，防止误传。
// ============================================================================

import { AdminError } from "../errors.ts";

/** 兜底掩码：即使白名单误配，也绝不落盘这些形态的值 */
const SECRET_KEY_PATTERN =
  /(password|passwd|secret|token|cookie|encrypted|authTag|cipher|apikey|api_key|privatekey|private_key)/i;

const MASK = "••••";

function maskIfSecret(key: string, value: unknown): unknown {
  if (SECRET_KEY_PATTERN.test(key)) return MASK;
  return value;
}

/**
 * 白名单投影：只保留 allow 中声明的字段。
 * before/after 写入 opLog 前必须经过此函数。
 */
export function projectSafe(
  source: Record<string, unknown> | null | undefined,
  allow: readonly string[],
): Record<string, unknown> | null {
  if (!source) return null;
  const out: Record<string, unknown> = {};
  for (const key of allow) {
    if (!(key in source)) continue;
    out[key] = maskIfSecret(key, source[key]);
  }
  return out;
}

/**
 * 递归密文掩码：用于 JSON 字段（如 pushRules）入审计前的兜底，
 * 逐层把命中密钥模式的键替换为掩码，其余结构保持不变。
 */
export function maskDeep(value: unknown, depth = 0): unknown {
  if (depth > 6) return MASK;
  if (Array.isArray(value)) return value.map((item) => maskDeep(item, depth + 1));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      out[key] = SECRET_KEY_PATTERN.test(key) ? MASK : maskDeep(item, depth + 1);
    }
    return out;
  }
  return value;
}

export interface FieldDiff {
  from: unknown;
  to: unknown;
}

/** 浅层差异：仅比较投影后的安全字段 */
export function buildDiff(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): Record<string, FieldDiff> {
  const diff: Record<string, FieldDiff> = {};
  const keys = Array.from(
    new Set([...Object.keys(before || {}), ...Object.keys(after || {})]),
  );
  for (const key of keys) {
    const from = before ? before[key] : undefined;
    const to = after ? after[key] : undefined;
    if (JSON.stringify(from) !== JSON.stringify(to)) {
      diff[key] = { from: from ?? null, to: to ?? null };
    }
  }
  return diff;
}

/** 校验必填原因（L1/L2 至少 10 字） */
export function assertReason(reason: unknown, level: "L0" | "L1" | "L2"): string | null {
  if (level === "L0") {
    return typeof reason === "string" && reason.trim() ? reason.trim() : null;
  }
  if (typeof reason !== "string" || reason.trim().length < 10) {
    throw new AdminError("VALIDATION_FAILED", "该操作需要填写不少于 10 个字的原因");
  }
  return reason.trim();
}
