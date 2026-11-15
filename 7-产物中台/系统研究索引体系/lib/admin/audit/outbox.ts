// ============================================================================
// 审计 outbox 补偿（SPEC-7 §9）
// ----------------------------------------------------------------------------
// 已提交事务无法回滚，因此审计采用「先落本地，再异步推送 27」：
//   1. 事务内写 PENDING_AUDIT
//   2. 提交后尽力推送 27 /api/v1/audit/event，成功置 APPLIED + auditFlushedAt
//   3. 失败保留待补偿，由 audit-flush 定时任务按指数退避重试
// 退避：失败次数 n → 等待 min(2^n, 3600) 秒（以 warnings 记录为准）
// ============================================================================

import type { AdminOperationLog, Prisma } from "@prisma/client";
import { prisma } from "@/lib/prisma";
import {
  ADMIN_AUDIT_FLUSH_BATCH,
  ADMIN_GOVERNANCE_TIMEOUT_MS,
  ENV_GOVERNANCE_ADMIN_TOKEN,
  GOVERNANCE_ADMIN_TOKEN_HEADER,
  GOVERNANCE_AUDIT_STAGE,
  GOVERNANCE_BASE_URL,
} from "../constants";
import { findPendingAudit, updateOpLog } from "../write/oplog";

export interface AuditFlushResult {
  scanned: number;
  flushed: number;
  skipped: number;
  failed: number;
  errors: string[];
}

interface AuditWarning {
  kind: string;
  at: string;
  error: string;
  attempts: number;
  /** 其他类型的警告可能携带补偿载荷（如 bridge_sync_failed.patch），必须原样保留 */
  [key: string]: unknown;
}

function readWarnings(value: Prisma.JsonValue | null): AuditWarning[] {
  if (!Array.isArray(value)) return [];
  const out: AuditWarning[] = [];
  for (const item of value) {
    if (item && typeof item === "object" && !Array.isArray(item)) {
      const record = item as Record<string, unknown>;
      out.push({
        ...record,
        kind: String(record.kind ?? ""),
        at: String(record.at ?? ""),
        error: String(record.error ?? ""),
        attempts: Number(record.attempts ?? 0) || 0,
      });
    }
  }
  return out;
}

function attemptsOf(warnings: AuditWarning[]): number {
  const relevant = warnings.filter((w) => w.kind === "audit_flush");
  return relevant.length ? Number(relevant[relevant.length - 1].attempts) || 0 : 0;
}

function lastFailedAt(warnings: AuditWarning[]): number {
  const relevant = warnings.filter((w) => w.kind === "audit_flush");
  if (!relevant.length) return 0;
  const ts = Date.parse(relevant[relevant.length - 1].at);
  return Number.isNaN(ts) ? 0 : ts;
}

function backoffMs(attempts: number): number {
  return Math.min(2 ** Math.min(attempts, 12), 3600) * 1000;
}

async function pushToGovernance(op: AdminOperationLog): Promise<string | null> {
  // 27 的 /api/v1/audit/event 需要写权限令牌，缺失即失败（不静默降级）
  const token = process.env[ENV_GOVERNANCE_ADMIN_TOKEN];
  if (!token) {
    return `${ENV_GOVERNANCE_ADMIN_TOKEN} 未配置`;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ADMIN_GOVERNANCE_TIMEOUT_MS);
  try {
    const res = await fetch(`${GOVERNANCE_BASE_URL}/api/v1/audit/event`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [GOVERNANCE_ADMIN_TOKEN_HEADER]: token,
      },
      // 字段口径对齐 27 governance/audit/chain.py::strategy_factory_audit
      body: JSON.stringify({
        trace_id: op.requestId,
        stage: GOVERNANCE_AUDIT_STAGE,
        action: op.action,
        actor: op.actorUid,
        result: {
          opId: op.id,
          level: op.level,
          targetType: op.targetType,
          targetId: op.targetId,
          status: op.status,
          actorRole: op.actorRole,
          reason: op.reason,
          diff: op.diff,
        },
        strategy_id: op.targetType === "strategy" ? op.targetId : null,
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      return `27 返回 ${res.status}`;
    }
    const body = (await res.json().catch(() => null)) as
      | { event?: { hash?: string }; hash?: string }
      | null;
    const hash = body?.event?.hash || body?.hash;
    return hash ? `hash:${hash}` : null;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  } finally {
    clearTimeout(timer);
  }
}

export async function flushAuditOutbox(
  limit = ADMIN_AUDIT_FLUSH_BATCH,
): Promise<AuditFlushResult> {
  const pending = await findPendingAudit(limit);
  const result: AuditFlushResult = {
    scanned: pending.length,
    flushed: 0,
    skipped: 0,
    failed: 0,
    errors: [],
  };

  for (const op of pending) {
    const warnings = readWarnings(op.warnings);
    const attempts = attemptsOf(warnings);
    const lastAt = lastFailedAt(warnings);
    if (lastAt && Date.now() - lastAt < backoffMs(attempts)) {
      result.skipped += 1;
      continue;
    }

    const outcome = await pushToGovernance(op);
    const success = outcome === null || outcome.startsWith("hash:");
    if (success) {
      await updateOpLog(prisma, op.id, {
        status: op.status === "PENDING_AUDIT" ? "APPLIED" : undefined,
        auditFlushedAt: new Date(),
        auditHash: outcome ? outcome.slice(5) : undefined,
      });
      result.flushed += 1;
      continue;
    }

    result.failed += 1;
    result.errors.push(`${op.id}: ${outcome}`);
    const nextWarnings: AuditWarning[] = [
      ...warnings,
      {
        kind: "audit_flush",
        at: new Date().toISOString(),
        error: outcome as string,
        attempts: attempts + 1,
      },
    ];
    await updateOpLog(prisma, op.id, {
      warnings: nextWarnings as unknown as Prisma.InputJsonValue,
      status:
        op.status === "APPLIED"
          ? "APPLIED_WITH_WARNINGS"
          : op.status === "PENDING_AUDIT"
            ? "PENDING_AUDIT"
            : undefined,
    });

    // 24h 未成功 → 告警（由日志采集侧接管）
    const firstFailure = Date.parse(
      (warnings.find((w) => w.kind === "audit_flush") || { at: "" }).at,
    );
    if (firstFailure && Date.now() - firstFailure > 24 * 3600 * 1000) {
      console.error(
        `[admin-audit-outbox] op ${op.id} 超过 24 小时未推送成功，需人工介入`,
      );
    }
  }

  return result;
}
