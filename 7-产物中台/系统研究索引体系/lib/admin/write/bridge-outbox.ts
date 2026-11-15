// ============================================================================
// Bridge 补偿（SPEC-7 §4.1 失败语义矩阵：非交易类失败 → APPLIED_WITH_WARNINGS）
// ----------------------------------------------------------------------------
// 扫描 status=APPLIED_WITH_WARNINGS 且 warnings 里存在 bridge_sync_failed 的 opLog，
// 按 warnings[].patch 重放一次 PUT 27 /api/v1/config：
//   · 成功 → warnings 追加 bridge_sync_recovered，status 升为 APPLIED
//   · 失败 → 累加 attempts / 刷新 at，保持 APPLIED_WITH_WARNINGS
// 幂等：已恢复的记录不再命中（status 已变 APPLIED 且无 failed 条目）。
// ============================================================================

import type { Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { putGovernanceConfig } from "./bridge.ts";
import { updateOpLog } from "./oplog.ts";

const FAILED_KIND = "bridge_sync_failed";
const RECOVERED_KIND = "bridge_sync_recovered";
const DEFAULT_BATCH = 20;

export interface BridgeFlushResult {
  scanned: number;
  recovered: number;
  failed: number;
  errors: string[];
}

interface BridgeWarning {
  kind?: unknown;
  at?: unknown;
  error?: unknown;
  attempts?: unknown;
  patch?: unknown;
  [key: string]: unknown;
}

function asWarnings(value: Prisma.JsonValue | null): BridgeWarning[] {
  if (!Array.isArray(value)) return [];
  const out: BridgeWarning[] = [];
  for (const item of value) {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      out.push(item as BridgeWarning);
    }
  }
  return out;
}

function hasRetryablePatch(warning: BridgeWarning): boolean {
  return (
    warning.kind === FAILED_KIND &&
    Boolean(warning.patch) &&
    typeof warning.patch === "object" &&
    !Array.isArray(warning.patch)
  );
}

export async function retryPendingBridgeSyncs(
  limit = DEFAULT_BATCH,
): Promise<BridgeFlushResult> {
  const result: BridgeFlushResult = { scanned: 0, recovered: 0, failed: 0, errors: [] };

  const candidates = await prisma.adminOperationLog.findMany({
    where: { status: "APPLIED_WITH_WARNINGS" },
    orderBy: { createdAt: "asc" },
    take: limit,
  });

  for (const op of candidates) {
    const warnings = asWarnings(op.warnings);
    const pending = warnings.filter(hasRetryablePatch);
    if (pending.length === 0) continue;
    result.scanned += 1;

    const outcome = await putGovernanceConfig(pending[pending.length - 1].patch as Record<string, unknown>);
    if (outcome.ok) {
      const nextWarnings = warnings.map((item) =>
        item.kind === FAILED_KIND
          ? {
              ...item,
              kind: RECOVERED_KIND,
              at: new Date().toISOString(),
              error: "",
            }
          : item,
      );
      await updateOpLog(prisma, op.id, {
        status: "APPLIED",
        warnings: nextWarnings as unknown as Prisma.InputJsonValue,
      });
      result.recovered += 1;
      continue;
    }

    result.failed += 1;
    result.errors.push(`${op.id}: ${outcome.error}`);
    const nextWarnings = warnings.map((item) =>
      item.kind === FAILED_KIND
        ? {
            ...item,
            at: new Date().toISOString(),
            error: outcome.error || "unknown",
            attempts: Number(item.attempts || 0) + 1,
          }
        : item,
    );
    await updateOpLog(prisma, op.id, {
      warnings: nextWarnings as unknown as Prisma.InputJsonValue,
    });
  }

  return result;
}
