// ============================================================================
// /api/admin/system-config/apply —— L2 执行（SPEC-7 §6.4 / §9 / G3）
// ----------------------------------------------------------------------------
// POST ?file=trailing_stop|param_center  body: { approvalId, expectedMtimeMs?, reason? }
//   1) 无 approvalId → 403（G3）
//   2) 27 不可达 → 503，拒绝执行（G3）
//   3) 审批目标/裁决/审批人校验：未通过 422；审批人=发起人 403（G3）
//   4) 同一 approvalId 只能执行一次
//   5) 以审批记录里的 patch 为准执行（不接受客户端新 patch，防审批后篡改）
// capital_control / capital_allocator 仅提案（SPEC §6.4），执行返回 422。
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import {
  ADMIN_L2_FILE_KEYS,
  L2_APPLY_ACTION,
  type AdminL2FileKey,
} from "@/lib/admin/constants";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";
import { prisma } from "@/lib/prisma";
import { beginWrite, readJsonBody } from "@/lib/admin/write/context";
import { buildDiff } from "@/lib/admin/write/diff";
import { createOpLog, updateOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";
import {
  planFilePatch,
  readConfigFile,
  serializeFileWrite,
  writeConfigAtomic,
  type FilePatchPlan,
  type FileSnapshot,
} from "@/lib/admin/write/file-config";
import { planParamCenterPatch, readParamCenterOverride } from "@/lib/admin/write/param-center";
import {
  assertApprovalUsableForExecution,
  checkGovernanceHealth,
  getApproval,
} from "@/lib/admin/write/governance";

export const dynamic = "force-dynamic";

const schema = z.object({
  approvalId: z.string().optional(),
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

interface PreparedWrite {
  plan: FilePatchPlan;
  snapshot: FileSnapshot;
  requiresRestart: boolean;
  message: string;
}

async function prepareWrite(
  file: AdminL2FileKey,
  patch: Record<string, unknown>,
  expectedMtimeMs?: number,
): Promise<PreparedWrite> {
  if (file === "capital_control" || file === "capital_allocator") {
    throw new AdminError(
      "RULE_BLOCKED",
      `${file} 仅支持提案（SPEC-7 §6.4），执行需由 27 gate 或人工完成`,
    );
  }

  const snapshot =
    file === "param_center"
      ? await readParamCenterOverride()
      : await readConfigFile("trailing_stop");

  if (
    expectedMtimeMs !== undefined &&
    Math.abs(snapshot.mtimeMs - expectedMtimeMs) > 1
  ) {
    throw new AdminError("CONFLICT_STALE", "配置文件已被外部修改，请刷新后重试");
  }

  if (file === "param_center") {
    return {
      plan: planParamCenterPatch(snapshot.data, patch),
      snapshot,
      requiresRestart: false,
      message: "param_center 覆盖已写入（≤60 秒内生效）",
    };
  }
  return {
    plan: planFilePatch("trailing_stop", snapshot.data, patch),
    snapshot,
    requiresRestart: true,
    message: "移动止损配置已写入，需重启下游服务后生效",
  };
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

    const approvalId = String(parsed.data.approvalId || "").trim();
    if (!approvalId) {
      throw new AdminError("FORBIDDEN_ROLE", "L2 执行必须携带 approvalId");
    }

    const health = await checkGovernanceHealth();
    if (!health.ok) {
      throw new AdminError(
        "GOVERNANCE_UNAVAILABLE",
        `27 治理系统不可达，拒绝执行：${health.error || "unknown"}`,
      );
    }

    const got = await getApproval(approvalId);
    if (!got.ok) {
      if (got.status === 404) {
        throw new AdminError("NOT_FOUND", "审批记录不存在");
      }
      throw new AdminError(
        "GOVERNANCE_UNAVAILABLE",
        `审批状态查询失败：${got.error || "unknown"}`,
      );
    }

    // G3：目标一致 + approved + 审批人≠发起人
    assertApprovalUsableForExecution(got.approval, file);

    const approvedPatch = got.approval?.patch;
    if (!approvedPatch || typeof approvedPatch !== "object" || Array.isArray(approvedPatch)) {
      throw new AdminError("RULE_BLOCKED", "审批记录缺少可执行的 patch");
    }

    const used = await prisma.adminOperationLog.findFirst({
      where: {
        approvalId,
        status: { in: ["APPLIED", "APPLIED_WITH_WARNINGS"] },
      },
      select: { id: true },
    });
    if (used) {
      throw new AdminError("RULE_BLOCKED", "该审批已被执行过，禁止重复执行");
    }

    const prepared = await prepareWrite(
      file,
      approvedPatch as Record<string, unknown>,
      parsed.data.expectedMtimeMs,
    );
    const diff = buildDiff(prepared.plan.before, prepared.plan.after);

    if (ctx.dryRun) {
      return apiOk(
        dryRunResponseData({
          before: prepared.plan.before,
          after: prepared.plan.after,
          diff,
          requiresRestart: prepared.requiresRestart,
        }),
        { requestId, message: "dryRun 校验通过（未写文件）" },
      );
    }

    const op = await createOpLog(prisma, {
      requestId: ctx.requestId,
      idempotencyKey: ctx.idempotencyKey,
      actorUid: ctx.actor.uid,
      actorRole: ctx.actor.role,
      level: "L2",
      action: L2_APPLY_ACTION,
      targetType: "system-config",
      targetId: file,
      reason: parsed.data.reason || null,
      beforeData: prepared.plan.before,
      afterData: prepared.plan.after,
      diff,
      status: "PENDING_AUDIT",
      approvalId,
      ip: ctx.ip,
      userAgent: ctx.userAgent,
    });

    let snapshotPath: string;
    try {
      snapshotPath = await serializeFileWrite(() =>
        writeConfigAtomic(file, prepared.snapshot, prepared.plan.next, prepared.plan.after),
      );
    } catch (error) {
      await updateOpLog(prisma, op.id, {
        status: "FAILED",
        errorCode: "FILE_WRITE_FAILED",
        errorMessage: error instanceof Error ? error.message : String(error),
      });
      throw error;
    }

    const withSnapshot = await updateOpLog(prisma, op.id, { snapshotPath });
    const finalized = await finalizeOp(withSnapshot);
    return apiOk(opResponseData(finalized, { requiresRestart: prepared.requiresRestart }), {
      requestId,
      message: prepared.message,
    });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
