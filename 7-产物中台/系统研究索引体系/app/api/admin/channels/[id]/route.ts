// ============================================================================
// PATCH /api/admin/channels/[id] —— 渠道启停 / 推送规则（L0，SPEC-7 §6.1）
// ----------------------------------------------------------------------------
// 可写：isOnline / format / silentStart / silentEnd / pushRules。
// 密文相关字段（encryptedData/iv/authTag）永不进入 before/after 与响应；
// pushRules 入审计前递归掩码，防止规则里夹带 token。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { CHANNEL_UPDATE_ACTION } from "@/lib/admin/constants";
import { prisma } from "@/lib/prisma";
import { beginWrite, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertCasHit, parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { buildDiff, maskDeep, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";

export const dynamic = "force-dynamic";

const SAFE_FIELDS = ["id", "isOnline", "format", "silentStart", "silentEnd", "pushRules"] as const;
const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

const schema = z
  .object({
    isOnline: z.boolean().optional(),
    format: z.enum(["CONCISE", "DETAILED"]).optional(),
    silentStart: z.string().regex(HHMM, "silentStart 需为 HH:MM").nullable().optional(),
    silentEnd: z.string().regex(HHMM, "silentEnd 需为 HH:MM").nullable().optional(),
    pushRules: z.record(z.string(), z.unknown()).optional(),
    expectedUpdatedAt: z.union([z.string(), z.number()]),
    reason: z.string().max(500).optional(),
  })
  .refine(
    (data) =>
      data.isOnline !== undefined ||
      data.format !== undefined ||
      data.silentStart !== undefined ||
      data.silentEnd !== undefined ||
      data.pushRules !== undefined,
    "至少提供一个可写字段",
  );

function safeChannel(source: Record<string, unknown>): Record<string, unknown> | null {
  const projected = projectSafe(source, [...SAFE_FIELDS]);
  if (projected && "pushRules" in projected) {
    projected.pushRules = maskDeep(projected.pushRules);
  }
  return projected;
}

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

    const replay = await findReplay(ctx.idempotencyKey, CHANNEL_UPDATE_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const target = await prisma.channelConfig.findUnique({
      where: { id: params.id },
      select: {
        id: true,
        isOnline: true,
        format: true,
        silentStart: true,
        silentEnd: true,
        pushRules: true,
        updatedAt: true,
      },
    });
    if (!target) {
      throw new AdminError("NOT_FOUND", "渠道不存在");
    }

    const data: Record<string, unknown> = {};
    if (parsed.data.isOnline !== undefined) data.isOnline = parsed.data.isOnline;
    if (parsed.data.format !== undefined) data.format = parsed.data.format;
    if (parsed.data.silentStart !== undefined) data.silentStart = parsed.data.silentStart;
    if (parsed.data.silentEnd !== undefined) data.silentEnd = parsed.data.silentEnd;
    if (parsed.data.pushRules !== undefined) data.pushRules = parsed.data.pushRules;

    const before = safeChannel(target as unknown as Record<string, unknown>);
    const after = safeChannel({
      ...(target as unknown as Record<string, unknown>),
      ...data,
    });
    const diff = buildDiff(before, after);
    if (Object.keys(diff).length === 0) {
      throw new AdminError("RULE_BLOCKED", "目标值与当前值一致，无需变更");
    }

    if (ctx.dryRun) {
      return apiOk(dryRunResponseData({ before, after, diff }), {
        requestId,
        message: "dryRun 校验通过（未落库）",
      });
    }

    const expected = parseExpectedUpdatedAt(parsed.data.expectedUpdatedAt);
    const op = await prisma.$transaction(async (tx) => {
      const updated = await tx.channelConfig.updateMany({
        where: { id: params.id, updatedAt: expected },
        data: data as never,
      });
      assertCasHit(updated.count, "渠道配置已被修改，请刷新后重试");

      return createOpLog(tx, {
        requestId: ctx.requestId,
        idempotencyKey: ctx.idempotencyKey,
        nonce: null,
        actorUid: ctx.actor.uid,
        actorRole: ctx.actor.role,
        level: "L0",
        action: CHANNEL_UPDATE_ACTION,
        targetType: "channel",
        targetId: params.id,
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
    return apiOk(opResponseData(finalized), { requestId, message: "渠道配置已更新" });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
