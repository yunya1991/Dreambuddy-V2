// ============================================================================
// 写操作收尾（SPEC-7 §9-1/2）
// ----------------------------------------------------------------------------
// 事务提交后：尽力推送 27 审计，再回读 opLog 得到最终状态。
// 推送失败不影响本次写结果（保留 PENDING_AUDIT + warnings，由补偿任务重试）。
// ============================================================================

import type { AdminOperationLog } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import { flushAuditOutbox } from "@/lib/admin/audit/outbox";

export async function finalizeOp(op: AdminOperationLog): Promise<AdminOperationLog> {
  try {
    await flushAuditOutbox(3);
  } catch {
    // 审计推送异常不得污染写结果，交由定时补偿任务兜底
  }
  return (await prisma.adminOperationLog.findUnique({ where: { id: op.id } })) ?? op;
}

export interface WriteResponseData {
  opId: string | null;
  status: string;
  before: unknown;
  after: unknown;
  diff: unknown;
  warnings: unknown[];
  requiresRestart: boolean;
  simulated?: boolean;
}

export function opResponseData(op: AdminOperationLog): WriteResponseData {
  return {
    opId: op.id,
    status: op.status,
    before: op.beforeData ?? null,
    after: op.afterData ?? null,
    diff: op.diff ?? null,
    warnings: Array.isArray(op.warnings) ? (op.warnings as unknown[]) : [],
    requiresRestart: false,
  };
}

export function dryRunResponseData(input: {
  before: unknown;
  after: unknown;
  diff: unknown;
}): WriteResponseData {
  return {
    opId: null,
    status: "DRY_RUN",
    before: input.before,
    after: input.after,
    diff: input.diff,
    warnings: [],
    requiresRestart: false,
    simulated: true,
  };
}
