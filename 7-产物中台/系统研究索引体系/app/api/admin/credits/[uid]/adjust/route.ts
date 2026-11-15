// ============================================================================
// POST /api/admin/credits/[uid]/adjust —— 积分调账（SPEC-7 §6.3 / §8.4）
// ----------------------------------------------------------------------------
// 分档（D3 定稿）：|delta| ≤ 500 → L0；501 ~ 5000 → L1（二次确认 + reason≥10字）；
//                > 5000 → RULE_BLOCKED。单用户日累计 ≤ 20000；余额不得为负。
// 并发：updateMany 条件包含 balance ≥ -delta，0 行即区分「余额不足」与「CAS 过期」。
// 事务：账户变更 + 流水 + opLog(PENDING_AUDIT) 原子提交。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import {
  CREDITS_ADJUST_ACTION,
  CREDITS_ADJUST_CATEGORY,
  CREDITS_ADJUST_DESCRIPTION_PREFIX,
} from "@/lib/admin/constants";
import { hashPayload, verifyConfirmToken } from "@/lib/admin/confirm-token";
import { prisma } from "@/lib/prisma";
import {
  beginWrite,
  payloadWithoutToken,
  readJsonBody,
} from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { assertReason, buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog, type DbClient } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";
import {
  assertBalanceSufficient,
  assertCreditsDeltaAllowed,
  assertDailyCap,
  buildAdjustDescription,
  creditsAdjustMagnitude,
  resolveCreditsAdjustLevel,
} from "@/lib/admin/write/credits-rules";

export const dynamic = "force-dynamic";

const SAFE_FIELDS = ["uid", "balance", "totalEarned", "totalSpent"] as const;

const schema = z.object({
  delta: z.number(),
  reason: z.string().max(500).optional(),
  expectedUpdatedAt: z.union([z.string(), z.number()]),
  confirmToken: z.string().optional(),
});

function startOfToday(): Date {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return now;
}

/** 当日管理台调账累计绝对值（按流水描述前缀归集） */
async function sumTodayAdjustments(db: DbClient, uid: string): Promise<number> {
  const rows = await db.creditsTransaction.findMany({
    where: {
      uid,
      category: CREDITS_ADJUST_CATEGORY,
      description: { startsWith: CREDITS_ADJUST_DESCRIPTION_PREFIX },
      createdAt: { gte: startOfToday() },
    },
    select: { amount: true },
  });
  return rows.reduce((sum, row) => sum + Math.abs(row.amount), 0);
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

    const delta = assertCreditsDeltaAllowed(parsed.data.delta);
    const level = resolveCreditsAdjustLevel(delta);
    const reason = assertReason(parsed.data.reason, level);

    const replay = await findReplay(ctx.idempotencyKey, CREDITS_ADJUST_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const account = await prisma.creditsAccount.findUnique({
      where: { uid: params.uid },
      select: {
        uid: true,
        balance: true,
        totalEarned: true,
        totalSpent: true,
        updatedAt: true,
      },
    });
    if (!account) {
      throw new AdminError("NOT_FOUND", "积分账户不存在");
    }

    const expected = parseExpectedUpdatedAt(parsed.data.expectedUpdatedAt);

    // L1 必须携带一次性确认令牌；dryRun 只做预演，不消耗 nonce
    let nonce: string | null = null;
    if (level === "L1" && !ctx.dryRun) {
      const token = parsed.data.confirmToken;
      if (!token) {
        throw new AdminError("VALIDATION_FAILED", "该额度需要二次确认，请先获取确认令牌");
      }
      nonce = verifyConfirmToken(token, {
        uid: ctx.actor.uid,
        action: CREDITS_ADJUST_ACTION,
        targetId: params.uid,
        payloadHash: hashPayload(payloadWithoutToken(body)),
      }).nonce;
    }

    const before = projectSafe(account as unknown as Record<string, unknown>, [...SAFE_FIELDS]);
    const after = {
      uid: account.uid,
      balance: account.balance + delta,
      totalEarned: account.totalEarned + Math.max(delta, 0),
      totalSpent: account.totalSpent + Math.max(-delta, 0),
      delta,
    };
    const safeAfter = projectSafe(after as unknown as Record<string, unknown>, [
      ...SAFE_FIELDS,
      "delta",
    ]);
    const diff = buildDiff(before, safeAfter);

    // dryRun：完整校验（日累计 + 余额），零落库
    if (ctx.dryRun) {
      const used = await sumTodayAdjustments(prisma, params.uid);
      assertDailyCap(used, delta);
      assertBalanceSufficient(account.balance, delta);
      return apiOk(dryRunResponseData({ before, after: safeAfter, diff }), {
        requestId,
        message: `dryRun 通过（级别 ${level}，未落库）`,
      });
    }

    const op = await prisma.$transaction(async (tx) => {
      // 日累计在事务内复查，缩小并发窗口
      const used = await sumTodayAdjustments(tx, params.uid);
      assertDailyCap(used, delta);

      const updated = await tx.creditsAccount.updateMany({
        where: {
          uid: params.uid,
          updatedAt: expected,
          balance: { gte: -delta },
        },
        data: {
          balance: { increment: delta },
          ...(delta > 0 ? { totalEarned: { increment: delta } } : {}),
          ...(delta < 0 ? { totalSpent: { increment: -delta } } : {}),
        },
      });
      if (updated.count === 0) {
        // 条件更新 0 行：区分余额不足与并发过期
        const current = await tx.creditsAccount.findUnique({
          where: { uid: params.uid },
          select: { balance: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "积分账户不存在");
        }
        assertBalanceSufficient(current.balance, delta);
        throw new AdminError("CONFLICT_STALE", "账户已被其他操作修改，请刷新后重试");
      }

      const fresh = await tx.creditsAccount.findUnique({
        where: { uid: params.uid },
        select: { balance: true },
      });

      await tx.creditsTransaction.create({
        data: {
          uid: params.uid,
          type: delta > 0 ? "EARN" : "SPEND",
          category: CREDITS_ADJUST_CATEGORY,
          amount: creditsAdjustMagnitude(delta),
          balanceAfter: fresh?.balance ?? account.balance + delta,
          description: buildAdjustDescription(CREDITS_ADJUST_DESCRIPTION_PREFIX, reason),
        },
      });

      try {
        return await createOpLog(tx, {
          requestId: ctx.requestId,
          idempotencyKey: ctx.idempotencyKey,
          nonce,
          actorUid: ctx.actor.uid,
          actorRole: ctx.actor.role,
          level,
          action: CREDITS_ADJUST_ACTION,
          targetType: "credits",
          targetId: params.uid,
          reason,
          beforeData: before,
          afterData: safeAfter,
          diff,
          status: "PENDING_AUDIT",
          ip: ctx.ip,
          userAgent: ctx.userAgent,
        });
      } catch (error) {
        // nonce 唯一索引冲突 = 确认令牌被重放
        if ((error as { code?: string }).code === "P2002") {
          throw new AdminError("VALIDATION_FAILED", "确认令牌已被使用，请重新确认");
        }
        throw error;
      }
    });

    const finalized = await finalizeOp(op);
    return apiOk(opResponseData(finalized), {
      requestId,
      message: `调账成功（${level}）`,
    });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
