// ============================================================================
// 幂等回放（SPEC-7 §8.2）
// ----------------------------------------------------------------------------
// 规则：写请求必带 Idempotency-Key；命中已有 opLog 时直接回放首次结果，
// 不重复落库、不重复推送审计。同一 key 跨 action 复用视为非法（400）。
// ============================================================================

import type { AdminOperationLog } from "@prisma/client";
import { AdminError } from "@/lib/admin/errors";
import { findByIdempotencyKey } from "./oplog";

const KEY_PATTERN = /^[A-Za-z0-9._:-]{8,128}$/;

export function requireIdempotencyKey(request: Request): string {
  const raw = request.headers.get("idempotency-key");
  const key = raw?.trim();
  if (!key) {
    throw new AdminError("VALIDATION_FAILED", "缺少 Idempotency-Key 请求头");
  }
  if (!KEY_PATTERN.test(key)) {
    throw new AdminError(
      "VALIDATION_FAILED",
      "Idempotency-Key 需为 8-128 位字母/数字/._:- 组合",
    );
  }
  return key;
}

/** 命中则返回历史记录；action 不一致直接拒绝，避免 key 串用 */
export async function findReplay(
  key: string,
  action: string,
): Promise<AdminOperationLog | null> {
  const existing = await findByIdempotencyKey(key);
  if (!existing) return null;
  if (existing.action !== action) {
    throw new AdminError(
      "VALIDATION_FAILED",
      "Idempotency-Key 已被其他操作占用，请更换",
    );
  }
  return existing;
}

/** 首次结果的回放响应体（结构与写接口一致） */
export function buildReplayPayload(op: AdminOperationLog) {
  return {
    opId: op.id,
    status: op.status,
    before: op.beforeData ?? null,
    after: op.afterData ?? null,
    diff: op.diff ?? null,
    warnings: op.warnings ?? [],
    requiresRestart: false,
    replayed: true,
  };
}
