// ============================================================================
// 写接口限流（SPEC-7 §5.3-4）
// ----------------------------------------------------------------------------
// 进程内存滑动窗口：20 次/分钟/actor。
// 前提：PM2 固定 instances=1（§12.3），水平扩容前必须改为 Redis。
// ============================================================================

import { AdminError } from "@/lib/admin/errors";
import { ADMIN_WRITE_RATE_LIMIT, ADMIN_WRITE_RATE_WINDOW_MS } from "@/lib/admin/constants";

const buckets = new Map<string, number[]>();

export function assertWithinRateLimit(actorUid: string, now = Date.now()): void {
  const windowStart = now - ADMIN_WRITE_RATE_WINDOW_MS;
  const hits = (buckets.get(actorUid) || []).filter((t) => t > windowStart);

  if (hits.length >= ADMIN_WRITE_RATE_LIMIT) {
    buckets.set(actorUid, hits);
    throw new AdminError(
      "RATE_LIMITED",
      `写操作过于频繁（上限 ${ADMIN_WRITE_RATE_LIMIT} 次/分钟）`,
    );
  }

  hits.push(now);
  buckets.set(actorUid, hits);

  // 轻量清理：桶过大时按窗口裁掉过期记录（避免 Map 迭代触发 es5 降级限制）
  if (buckets.size > 500) {
    buckets.forEach((list, key) => {
      const alive = list.filter((t) => t > windowStart);
      if (alive.length === 0) buckets.delete(key);
      else buckets.set(key, alive);
    });
  }
}

/** 仅用于测试/排障 */
export function resetRateLimit(): void {
  buckets.clear();
}
