// ============================================================================
// PATCH /api/admin/trading-params/[uid] —— 交易总开关 / 交易状态（L1，SPEC-7 §6.2）
// ----------------------------------------------------------------------------
// · 参数面：UserProfile.isTradingEnabled；状态面：TradingParams.status
// · 两级 CAS：两个表各自带 expectedUpdatedAt，任一 0 行即 409
// · 原因 ≥10 字 + 一次性 confirmToken（L1）
// · BridgeSync：交易类动作，写库后 27 config 必须同步成功；
//   失败 → 事务外补偿回滚到 before + opLog=FAILED + 502 BRIDGE_SYNC_FAILED
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { TRADING_PARAMS_ACTION } from "@/lib/admin/constants";
import { hashPayload, verifyConfirmToken } from "@/lib/admin/confirm-token";
import { prisma } from "@/lib/prisma";
import { beginWrite, payloadWithoutToken, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertCasHit, parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { assertReason, buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog, updateOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";
import { assertTradingStatusTarget } from "@/lib/admin/write/state-machines";
import { bridgeFailureWarning, syncTradingConfig } from "@/lib/admin/write/bridge";

export const dynamic = "force-dynamic";

const SAFE_FIELDS = ["uid", "isTradingEnabled", "status"] as const;

const schema = z
  .object({
    isTradingEnabled: z.boolean().optional(),
    status: z.enum(["ACTIVE", "PAUSED", "FROZEN"]).optional(),
    expectedProfileUpdatedAt: z.union([z.string(), z.number()]).optional(),
    expectedParamsUpdatedAt: z.union([z.string(), z.number()]).optional(),
    reason: z.string().max(500).optional(),
    confirmToken: z.string().optional(),
  })
  .refine(
    (data) => data.isTradingEnabled !== undefined || data.status !== undefined,
    "isTradingEnabled 与 status 至少提供一个",
  );

export async function PATCH(request: Request, { params }: { params: { uid: string } }) {
  let requestId = "";
  try {
    const ctx = await beginWrite(request);
    requestId = ctx.requestId;

    const body = await readJsonBody(request);
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      throw new AdminError("VALIDATION_FAILED", "参数校验失败", {
        issues: parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
      });
    }

    const reason = assertReason(parsed.data.reason, "L1");
    const replay = await findReplay(ctx.idempotencyKey, TRADING_PARAMS_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const [profile, tradingParams] = await Promise.all([
      prisma.userProfile.findUnique({
        where: { uid: params.uid },
        select: { uid: true, isTradingEnabled: true, updatedAt: true },
      }),
      prisma.tradingParams.findUnique({
        where: { uid: params.uid },
        select: { uid: true, status: true, updatedAt: true },
      }),
    ]);
    if (!profile) {
      throw new AdminError("NOT_FOUND", "用户交易档案不存在");
    }
    if (!tradingParams) {
      throw new AdminError("NOT_FOUND", "用户交易参数记录不存在");
    }

    if (parsed.data.isTradingEnabled !== undefined) {
      if (parsed.data.expectedProfileUpdatedAt === undefined) {
        throw new AdminError("VALIDATION_FAILED", "缺少 expectedProfileUpdatedAt（并发控制必填）");
      }
    }
    if (parsed.data.status !== undefined) {
      assertTradingStatusTarget(parsed.data.status);
      if (parsed.data.expectedParamsUpdatedAt === undefined) {
        throw new AdminError("VALIDATION_FAILED", "缺少 expectedParamsUpdatedAt（并发控制必填）");
      }
    }

    const before = projectSafe(
      { uid: params.uid, isTradingEnabled: profile.isTradingEnabled, status: tradingParams.status },
      [...SAFE_FIELDS],
    );
    const after = projectSafe(
      {
        uid: params.uid,
        isTradingEnabled: parsed.data.isTradingEnabled ?? profile.isTradingEnabled,
        status: parsed.data.status ?? tradingParams.status,
      },
      [...SAFE_FIELDS],
    );
    const diff = buildDiff(before, after);
    if (Object.keys(diff).length === 0) {
      throw new AdminError("RULE_BLOCKED", "目标值与当前值一致，无需变更");
    }

    let nonce: string | null = null;
    if (!ctx.dryRun) {
      const token = parsed.data.confirmToken;
      if (!token) {
        throw new AdminError("VALIDATION_FAILED", "该操作需要二次确认，请先获取确认令牌");
      }
      nonce = verifyConfirmToken(token, {
        uid: ctx.actor.uid,
        action: TRADING_PARAMS_ACTION,
        targetId: params.uid,
        payloadHash: hashPayload(payloadWithoutToken(body)),
      }).nonce;
    }

    if (ctx.dryRun) {
      return apiOk(dryRunResponseData({ before, after, diff }), {
        requestId,
        message: "dryRun 校验通过（未落库）",
      });
    }

    const expectedProfile = parsed.data.expectedProfileUpdatedAt
      ? parseExpectedUpdatedAt(parsed.data.expectedProfileUpdatedAt)
      : null;
    const expectedParams = parsed.data.expectedParamsUpdatedAt
      ? parseExpectedUpdatedAt(parsed.data.expectedParamsUpdatedAt)
      : null;

    const op = await prisma.$transaction(async (tx) => {
      if (parsed.data.isTradingEnabled !== undefined && expectedProfile) {
        const updated = await tx.userProfile.updateMany({
          where: { uid: params.uid, updatedAt: expectedProfile },
          data: { isTradingEnabled: parsed.data.isTradingEnabled },
        });
        assertCasHit(updated.count, "交易档案已被修改，请刷新后重试");
      }
      if (parsed.data.status !== undefined && expectedParams) {
        const updated = await tx.tradingParams.updateMany({
          where: { uid: params.uid, updatedAt: expectedParams },
          data: { status: parsed.data.status },
        });
        assertCasHit(updated.count, "交易参数已被修改，请刷新后重试");
      }

      return createOpLog(tx, {
        requestId: ctx.requestId,
        idempotencyKey: ctx.idempotencyKey,
        nonce,
        actorUid: ctx.actor.uid,
        actorRole: ctx.actor.role,
        level: "L1",
        action: TRADING_PARAMS_ACTION,
        targetType: "tradingParams",
        targetId: params.uid,
        reason,
        beforeData: before,
        afterData: after,
        diff,
        status: "PENDING_AUDIT",
        ip: ctx.ip,
        userAgent: ctx.userAgent,
      });
    });

    // 交易类下发：失败必须整体回滚（SPEC §4.1 失败语义矩阵）
    const bridge = await syncTradingConfig({
      ...(parsed.data.isTradingEnabled !== undefined
        ? { liveTradingEnabled: parsed.data.isTradingEnabled }
        : {}),
      ...(parsed.data.status !== undefined ? { status: parsed.data.status } : {}),
    });
    if (!bridge.ok) {
      await revertTradingChange(params.uid, parsed.data, before);
      await updateOpLog(prisma, op.id, {
        status: "FAILED",
        errorCode: "BRIDGE_SYNC_FAILED",
        errorMessage: bridge.error || "27 治理配置同步失败",
        warnings: [{ ...bridgeFailureWarning("bridge_sync_failed", bridge), reverted: true }],
      });
      throw new AdminError(
        "BRIDGE_SYNC_FAILED",
        `27 治理配置同步失败，已回滚本次变更：${bridge.error || "unknown"}`,
        { opId: op.id, traceId: bridge.traceId },
      );
    }

    const finalized = await finalizeOp(op);
    return apiOk(opResponseData(finalized), { requestId, message: "交易参数已更新并下发" });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}

/**
 * Bridge 失败后的补偿回滚：按「刚写入后的 updatedAt」做一次条件回写。
 * 回写失败只记日志（已无法保证一致性），由人工在审计页核对。
 */
async function revertTradingChange(
  uid: string,
  patch: { isTradingEnabled?: boolean; status?: string },
  before: Record<string, unknown> | null,
): Promise<void> {
  try {
    await prisma.$transaction(async (tx) => {
      if (patch.isTradingEnabled !== undefined) {
        const fresh = await tx.userProfile.findUnique({
          where: { uid },
          select: { updatedAt: true },
        });
        if (fresh) {
          await tx.userProfile.updateMany({
            where: { uid, updatedAt: fresh.updatedAt },
            data: { isTradingEnabled: Boolean(before?.isTradingEnabled) },
          });
        }
      }
      if (patch.status !== undefined) {
        const fresh = await tx.tradingParams.findUnique({
          where: { uid },
          select: { updatedAt: true },
        });
        if (fresh) {
          await tx.tradingParams.updateMany({
            where: { uid, updatedAt: fresh.updatedAt },
            data: { status: String(before?.status ?? "ACTIVE") as "ACTIVE" | "PAUSED" | "FROZEN" | "LOCKED" },
          });
        }
      }
    });
  } catch (error) {
    console.error(
      `[admin-bridge-rollback] uid=${uid} 补偿回滚失败，需人工核对`,
      error instanceof Error ? error.message : String(error),
    );
  }
}
