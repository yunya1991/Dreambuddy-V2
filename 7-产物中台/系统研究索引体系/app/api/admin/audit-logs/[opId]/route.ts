// ============================================================================
// GET /api/admin/audit-logs/[opId] —— 单条操作详情（SPEC-7 §8.3）
// ----------------------------------------------------------------------------
// 附带：该操作的回滚记录、是否允许自动回滚（L0/L1 且未被回滚）。
// ============================================================================

import { AdminError, apiFail, apiOk, newRequestId } from "@/lib/admin/errors";
import { prisma } from "@/lib/prisma";
import { requireAdmin } from "@/lib/admin/auth";
import { ROLLBACK_ACTION } from "@/lib/admin/constants";
import { isAdminFileKey, readConfigFile } from "@/lib/admin/write/file-config";

export const dynamic = "force-dynamic";

const ROLLBACKABLE_STATUS = ["PENDING_AUDIT", "APPLIED", "APPLIED_WITH_WARNINGS"];

export async function GET(_request: Request, { params }: { params: { opId: string } }) {
  const requestId = newRequestId();
  try {
    await requireAdmin();

    const op = await prisma.adminOperationLog.findUnique({ where: { id: params.opId } });
    if (!op) {
      throw new AdminError("NOT_FOUND", "操作记录不存在");
    }

    const rollbacks = await prisma.adminOperationLog.findMany({
      where: { action: ROLLBACK_ACTION, targetId: op.id },
      orderBy: { createdAt: "desc" },
    });

    const canRollback =
      op.action !== ROLLBACK_ACTION &&
      op.level !== "L2" &&
      ROLLBACKABLE_STATUS.includes(op.status) &&
      rollbacks.length === 0;

    const meta = await readTargetMeta(op.targetType, op.targetId);

    return apiOk(
      { op, rollbacks, canRollback, ...meta },
      { requestId, message: "ok" },
    );
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}

interface TargetMeta {
  /** 单表目标的当前 updatedAt（回滚 CAS 基准） */
  targetUpdatedAt: string | null;
  /** 复合目标（交易开关跨 UserProfile + TradingParams 两表）各自的 updatedAt */
  targetUpdatedAtMap: Record<string, string> | null;
  /** 文件型目标的当前 mtimeMs（monitor 回滚的乐观并发基准） */
  targetMtimeMs: number | null;
}

/** 目标行当前版本：供回滚请求带上 CAS 基准（找不到则 null） */
async function readTargetMeta(targetType: string, targetId: string): Promise<TargetMeta> {
  const meta: TargetMeta = { targetUpdatedAt: null, targetUpdatedAtMap: null, targetMtimeMs: null };
  try {
    if (targetType === "user") {
      const row = await prisma.user.findUnique({ where: { uid: targetId }, select: { updatedAt: true } });
      meta.targetUpdatedAt = row?.updatedAt?.toISOString() ?? null;
    } else if (targetType === "credits") {
      const row = await prisma.creditsAccount.findUnique({
        where: { uid: targetId },
        select: { updatedAt: true },
      });
      meta.targetUpdatedAt = row?.updatedAt?.toISOString() ?? null;
    } else if (targetType === "tradingParams") {
      const [params, profile] = await Promise.all([
        prisma.tradingParams.findUnique({ where: { uid: targetId }, select: { updatedAt: true } }),
        prisma.userProfile.findUnique({ where: { uid: targetId }, select: { updatedAt: true } }),
      ]);
      meta.targetUpdatedAt = params?.updatedAt?.toISOString() ?? null;
      meta.targetUpdatedAtMap = {
        params: params?.updatedAt?.toISOString() ?? "",
        profile: profile?.updatedAt?.toISOString() ?? "",
      };
    } else if (targetType === "strategy") {
      const row = await prisma.strategy.findUnique({ where: { id: targetId }, select: { updatedAt: true } });
      meta.targetUpdatedAt = row?.updatedAt?.toISOString() ?? null;
    } else if (targetType === "task") {
      const row = await prisma.strategyTask.findUnique({
        where: { id: targetId },
        select: { updatedAt: true },
      });
      meta.targetUpdatedAt = row?.updatedAt?.toISOString() ?? null;
    } else if (targetType === "channel") {
      const row = await prisma.channelConfig.findUnique({
        where: { id: targetId },
        select: { updatedAt: true },
      });
      meta.targetUpdatedAt = row?.updatedAt?.toISOString() ?? null;
    } else if (targetType === "api-config") {
      const row = await prisma.apiConfig.findUnique({ where: { id: targetId }, select: { updatedAt: true } });
      meta.targetUpdatedAt = row?.updatedAt?.toISOString() ?? null;
    } else if (targetType === "order") {
      const row = await prisma.order.findUnique({ where: { id: targetId }, select: { updatedAt: true } });
      meta.targetUpdatedAt = row?.updatedAt?.toISOString() ?? null;
    } else if (targetType === "system-config") {
      if (isAdminFileKey(targetId)) {
        const snapshot = await readConfigFile(targetId);
        meta.targetMtimeMs = snapshot.mtimeMs;
      }
    }
  } catch {
    return meta;
  }
  return meta;
}
