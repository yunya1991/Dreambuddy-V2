// ============================================================================
// POST /api/admin/users/[uid]/unlock —— 解锁用户（L0，SPEC-7 §6.1 / §8.3）
// ----------------------------------------------------------------------------
// 语义：lockedUntil=null、loginAttempts=0，条件更新（CAS on updatedAt）。
// 未锁定用户直接拒绝（RULE_BLOCKED），避免制造无意义审计。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { USER_UNLOCK_ACTION } from "@/lib/admin/constants";
import { prisma } from "@/lib/prisma";
import { beginWrite, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { parseExpectedUpdatedAt, assertCasHit } from "@/lib/admin/write/cas";
import { buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";

export const dynamic = "force-dynamic";

const SAFE_FIELDS = ["uid", "lockedUntil", "loginAttempts"] as const;

const schema = z.object({
  expectedUpdatedAt: z.union([z.string(), z.number()]),
  reason: z.string().max(500).optional(),
});

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

    const replay = await findReplay(ctx.idempotencyKey, USER_UNLOCK_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const target = await prisma.user.findUnique({
      where: { uid: params.uid },
      select: { uid: true, lockedUntil: true, loginAttempts: true, updatedAt: true },
    });
    if (!target) {
      throw new AdminError("NOT_FOUND", "用户不存在");
    }

    const before = projectSafe(target as unknown as Record<string, unknown>, [...SAFE_FIELDS]);
    const after = projectSafe(
      { uid: target.uid, lockedUntil: null, loginAttempts: 0 },
      [...SAFE_FIELDS],
    );
    const diff = buildDiff(before, after);
    if (Object.keys(diff).length === 0) {
      throw new AdminError("RULE_BLOCKED", "该用户当前未被锁定，无需解锁");
    }

    if (ctx.dryRun) {
      return apiOk(dryRunResponseData({ before, after, diff }), {
        requestId,
        message: "dryRun 校验通过（未落库）",
      });
    }

    const expected = parseExpectedUpdatedAt(parsed.data.expectedUpdatedAt);
    const op = await prisma.$transaction(async (tx) => {
      const result = await tx.user.updateMany({
        where: { uid: params.uid, updatedAt: expected },
        data: { lockedUntil: null, loginAttempts: 0 },
      });
      assertCasHit(result.count);

      return createOpLog(tx, {
        requestId: ctx.requestId,
        idempotencyKey: ctx.idempotencyKey,
        actorUid: ctx.actor.uid,
        actorRole: ctx.actor.role,
        level: "L0",
        action: USER_UNLOCK_ACTION,
        targetType: "user",
        targetId: params.uid,
        reason: parsed.data.reason?.trim() || null,
        beforeData: before,
        afterData: after,
        diff,
        status: "PENDING_AUDIT",
        ip: ctx.ip,
        userAgent: ctx.userAgent,
      });
    });

    const finalized = await finalizeOp(op);
    return apiOk(opResponseData(finalized), { requestId, message: "用户已解锁" });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
