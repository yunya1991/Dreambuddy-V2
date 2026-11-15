// ============================================================================
// /api/admin/system-config/propose —— L2 提案（SPEC-7 §6.4 / §9）
// ----------------------------------------------------------------------------
// POST ?file=capital_control|capital_allocator|trailing_stop|param_center
//   1) 先按文件规格做类型/白名单/硬下限校验（不合法 400，不落 27 也不落库）
//   2) 27 不可达 → 503（提案必须进治理系统，禁止本地直写）
//   3) 在 27 创建审批记录，opLog 落 PENDING_APPROVAL + approvalId
// 执行不在这里：见 /api/admin/system-config/apply（必须携带 approvalId）
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import {
  ADMIN_L2_FILE_KEYS,
  L2_PROPOSE_ACTION,
  type AdminL2FileKey,
} from "@/lib/admin/constants";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";
import { prisma } from "@/lib/prisma";
import { beginWrite, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { buildDiff } from "@/lib/admin/write/diff";
import { createOpLog } from "@/lib/admin/write/oplog";
import { planFilePatch, readConfigFile, type FilePatchPlan } from "@/lib/admin/write/file-config";
import { planParamCenterPatch, readParamCenterOverride } from "@/lib/admin/write/param-center";
import { checkGovernanceHealth, createApproval } from "@/lib/admin/write/governance";

export const dynamic = "force-dynamic";

const schema = z.object({
  patch: z.record(z.string(), z.unknown()),
  expectedMtimeMs: z.number().optional(),
  reason: z.string().max(500).optional(),
});

function resolveL2FileKey(request: Request): AdminL2FileKey {
  const file = new URL(request.url).searchParams.get("file") || "";
  if (!(ADMIN_L2_FILE_KEYS as readonly string[]).includes(file)) {
    throw new AdminError(
      "VALIDATION_FAILED",
      `不支持的 L2 file 参数：${file || "(空)"}（可选：${ADMIN_L2_FILE_KEYS.join(" / ")}）`,
    );
  }
  return file as AdminL2FileKey;
}

/** 按文件类型做提案校验；capital_* 仅提案不定义可写白名单，保持原样 */
async function buildProposalPlan(
  file: AdminL2FileKey,
  patch: Record<string, unknown>,
): Promise<FilePatchPlan | null> {
  if (file === "trailing_stop") {
    const snapshot = await readConfigFile("trailing_stop");
    return planFilePatch("trailing_stop", snapshot.data, patch);
  }
  if (file === "param_center") {
    const snapshot = await readParamCenterOverride();
    return planParamCenterPatch(snapshot.data, patch);
  }
  return null;
}

export async function POST(request: Request) {
  let requestId = "";
  try {
    const ctx = await beginWrite(request);
    requestId = ctx.requestId;
    const file = resolveL2FileKey(request);

    const parsed = schema.safeParse(await readJsonBody(request));
    if (!parsed.success) {
      throw new AdminError("VALIDATION_FAILED", "参数校验失败", {
        issues: parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
      });
    }

    const replay = await findReplay(ctx.idempotencyKey, L2_PROPOSE_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const plan = await buildProposalPlan(file, parsed.data.patch);
    const before = plan ? plan.before : null;
    const after = plan ? plan.after : parsed.data.patch;
    const diff = plan ? buildDiff(before ?? {}, after) : null;

    // 提案必须进 27：不可达即拒绝（不降级为本地直写）
    const health = await checkGovernanceHealth();
    if (!health.ok) {
      throw new AdminError(
        "GOVERNANCE_UNAVAILABLE",
        `27 治理系统不可达，提案被拒绝：${health.error || "unknown"}`,
      );
    }

    const created = await createApproval({
      action: L2_PROPOSE_ACTION,
      level: "L2",
      target: file,
      target_type: "system-config",
      requester: ctx.actor.uid,
      reason: parsed.data.reason || "",
      patch: after,
      before,
      expected_mtime_ms: parsed.data.expectedMtimeMs ?? null,
      decision: "pending",
      source: "admin-console",
    });
    if (!created.ok || !created.approvalId) {
      throw new AdminError(
        "GOVERNANCE_UNAVAILABLE",
        `27 审批创建失败：${created.error || "unknown"}`,
      );
    }

    const op = await createOpLog(prisma, {
      requestId: ctx.requestId,
      idempotencyKey: ctx.idempotencyKey,
      actorUid: ctx.actor.uid,
      actorRole: ctx.actor.role,
      level: "L2",
      action: L2_PROPOSE_ACTION,
      targetType: "system-config",
      targetId: file,
      reason: parsed.data.reason || null,
      beforeData: before,
      afterData: after,
      diff,
      status: "PENDING_APPROVAL",
      approvalId: created.approvalId,
      ip: ctx.ip,
      userAgent: ctx.userAgent,
    });

    return apiOk(
      {
        opId: op.id,
        approvalId: created.approvalId,
        status: "PENDING_APPROVAL",
        file,
        before,
        after,
        diff,
      },
      { requestId, message: "L2 提案已提交 27 审批，审批通过后用 approvalId 执行" },
    );
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
