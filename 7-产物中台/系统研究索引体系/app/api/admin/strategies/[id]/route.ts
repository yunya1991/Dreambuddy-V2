// ============================================================================
// PATCH /api/admin/strategies/[id] —— 策略状态（L1，SPEC-7 §6.2）
// ----------------------------------------------------------------------------
// 状态机白名单见 state-machines.ts；CAS 走 updatedAt。
// BridgeSync（启用/暂停）属于非交易类：失败不回滚，转 APPLIED_WITH_WARNINGS，
// 由 /api/admin/jobs/audit-flush 内的 bridge 补偿任务重试。
// ============================================================================

import { NextResponse } from "next/server";
import { z } from "zod";
import { getAdminStrategyDetail } from "@/lib/admin-queries";
import { apiSuccess, apiError } from "@/lib/types/admin-api";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { STRATEGY_STATUS_ACTION } from "@/lib/admin/constants";
import { hashPayload, verifyConfirmToken } from "@/lib/admin/confirm-token";
import { prisma } from "@/lib/prisma";
import { beginWrite, payloadWithoutToken, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertCasHit, parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { assertReason, buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog, updateOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";
import { assertStrategyTransition } from "@/lib/admin/write/state-machines";
import { bridgeFailureWarning, syncStrategyStatus } from "@/lib/admin/write/bridge";

export const dynamic = "force-dynamic";

const STRATEGY_STATUSES = ["DRAFT", "APPROVED", "APPLIED", "PAUSED", "EXPIRED"] as const;
const SAFE_FIELDS = ["id", "status"] as const;

const patchSchema = z.object({
  status: z.enum(STRATEGY_STATUSES),
  expectedUpdatedAt: z.union([z.string(), z.number()]),
  reason: z.string().max(500).optional(),
  confirmToken: z.string().optional(),
});

export async function GET(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const denied = await requireAdminOrResponse();
  if (denied) return denied;
  const strategy = await getAdminStrategyDetail(params.id);
  if (!strategy) {
    return NextResponse.json(apiError("策略不存在"), { status: 404 });
  }
  return NextResponse.json(apiSuccess(strategy));
}

export async function PATCH(request: Request, { params }: { params: { id: string } }) {
  let requestId = "";
  try {
    const ctx = await beginWrite(request);
    requestId = ctx.requestId;

    const body = await readJsonBody(request);
    const parsed = patchSchema.safeParse(body);
    if (!parsed.success) {
      throw new AdminError("VALIDATION_FAILED", "参数校验失败", {
        issues: parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
      });
    }

    const reason = assertReason(parsed.data.reason, "L1");
    const replay = await findReplay(ctx.idempotencyKey, STRATEGY_STATUS_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const target = await prisma.strategy.findUnique({
      where: { id: params.id },
      select: { id: true, uid: true, status: true, updatedAt: true },
    });
    if (!target) {
      throw new AdminError("NOT_FOUND", "策略不存在");
    }
    assertStrategyTransition(target.status, parsed.data.status);

    const before = projectSafe(target as unknown as Record<string, unknown>, [...SAFE_FIELDS]);
    const after = projectSafe({ id: target.id, status: parsed.data.status }, [...SAFE_FIELDS]);
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
      action: STRATEGY_STATUS_ACTION,
      targetId: params.id,
      payloadHash: hashPayload(payloadWithoutToken(body)),
    }).nonce;

    const expected = parseExpectedUpdatedAt(parsed.data.expectedUpdatedAt);
    const op = await prisma.$transaction(async (tx) => {
      const updated = await tx.strategy.updateMany({
        where: { id: params.id, updatedAt: expected, status: target.status },
        data: { status: parsed.data.status },
      });
      assertCasHit(updated.count, "策略已被修改，请刷新后重试");

      return createOpLog(tx, {
        requestId: ctx.requestId,
        idempotencyKey: ctx.idempotencyKey,
        nonce,
        actorUid: ctx.actor.uid,
        actorRole: ctx.actor.role,
        level: "L1",
        action: STRATEGY_STATUS_ACTION,
        targetType: "strategy",
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

    const bridge = await syncStrategyStatus(params.id, parsed.data.status);
    const pending = bridge.ok ? op : await updateOpLog(prisma, op.id, {
      status: "APPLIED_WITH_WARNINGS",
      warnings: [bridgeFailureWarning("bridge_sync_failed", bridge)],
    });
    const finalized = await finalizeOp(pending);
    return apiOk(opResponseData(finalized), {
      requestId,
      message: bridge.ok
        ? "策略状态已更新并下发"
        : "策略状态已更新；下游同步待补偿（bridge 失败已登记）",
    });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
