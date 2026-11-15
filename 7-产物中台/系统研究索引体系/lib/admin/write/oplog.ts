// ============================================================================
// 管理台写操作日志服务（SPEC-7 §4.1 / §9）
// ----------------------------------------------------------------------------
// 唯一入口写 admin_operation_logs：
//   - 事务内创建（PENDING_AUDIT），保证「库变更」与「留痕」原子
//   - 提交后由审计 outbox 异步推送 27，成功才置 APPLIED
// ============================================================================

import type { AdminOperationLog, Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import type { AdminLevel, AdminOpStatus } from "../constants";

/** 允许在事务内复用：Prisma.TransactionClient 与单例同构 */
export type DbClient = Prisma.TransactionClient | typeof prisma;

export interface CreateOpLogInput {
  requestId: string;
  idempotencyKey?: string | null;
  nonce?: string | null;
  actorUid: string;
  actorRole: string;
  level: AdminLevel;
  action: string;
  targetType: string;
  targetId: string;
  reason?: string | null;
  beforeData?: unknown | null;
  afterData?: unknown | null;
  diff?: unknown | null;
  status?: AdminOpStatus;
  warnings?: unknown | null;
  snapshotPath?: string | null;
  ip?: string | null;
  userAgent?: string | null;
}

function jsonOrUndefined(value: unknown): Prisma.InputJsonValue | undefined {
  return value === null || value === undefined
    ? undefined
    : (value as Prisma.InputJsonValue);
}

export async function createOpLog(
  db: DbClient,
  input: CreateOpLogInput,
): Promise<AdminOperationLog> {
  return db.adminOperationLog.create({
    data: {
      requestId: input.requestId,
      idempotencyKey: input.idempotencyKey ?? undefined,
      nonce: input.nonce ?? undefined,
      actorUid: input.actorUid,
      actorRole: input.actorRole,
      level: input.level,
      action: input.action,
      targetType: input.targetType,
      targetId: input.targetId,
      reason: input.reason ?? undefined,
      beforeData: jsonOrUndefined(input.beforeData),
      afterData: jsonOrUndefined(input.afterData),
      diff: jsonOrUndefined(input.diff),
      status: input.status ?? "PENDING_AUDIT",
      warnings: jsonOrUndefined(input.warnings),
      snapshotPath: input.snapshotPath ?? undefined,
      ip: input.ip ?? undefined,
      userAgent: input.userAgent ?? undefined,
    },
  });
}

export interface OpLogPatch {
  status?: AdminOpStatus;
  afterData?: unknown | null;
  diff?: unknown | null;
  warnings?: unknown | null;
  errorCode?: string | null;
  errorMessage?: string | null;
  approvalId?: string | null;
  auditHash?: string | null;
  snapshotPath?: string | null;
  appliedAt?: Date | null;
  rolledBackAt?: Date | null;
  auditFlushedAt?: Date | null;
}

export async function updateOpLog(
  db: DbClient,
  id: string,
  patch: OpLogPatch,
): Promise<AdminOperationLog> {
  return db.adminOperationLog.update({
    where: { id },
    data: {
      status: patch.status,
      afterData: jsonOrUndefined(patch.afterData),
      diff: jsonOrUndefined(patch.diff),
      warnings: jsonOrUndefined(patch.warnings),
      errorCode: patch.errorCode ?? undefined,
      errorMessage: patch.errorMessage ?? undefined,
      approvalId: patch.approvalId ?? undefined,
      auditHash: patch.auditHash ?? undefined,
      snapshotPath: patch.snapshotPath ?? undefined,
      appliedAt: patch.appliedAt ?? undefined,
      rolledBackAt: patch.rolledBackAt ?? undefined,
      auditFlushedAt: patch.auditFlushedAt ?? undefined,
    },
  });
}

export async function findByRequestId(requestId: string) {
  return prisma.adminOperationLog.findUnique({ where: { requestId } });
}

export async function findByIdempotencyKey(key: string) {
  return prisma.adminOperationLog.findUnique({ where: { idempotencyKey: key } });
}

/** 待补偿审计：未成功推送到 27 的记录 */
export async function findPendingAudit(limit: number) {
  return prisma.adminOperationLog.findMany({
    where: {
      auditFlushedAt: null,
      status: { in: ["PENDING_AUDIT", "APPLIED", "APPLIED_WITH_WARNINGS", "ROLLED_BACK"] },
    },
    orderBy: { createdAt: "asc" },
    take: limit,
  });
}
