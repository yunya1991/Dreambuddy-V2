// ============================================================================
// POST /api/admin/trading-params/[uid]/reset-daily —— 日重置（L1，SPEC-7 §6.2）
// ----------------------------------------------------------------------------
// 语义：todayLoss=0、todayTradeCount=0、lastResetDate=今天（本地日期）。
// 同日幂等：lastResetDate 已是今天 → 返回 NOOP，不再落库、不消耗确认令牌。
// 无 BridgeSync（§6.2 标注 ❌）。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { TRADING_RESET_DAILY_ACTION } from "@/lib/admin/constants";
import { hashPayload, verifyConfirmToken } from "@/lib/admin/confirm-token";
import { prisma } from "@/lib/prisma";
import { beginWrite, payloadWithoutToken, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertCasHit, parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { assertReason, buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";

export const dynamic = "force-dynamic";

const SAFE_FIELDS = ["uid", "todayLoss", "todayTradeCount", "lastResetDate"] as const;

const schema = z.object({
  expectedUpdatedAt: z.union([z.string(), z.number()]),
  reason: z.string().max(500).optional(),
  confirmToken: z.string().optional(),
});

function todayString(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export async function POST(request: Request, { params }: { params: { uid: string } }) {
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
    const replay = await findReplay(ctx.idempotencyKey, TRADING_RESET_DAILY_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const target = await prisma.tradingParams.findUnique({
      where: { uid: params.uid },
      select: { uid: true, todayLoss: true, todayTradeCount: true, lastResetDate: true, updatedAt: true },
    });
    if (!target) {
      throw new AdminError("NOT_FOUND", "用户交易参数记录不存在");
    }

    const today = todayString();
    const before = projectSafe(target as unknown as Record<string, unknown>, [...SAFE_FIELDS]);
    if (target.lastResetDate === today) {
      return apiOk(
        {
          opId: null,
          status: "NOOP",
          before,
          after: before,
          diff: {},
          warnings: [],
          requiresRestart: false,
          simulated: true,
        },
        { requestId, message: "今日已重置（幂等跳过）" },
      );
    }

    const after = projectSafe(
      { uid: params.uid, todayLoss: 0, todayTradeCount: 0, lastResetDate: today },
      [...SAFE_FIELDS],
    );
    const diff = buildDiff(before, after);

    if (ctx.dryRun) {
      return apiOk(dryRunResponseData({ before, after, diff }), {
        requestId,
        message: "dryRun 校验通过（未落库）",
      });
    }

    let nonce: string | null = null;
    const token = parsed.data.confirmToken;
    if (!token) {
      throw new AdminError("VALIDATION_FAILED", "该操作需要二次确认，请先获取确认令牌");
    }
    nonce = verifyConfirmToken(token, {
      uid: ctx.actor.uid,
      action: TRADING_RESET_DAILY_ACTION,
      targetId: params.uid,
      payloadHash: hashPayload(payloadWithoutToken(body)),
    }).nonce;

    const expected = parseExpectedUpdatedAt(parsed.data.expectedUpdatedAt);
    const op = await prisma.$transaction(async (tx) => {
      const updated = await tx.tradingParams.updateMany({
        where: { uid: params.uid, updatedAt: expected, lastResetDate: { not: today } },
        data: { todayLoss: 0, todayTradeCount: 0, lastResetDate: today },
      });
      assertCasHit(updated.count, "交易参数已被修改或今日已重置，请刷新后重试");

      return createOpLog(tx, {
        requestId: ctx.requestId,
        idempotencyKey: ctx.idempotencyKey,
        nonce,
        actorUid: ctx.actor.uid,
        actorRole: ctx.actor.role,
        level: "L1",
        action: TRADING_RESET_DAILY_ACTION,
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

    const finalized = await finalizeOp(op);
    return apiOk(opResponseData(finalized), { requestId, message: "交易日数据已重置" });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
