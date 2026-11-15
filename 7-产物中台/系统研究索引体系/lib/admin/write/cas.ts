// ============================================================================
// CAS（乐观并发）工具（SPEC-7 §8.2 / §8.4）
// ----------------------------------------------------------------------------
// 统一口径：Body 必带 expectedUpdatedAt，条件更新命中 0 行即 409 CONFLICT_STALE。
// 所有写操作必须走 updateMany + 条件 where，禁止 findUnique 后无条件 update。
// ============================================================================

import { AdminError } from "@/lib/admin/errors";

/** 解析并校验 expectedUpdatedAt（ISO 字符串 / 毫秒时间戳） */
export function parseExpectedUpdatedAt(value: unknown): Date {
  if (value === undefined || value === null || value === "") {
    throw new AdminError("VALIDATION_FAILED", "缺少 expectedUpdatedAt（并发控制必填）");
  }
  const date =
    typeof value === "number"
      ? new Date(value)
      : typeof value === "string"
        ? new Date(value)
        : null;
  if (!date || Number.isNaN(date.getTime())) {
    throw new AdminError("VALIDATION_FAILED", "expectedUpdatedAt 格式不正确");
  }
  return date;
}

/** 条件更新命中 0 行 → 409；返回影响行数便于调用方继续判断 */
export function assertCasHit(count: number, message = "数据已被其他操作修改，请刷新后重试"): void {
  if (count === 0) {
    throw new AdminError("CONFLICT_STALE", message);
  }
}
