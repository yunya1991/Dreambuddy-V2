// ============================================================================
// PATCH /api/admin/api-configs/[id] —— API 校验状态 / 标签（L0，SPEC-7 §6.1）
// ----------------------------------------------------------------------------
// 可写：isVerified / lastVerifiedAt / label。
// encryptedData / iv / authTag / keyHint 永不读写（密钥明文零接触）。
// label 受 @@unique([uid, category, provider, label]) 约束，冲突转 RULE_BLOCKED。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { API_CONFIG_UPDATE_ACTION } from "@/lib/admin/constants";
import { prisma } from "@/lib/prisma";
import { beginWrite, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertCasHit, parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { createOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";

export const dynamic = "force-dynamic";

const SAFE_FIELDS = ["id", "provider", "label", "isVerified", "lastVerifiedAt", "environment"] as const;

const schema = z
  .object({
    isVerified: z.boolean().optional(),
    lastVerifiedAt: z.union([z.string(), z.number()]).nullable().optional(),
    label: z.string().trim().min(1).max(60).optional(),
    expectedUpdatedAt: z.union([z.string(), z.number()]),
    reason: z.string().max(500).optional(),
  })
  .refine(
    (data) =>
      data.isVerified !== undefined ||
      data.lastVerifiedAt !== undefined ||
      data.label !== undefined,
    "至少提供一个可写字段",
  );

function isUniqueViolation(error: unknown): boolean {
  return Boolean(
    error &&
      typeof error === "object" &&
      "code" in error &&
      (error as { code?: string }).code === "P2002",
  );
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

    const replay = await findReplay(ctx.idempotencyKey, API_CONFIG_UPDATE_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const target = await prisma.apiConfig.findUnique({
      where: { id: params.id },
      select: {
        id: true,
        provider: true,
        label: true,
        isVerified: true,
        lastVerifiedAt: true,
        environment: true,
        updatedAt: true,
      },
    });
    if (!target) {
      throw new AdminError("NOT_FOUND", "API 配置不存在");
    }

    const data: Record<string, unknown> = {};
    if (parsed.data.isVerified !== undefined) data.isVerified = parsed.data.isVerified;
    if (parsed.data.label !== undefined) data.label = parsed.data.label;
    if (parsed.data.lastVerifiedAt !== undefined) {
      data.lastVerifiedAt =
        parsed.data.lastVerifiedAt === null
          ? null
          : new Date(
              typeof parsed.data.lastVerifiedAt === "number"
                ? parsed.data.lastVerifiedAt
                : Date.parse(parsed.data.lastVerifiedAt),
            );
      if (data.lastVerifiedAt instanceof Date && Number.isNaN(data.lastVerifiedAt.getTime())) {
        throw new AdminError("VALIDATION_FAILED", "lastVerifiedAt 不是合法时间");
      }
    }

    const before = projectSafe(target as unknown as Record<string, unknown>, [...SAFE_FIELDS]);
    const after = projectSafe(
      { ...(target as unknown as Record<string, unknown>), ...data },
      [...SAFE_FIELDS],
    );
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
      const updated = await tx.apiConfig.updateMany({
        where: { id: params.id, updatedAt: expected },
        data: data as never,
      });
      assertCasHit(updated.count, "API 配置已被修改，请刷新后重试");

      return createOpLog(tx, {
        requestId: ctx.requestId,
        idempotencyKey: ctx.idempotencyKey,
        nonce: null,
        actorUid: ctx.actor.uid,
        actorRole: ctx.actor.role,
        level: "L0",
        action: API_CONFIG_UPDATE_ACTION,
        targetType: "api-config",
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
    return apiOk(opResponseData(finalized), { requestId, message: "API 配置已更新" });
  } catch (error) {
    if (isUniqueViolation(error)) {
      return apiFail(
        new AdminError("RULE_BLOCKED", "同一类别/提供商下已存在同名标签"),
        requestId,
      );
    }
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
