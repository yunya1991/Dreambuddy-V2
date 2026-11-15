// ============================================================================
// PATCH /api/admin/orders/[id] —— 订单修正（L1，SPEC-7 §6.2）
// ----------------------------------------------------------------------------
// 仅两条迁移：PENDING → CANCELLED、PAID → COMPLETED（CAS：updatedAt + 当前状态）。
// 不做金额/积分改动，不触发支付网关。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { ORDER_UPDATE_ACTION } from "@/lib/admin/constants";
import { hashPayload, verifyConfirmToken } from "@/lib/admin/confirm-token";
import { prisma } from "@/lib/prisma";
import { beginWrite, payloadWithoutToken, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertCasHit, parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { assertReason, buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";
import { assertOrderTransition } from "@/lib/admin/write/state-machines";

export const dynamic = "force-dynamic";

const SAFE_FIELDS = ["id", "status", "amount", "credits"] as const;

const schema = z.object({
  status: z.enum(["CANCELLED", "COMPLETED"]),
  expectedUpdatedAt: z.union([z.string(), z.number()]),
  reason: z.string().max(500).optional(),
  confirmToken: z.string().optional(),
});

export async function PATCH(request: Request, { params }: { params: { id: string } }) {
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
    const replay = await findReplay(ctx.idempotencyKey, ORDER_UPDATE_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const target = await prisma.order.findUnique({
      where: { id: params.id },
      select: { id: true, status: true, amount: true, credits: true, updatedAt: true },
    });
    if (!target) {
      throw new AdminError("NOT_FOUND", "订单不存在");
    }
    assertOrderTransition(target.status, parsed.data.status);

    const before = projectSafe(target as unknown as Record<string, unknown>, [...SAFE_FIELDS]);
    const after = projectSafe({ ...target, status: parsed.data.status }, [...SAFE_FIELDS]);
    const diff = buildDiff(before, after);

    if (ctx.dryRun) {
      return apiOk(dryRunResponseData({ before, after, diff }), {
        requestId,
        message: "dryRun 校验通过（未落库）",
      });
    }

    const token = parsed.data.confirmToken;
    if (!token) {
      throw new AdminError("VALIDATION_FAILED", "该操作需要二次确认，请先获取确认令牌");
    }
    const nonce = verifyConfirmToken(token, {
      uid: ctx.actor.uid,
      action: ORDER_UPDATE_ACTION,
      targetId: params.id,
      payloadHash: hashPayload(payloadWithoutToken(body)),
    }).nonce;

    const expected = parseExpectedUpdatedAt(parsed.data.expectedUpdatedAt);
    const now = new Date();
    const op = await prisma.$transaction(async (tx) => {
      const updated = await tx.order.updateMany({
        where: { id: params.id, updatedAt: expected, status: target.status },
        data: {
          status: parsed.data.status,
          ...(parsed.data.status === "COMPLETED" ? { completedAt: now } : {}),
        },
      });
      assertCasHit(updated.count, "订单状态已变化，请刷新后重试");

      return createOpLog(tx, {
        requestId: ctx.requestId,
        idempotencyKey: ctx.idempotencyKey,
        nonce,
        actorUid: ctx.actor.uid,
        actorRole: ctx.actor.role,
        level: "L1",
        action: ORDER_UPDATE_ACTION,
        targetType: "order",
        targetId: params.id,
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
    return apiOk(opResponseData(finalized), { requestId, message: `订单已置为 ${parsed.data.status}` });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
