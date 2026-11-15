import { NextResponse } from "next/server";
import { z } from "zod";
import { getAdminUserDetail } from "@/lib/admin-queries";
import { apiSuccess, apiError } from "@/lib/types/admin-api";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { USER_ROLE_ACTION } from "@/lib/admin/constants";
import { prisma } from "@/lib/prisma";
import { beginWrite, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertCasHit, parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: { uid: string } },
) {
  const denied = await requireAdminOrResponse();
  if (denied) return denied;
  const user = await getAdminUserDetail(params.uid);
  if (!user) {
    return NextResponse.json(apiError("用户不存在"), { status: 404 });
  }
  return NextResponse.json(apiSuccess(user));
}

// ============================================================================
// PATCH /api/admin/users/[uid] —— 角色调整（L0，SPEC-7 §6.1 / D2）
// ----------------------------------------------------------------------------
// 单管理员可操作（D2）：FREE ↔ PRO ↔ ADMIN；条件更新带角色白名单，0 行即 409。
// 角色变更额外写一条结构化告警日志（不阻塞主流程），便于事后追溯提权行为。
// ============================================================================

const SAFE_FIELDS = ["uid", "role"] as const;
const ALL_ROLES = ["FREE", "PRO", "ADMIN"] as const;

const patchSchema = z.object({
  role: z.enum(ALL_ROLES),
  expectedUpdatedAt: z.union([z.string(), z.number()]),
  reason: z.string().max(500).optional(),
});

export async function PATCH(request: Request, { params }: { params: { uid: string } }) {
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

    const replay = await findReplay(ctx.idempotencyKey, USER_ROLE_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const target = await prisma.user.findUnique({
      where: { uid: params.uid },
      select: { uid: true, role: true, updatedAt: true },
    });
    if (!target) {
      throw new AdminError("NOT_FOUND", "用户不存在");
    }
    if (target.role === parsed.data.role) {
      throw new AdminError("RULE_BLOCKED", `用户角色已是 ${parsed.data.role}，无需变更`);
    }

    const before = projectSafe(target as unknown as Record<string, unknown>, [...SAFE_FIELDS]);
    const after = projectSafe({ uid: target.uid, role: parsed.data.role }, [...SAFE_FIELDS]);
    const diff = buildDiff(before, after);
    const reason = parsed.data.reason?.trim() || null;

    if (ctx.dryRun) {
      return apiOk(dryRunResponseData({ before, after, diff }), {
        requestId,
        message: "dryRun 校验通过（未落库）",
      });
    }

    const expected = parseExpectedUpdatedAt(parsed.data.expectedUpdatedAt);
    const op = await prisma.$transaction(async (tx) => {
      const updated = await tx.user.updateMany({
        where: { uid: params.uid, updatedAt: expected, role: { in: [...ALL_ROLES] } },
        data: { role: parsed.data.role },
      });
      assertCasHit(updated.count, "用户已被其他操作修改，请刷新后重试");

      return createOpLog(tx, {
        requestId: ctx.requestId,
        idempotencyKey: ctx.idempotencyKey,
        actorUid: ctx.actor.uid,
        actorRole: ctx.actor.role,
        level: "L0",
        action: USER_ROLE_ACTION,
        targetType: "user",
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

    // 结构化告警日志：提权/降权必须可检索（不阻塞主流程）
    console.warn(
      JSON.stringify({
        kind: "admin_role_change",
        at: new Date().toISOString(),
        actorUid: ctx.actor.uid,
        targetUid: params.uid,
        from: target.role,
        to: parsed.data.role,
        requestId: ctx.requestId,
        reason,
      }),
    );

    const finalized = await finalizeOp(op);
    return apiOk(opResponseData(finalized), {
      requestId,
      message: `用户角色已更新为 ${parsed.data.role}`,
    });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
