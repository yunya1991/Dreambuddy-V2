// ============================================================================
// /api/admin/system-config —— 文件型系统配置（SPEC-7 §6.2 / §10）
// ----------------------------------------------------------------------------
// GET  ?file=monitor  读取当前配置（只读，供 UI 展示）
// PATCH ?file=monitor 白名单 key 写入（L1：原因 ≥10 字 + confirmToken）
//   · patch: { "systems.<name>.enabled": bool, "systems.<name>.max_idle_minutes": 1..1440 }
//   · expectedMtimeMs 可选，用于乐观并发（文件被外部改动 → 409）
//   · 快照写入 .admin-backups/，原子 rename，回读比对，requiresRestart=false（D4）
// ============================================================================

import { z } from "zod";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import { SYSTEM_CONFIG_ACTION } from "@/lib/admin/constants";
import { hashPayload, verifyConfirmToken } from "@/lib/admin/confirm-token";
import { requireAdminOrResponse } from "@/lib/admin/route-guard";
import { prisma } from "@/lib/prisma";
import { beginWrite, payloadWithoutToken, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertReason, buildDiff } from "@/lib/admin/write/diff";
import { createOpLog, updateOpLog } from "@/lib/admin/write/oplog";
import { dryRunResponseData, finalizeOp, opResponseData } from "@/lib/admin/write/finalize";
import {
  isAdminFileKey,
  planMonitorPatch,
  readConfigFile,
  serializeFileWrite,
  writeConfigAtomic,
  type FileSnapshot,
} from "@/lib/admin/write/file-config";

export const dynamic = "force-dynamic";

const schema = z.object({
  patch: z.record(z.string(), z.unknown()),
  expectedMtimeMs: z.number().optional(),
  reason: z.string().max(500).optional(),
  confirmToken: z.string().optional(),
});

function resolveFileKey(request: Request) {
  const file = new URL(request.url).searchParams.get("file") || "";
  if (!isAdminFileKey(file)) {
    throw new AdminError("VALIDATION_FAILED", `不支持的 file 参数：${file || "(空)"}`);
  }
  return file;
}

export async function GET(request: Request) {
  const denied = await requireAdminOrResponse();
  if (denied) return denied;
  let requestId = "";
  try {
    const key = resolveFileKey(request);
    const snapshot = await readConfigFile(key);
    requestId = `read-${Date.now().toString(36)}`;
    return apiOk(
      { file: key, mtimeMs: snapshot.mtimeMs, data: snapshot.data },
      { requestId },
    );
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}

export async function PATCH(request: Request) {
  let requestId = "";
  try {
    const ctx = await beginWrite(request);
    requestId = ctx.requestId;
    const key = resolveFileKey(request);

    const body = await readJsonBody(request);
    const parsed = schema.safeParse(body);
    if (!parsed.success) {
      throw new AdminError("VALIDATION_FAILED", "参数校验失败", {
        issues: parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
      });
    }

    const reason = assertReason(parsed.data.reason, "L1");
    const replay = await findReplay(ctx.idempotencyKey, SYSTEM_CONFIG_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const snapshot = await readConfigFile(key);
    if (
      parsed.data.expectedMtimeMs !== undefined &&
      Math.abs(snapshot.mtimeMs - parsed.data.expectedMtimeMs) > 1
    ) {
      throw new AdminError("CONFLICT_STALE", "配置文件已被外部修改，请刷新后重试");
    }

    const plan = planMonitorPatch(snapshot.data, parsed.data.patch);
    const diff = buildDiff(plan.before, plan.after);

    if (ctx.dryRun) {
      return apiOk(dryRunResponseData({ before: plan.before, after: plan.after, diff }), {
        requestId,
        message: "dryRun 校验通过（未写文件）",
      });
    }

    const token = parsed.data.confirmToken;
    if (!token) {
      throw new AdminError("VALIDATION_FAILED", "该操作需要二次确认，请先获取确认令牌");
    }
    const nonce = verifyConfirmToken(token, {
      uid: ctx.actor.uid,
      action: SYSTEM_CONFIG_ACTION,
      targetId: key,
      payloadHash: hashPayload(payloadWithoutToken(body)),
    }).nonce;

    // 先落 opLog（意图可审计），再写文件；写完补 snapshotPath
    const op = await createOpLog(prisma, {
      requestId: ctx.requestId,
      idempotencyKey: ctx.idempotencyKey,
      nonce,
      actorUid: ctx.actor.uid,
      actorRole: ctx.actor.role,
      level: "L1",
      action: SYSTEM_CONFIG_ACTION,
      targetType: "system-config",
      targetId: key,
      reason,
      beforeData: plan.before,
      afterData: plan.after,
      diff,
      status: "PENDING_AUDIT",
      ip: ctx.ip,
      userAgent: ctx.userAgent,
    });

    let snapshotPath: string;
    try {
      snapshotPath = await serializeFileWrite(() =>
        writeConfigAtomic(key, snapshot as FileSnapshot, plan.next, plan.after),
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
    return apiOk(opResponseData(finalized), {
      requestId,
      message: "监控配置已写入（下一轮 ≤60 分钟生效，无需重启）",
    });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}
