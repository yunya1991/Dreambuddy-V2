// ============================================================================
// POST /api/admin/audit-logs/[opId]/rollback —— 受控回滚（SPEC-7 §9-6/7）
// ----------------------------------------------------------------------------
// 由 beforeData 生成逆操作，同样走 CAS：
//   · 目标 updatedAt 已变 → 409 CONFLICT_STALE（不允许自动回滚）
//   · 生成新 opLog：action=rollback，targetId=原 opId；原记录置 ROLLED_BACK
//   · 支持范围（M1a + M1b 全部写动作）：
//       users.unlock / credits.adjust / users.role / trading-params.update /
//       trading-params.reset-daily / strategies.status / tasks.status /
//       channels.update / api-configs.update / orders.update / system-config.update
//   · 交易类回滚下发失败 → 502 且把库内值还原为「回滚前」（与交易写同语义）
//   · 非交易类下发失败 → APPLIED_WITH_WARNINGS，交由 audit-flush 补偿重试
//   · 文件配置回滚按 expectedMtimeMs 乐观并发；L2 引导 27 gate/rollback
// ============================================================================

import { z } from "zod";
import type { AdminOperationLog, TradingStatus } from "@prisma/client";
import { AdminError, apiFail, apiOk } from "@/lib/admin/errors";
import {
  API_CONFIG_UPDATE_ACTION,
  CHANNEL_UPDATE_ACTION,
  CREDITS_ADJUST_ACTION,
  CREDITS_ADJUST_CATEGORY,
  CREDITS_ADJUST_DESCRIPTION_PREFIX,
  ORDER_UPDATE_ACTION,
  ROLLBACK_ACTION,
  STRATEGY_STATUS_ACTION,
  SYSTEM_CONFIG_ACTION,
  TASK_STATUS_ACTION,
  TRADING_PARAMS_ACTION,
  TRADING_RESET_DAILY_ACTION,
  USER_ROLE_ACTION,
  USER_UNLOCK_ACTION,
} from "@/lib/admin/constants";
import { hashPayload, verifyConfirmToken } from "@/lib/admin/confirm-token";
import { prisma } from "@/lib/prisma";
import { beginWrite, payloadWithoutToken, readJsonBody } from "@/lib/admin/write/context";
import { buildReplayPayload, findReplay } from "@/lib/admin/write/idempotency";
import { assertCasHit, parseExpectedUpdatedAt } from "@/lib/admin/write/cas";
import { assertReason, buildDiff, projectSafe } from "@/lib/admin/write/diff";
import { assertBalanceSufficient, creditsAdjustMagnitude } from "@/lib/admin/write/credits-rules";
import { createOpLog, updateOpLog } from "@/lib/admin/write/oplog";
import { finalizeOp, opResponseData } from "@/lib/admin/write/finalize";
import { bridgeFailureWarning, syncStrategyStatus, syncTradingConfig } from "@/lib/admin/write/bridge";
import {
  isAdminFileKey,
  planMonitorPatch,
  readConfigFile,
  serializeFileWrite,
  writeConfigAtomic,
} from "@/lib/admin/write/file-config";

export const dynamic = "force-dynamic";

const ROLLBACKABLE_STATUS = ["PENDING_AUDIT", "APPLIED", "APPLIED_WITH_WARNINGS"];

const ROLES = ["FREE", "PRO", "ADMIN"] as const;
const STRATEGY_STATUSES = ["DRAFT", "APPROVED", "APPLIED", "PAUSED", "EXPIRED"] as const;
const TASK_STATUSES = ["ACTIVE", "PAUSED", "COMPLETED", "FAILED"] as const;
const TRADING_STATUSES = ["ACTIVE", "PAUSED", "FROZEN"] as const; // LOCKED 只能由系统置位
const CHANNEL_FORMATS = ["CONCISE", "DETAILED"] as const;
const ORDER_STATUSES = ["PENDING", "PAID", "COMPLETED", "CANCELLED", "REFUNDED", "FAILED"] as const;

const schema = z.object({
  expectedUpdatedAt: z.union([z.string(), z.number()]).optional(),
  expectedProfileUpdatedAt: z.union([z.string(), z.number()]).optional(),
  expectedParamsUpdatedAt: z.union([z.string(), z.number()]).optional(),
  expectedMtimeMs: z.number().optional(),
  reason: z.string().max(500).optional(),
  confirmToken: z.string().optional(),
});

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** JSON 列不接受 Date 实例，统一转 ISO 字符串落审计 */
function iso(value: Date | null | undefined): string | null {
  return value ? value.toISOString() : null;
}

function pickEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
  label: string,
): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw new AdminError("RULE_BLOCKED", `原始记录缺少可恢复的${label}，无法自动回滚`);
  }
  return value as T;
}

/** 交易类补偿/非交易类补偿所需的后续动作 */
type PostAction =
  | {
      kind: "trading";
      restore: { isTradingEnabled: boolean; status: TradingStatus };
      previous: { isTradingEnabled: boolean; status: TradingStatus };
    }
  | { kind: "strategy"; strategyId: string; status: string };

export async function POST(request: Request, { params }: { params: { opId: string } }) {
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

    const replay = await findReplay(ctx.idempotencyKey, ROLLBACK_ACTION);
    if (replay) {
      return apiOk(buildReplayPayload(replay), { requestId, message: "幂等回放" });
    }

    const op = await prisma.adminOperationLog.findUnique({ where: { id: params.opId } });
    if (!op) {
      throw new AdminError("NOT_FOUND", "操作记录不存在");
    }
    if (op.action === ROLLBACK_ACTION) {
      throw new AdminError("RULE_BLOCKED", "回滚操作本身不可再回滚");
    }
    if (!ROLLBACKABLE_STATUS.includes(op.status)) {
      throw new AdminError("RULE_BLOCKED", `当前状态 ${op.status} 不可回滚`);
    }
    if (op.level !== "L0" && op.level !== "L1") {
      throw new AdminError("RULE_BLOCKED", "L2 操作请走 27 审批系统的 gate/rollback");
    }
    const existing = await prisma.adminOperationLog.findFirst({
      where: { action: ROLLBACK_ACTION, targetId: op.id },
      select: { id: true },
    });
    if (existing) {
      throw new AdminError("RULE_BLOCKED", `该操作已于 ${existing.id} 回滚`);
    }

    const level = op.level === "L1" ? "L1" : "L0";
    const reason = assertReason(parsed.data.reason, level);

    let nonce: string | null = null;
    if (level === "L1") {
      if (!parsed.data.confirmToken) {
        throw new AdminError("VALIDATION_FAILED", "回滚该操作需要二次确认令牌");
      }
      nonce = verifyConfirmToken(parsed.data.confirmToken, {
        uid: ctx.actor.uid,
        action: ROLLBACK_ACTION,
        targetId: op.id,
        payloadHash: hashPayload(payloadWithoutToken(body)),
      }).nonce;
    }

    const baseLogInput = {
      requestId: ctx.requestId,
      idempotencyKey: ctx.idempotencyKey,
      nonce,
      actorUid: ctx.actor.uid,
      actorRole: ctx.actor.role,
      level,
      action: ROLLBACK_ACTION,
      targetType: op.targetType,
      targetId: op.id,
      ip: ctx.ip,
      userAgent: ctx.userAgent,
    } as const;

    // 文件型配置：不能进 DB 事务，单独走「快照 → 原子写 → 回读」
    if (op.action === SYSTEM_CONFIG_ACTION) {
      const rolledFile = await rollbackFileConfig(
        op,
        parsed.data.expectedMtimeMs ?? null,
        reason,
        baseLogInput,
      );
      const finalized = await finalizeOp(rolledFile);
      return apiOk(opResponseData(finalized), {
        requestId,
        message: "配置已回滚（下一轮 ≤60 分钟生效，无需重启）",
      });
    }

    const expected = parsed.data.expectedUpdatedAt !== undefined
      ? parseExpectedUpdatedAt(parsed.data.expectedUpdatedAt)
      : null;
    if (!expected) {
      throw new AdminError("VALIDATION_FAILED", "缺少 expectedUpdatedAt（并发控制必填）");
    }

    const rolled = await prisma.$transaction(async (tx) => {
      let before: Record<string, unknown> | null = null;
      let after: Record<string, unknown> | null = null;
      let post: PostAction | null = null;

      if (op.action === USER_UNLOCK_ACTION) {
        const snapshot = asRecord(op.beforeData);
        const current = await tx.user.findUnique({
          where: { uid: op.targetId },
          select: { uid: true, lockedUntil: true, loginAttempts: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "目标用户已不存在");
        }
        const restored = {
          uid: current.uid,
          lockedUntil: snapshot.lockedUntil ? new Date(String(snapshot.lockedUntil)) : null,
          loginAttempts: Number(snapshot.loginAttempts ?? 0),
        };
        before = projectSafe(current as unknown as Record<string, unknown>, [
          "uid",
          "lockedUntil",
          "loginAttempts",
        ]);
        after = projectSafe(restored as unknown as Record<string, unknown>, [
          "uid",
          "lockedUntil",
          "loginAttempts",
        ]);

        const updated = await tx.user.updateMany({
          where: { uid: op.targetId, updatedAt: expected },
          data: restored,
        });
        assertCasHit(updated.count, "目标用户已被修改，无法自动回滚，请人工核对");
      } else if (op.action === CREDITS_ADJUST_ACTION) {
        const delta = Number(asRecord(op.afterData).delta);
        if (!Number.isFinite(delta) || delta === 0) {
          throw new AdminError("RULE_BLOCKED", "原始记录缺少调账额度，无法自动回滚");
        }
        const inverse = -delta;

        const current = await tx.creditsAccount.findUnique({
          where: { uid: op.targetId },
          select: { uid: true, balance: true, totalEarned: true, totalSpent: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "积分账户已不存在");
        }
        assertBalanceSufficient(current.balance, inverse);

        before = projectSafe(current as unknown as Record<string, unknown>, [
          "uid",
          "balance",
          "totalEarned",
          "totalSpent",
        ]);
        after = projectSafe(
          {
            uid: current.uid,
            balance: current.balance + inverse,
            totalEarned: current.totalEarned - Math.max(delta, 0),
            totalSpent: current.totalSpent - Math.max(-delta, 0),
          },
          ["uid", "balance", "totalEarned", "totalSpent"],
        );

        const updated = await tx.creditsAccount.updateMany({
          where: { uid: op.targetId, updatedAt: expected, balance: { gte: -inverse } },
          data: {
            balance: { increment: inverse },
            ...(inverse > 0 ? { totalEarned: { increment: inverse } } : {}),
            ...(inverse < 0 ? { totalSpent: { increment: -inverse } } : {}),
          },
        });
        assertCasHit(updated.count, "积分账户已被修改，无法自动回滚，请刷新后重试");

        const fresh = await tx.creditsAccount.findUnique({
          where: { uid: op.targetId },
          select: { balance: true },
        });
        await tx.creditsTransaction.create({
          data: {
            uid: op.targetId,
            type: inverse > 0 ? "EARN" : "SPEND",
            category: CREDITS_ADJUST_CATEGORY,
            amount: creditsAdjustMagnitude(inverse),
            balanceAfter: fresh?.balance ?? current.balance + inverse,
            description: `${CREDITS_ADJUST_DESCRIPTION_PREFIX}回滚 ${op.id}${reason ? `（${reason}）` : ""}`,
          },
        });
      } else if (op.action === USER_ROLE_ACTION) {
        const restoreRole = pickEnum(asRecord(op.beforeData).role, ROLES, "角色");
        const current = await tx.user.findUnique({
          where: { uid: op.targetId },
          select: { uid: true, role: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "目标用户已不存在");
        }
        before = { uid: current.uid, role: current.role };
        after = { uid: current.uid, role: restoreRole };

        const updated = await tx.user.updateMany({
          where: { uid: op.targetId, updatedAt: expected, role: { in: [...ROLES] } },
          data: { role: restoreRole },
        });
        assertCasHit(updated.count, "用户角色已变化，无法自动回滚，请刷新后重试");
      } else if (op.action === TRADING_PARAMS_ACTION) {
        const snapshot = asRecord(op.beforeData);
        const restoreEnabled = typeof snapshot.isTradingEnabled === "boolean"
          ? snapshot.isTradingEnabled
          : undefined;
        const restoreStatus = snapshot.status === undefined
          ? undefined
          : pickEnum(snapshot.status, TRADING_STATUSES, "交易状态");
        if (restoreEnabled === undefined && restoreStatus === undefined) {
          throw new AdminError("RULE_BLOCKED", "原始记录缺少交易开关/状态，无法自动回滚");
        }

        const [profile, tradingParams] = await Promise.all([
          tx.userProfile.findUnique({
            where: { uid: op.targetId },
            select: { uid: true, isTradingEnabled: true },
          }),
          tx.tradingParams.findUnique({
            where: { uid: op.targetId },
            select: { uid: true, status: true },
          }),
        ]);
        if (!profile || !tradingParams) {
          throw new AdminError("NOT_FOUND", "目标交易档案已不存在");
        }

        const previous = { isTradingEnabled: profile.isTradingEnabled, status: tradingParams.status };
        const restore = {
          isTradingEnabled: restoreEnabled ?? previous.isTradingEnabled,
          status: restoreStatus ?? previous.status,
        };
        before = { uid: op.targetId, ...previous };
        after = { uid: op.targetId, ...restore };

        if (restoreEnabled !== undefined) {
          const expProfile = parsed.data.expectedProfileUpdatedAt !== undefined
            ? parseExpectedUpdatedAt(parsed.data.expectedProfileUpdatedAt)
            : expected;
          const updated = await tx.userProfile.updateMany({
            where: { uid: op.targetId, updatedAt: expProfile },
            data: { isTradingEnabled: restore.isTradingEnabled },
          });
          assertCasHit(updated.count, "交易档案已被修改，无法自动回滚，请刷新后重试");
        }
        if (restoreStatus !== undefined) {
          const expParams = parsed.data.expectedParamsUpdatedAt !== undefined
            ? parseExpectedUpdatedAt(parsed.data.expectedParamsUpdatedAt)
            : expected;
          const updated = await tx.tradingParams.updateMany({
            where: { uid: op.targetId, updatedAt: expParams },
            data: { status: restore.status },
          });
          assertCasHit(updated.count, "交易参数已被修改，无法自动回滚，请刷新后重试");
        }

        post = { kind: "trading", restore, previous };
      } else if (op.action === TRADING_RESET_DAILY_ACTION) {
        const snapshot = asRecord(op.beforeData);
        const todayLoss = Number(snapshot.todayLoss);
        const todayTradeCount = Number(snapshot.todayTradeCount);
        const lastResetDate = typeof snapshot.lastResetDate === "string" ? snapshot.lastResetDate : null;
        if (!Number.isFinite(todayLoss) || !Number.isFinite(todayTradeCount) || !lastResetDate) {
          throw new AdminError("RULE_BLOCKED", "原始记录缺少当日亏损快照，无法自动回滚");
        }

        const current = await tx.tradingParams.findUnique({
          where: { uid: op.targetId },
          select: { uid: true, todayLoss: true, todayTradeCount: true, lastResetDate: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "目标交易参数记录已不存在");
        }
        before = {
          uid: current.uid,
          todayLoss: current.todayLoss,
          todayTradeCount: current.todayTradeCount,
          lastResetDate: current.lastResetDate,
        };
        after = { uid: current.uid, todayLoss, todayTradeCount, lastResetDate };

        const updated = await tx.tradingParams.updateMany({
          where: { uid: op.targetId, updatedAt: expected },
          data: { todayLoss, todayTradeCount, lastResetDate },
        });
        assertCasHit(updated.count, "交易参数已被修改，无法自动回滚，请刷新后重试");
      } else if (op.action === STRATEGY_STATUS_ACTION) {
        const restoreStatus = pickEnum(asRecord(op.beforeData).status, STRATEGY_STATUSES, "策略状态");
        const current = await tx.strategy.findUnique({
          where: { id: op.targetId },
          select: { id: true, status: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "目标策略已不存在");
        }
        before = { id: current.id, status: current.status };
        after = { id: current.id, status: restoreStatus };

        const updated = await tx.strategy.updateMany({
          where: { id: op.targetId, updatedAt: expected, status: current.status },
          data: { status: restoreStatus },
        });
        assertCasHit(updated.count, "策略已被修改，无法自动回滚，请刷新后重试");

        post = { kind: "strategy", strategyId: op.targetId, status: restoreStatus };
      } else if (op.action === TASK_STATUS_ACTION) {
        const restoreStatus = pickEnum(asRecord(op.beforeData).status, TASK_STATUSES, "任务状态");
        const current = await tx.strategyTask.findUnique({
          where: { id: op.targetId },
          select: { id: true, status: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "目标任务已不存在");
        }
        before = { id: current.id, status: current.status };
        after = { id: current.id, status: restoreStatus };

        const updated = await tx.strategyTask.updateMany({
          where: { id: op.targetId, updatedAt: expected, status: current.status },
          data: { status: restoreStatus },
        });
        assertCasHit(updated.count, "任务已被修改，无法自动回滚，请刷新后重试");
      } else if (op.action === CHANNEL_UPDATE_ACTION) {
        if (Object.prototype.hasOwnProperty.call(asRecord(op.diff), "pushRules")) {
          throw new AdminError(
            "RULE_BLOCKED",
            "该操作改动了推送规则（审计已脱敏），无法自动回滚，请人工核对后重配",
          );
        }
        const snapshot = asRecord(op.beforeData);
        const data: Record<string, unknown> = {};
        if (typeof snapshot.isOnline === "boolean") data.isOnline = snapshot.isOnline;
        if (typeof snapshot.format === "string") {
          data.format = pickEnum(snapshot.format, CHANNEL_FORMATS, "推送格式");
        }
        if (snapshot.silentStart === null || typeof snapshot.silentStart === "string") {
          data.silentStart = snapshot.silentStart;
        }
        if (snapshot.silentEnd === null || typeof snapshot.silentEnd === "string") {
          data.silentEnd = snapshot.silentEnd;
        }
        if (Object.keys(data).length === 0) {
          throw new AdminError("RULE_BLOCKED", "原始记录缺少可恢复的渠道字段，无法自动回滚");
        }

        const current = await tx.channelConfig.findUnique({
          where: { id: op.targetId },
          select: { id: true, isOnline: true, format: true, silentStart: true, silentEnd: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "目标渠道配置已不存在");
        }
        before = { ...current };
        after = { ...current, ...data };

        const updated = await tx.channelConfig.updateMany({
          where: { id: op.targetId, updatedAt: expected },
          data: data as never,
        });
        assertCasHit(updated.count, "渠道配置已被修改，无法自动回滚，请刷新后重试");
      } else if (op.action === API_CONFIG_UPDATE_ACTION) {
        const snapshot = asRecord(op.beforeData);
        const data: Record<string, unknown> = {};
        if (typeof snapshot.label === "string") data.label = snapshot.label;
        if (typeof snapshot.isVerified === "boolean") data.isVerified = snapshot.isVerified;
        if (snapshot.lastVerifiedAt === null || typeof snapshot.lastVerifiedAt === "string") {
          data.lastVerifiedAt = snapshot.lastVerifiedAt ? new Date(String(snapshot.lastVerifiedAt)) : null;
        }
        if (Object.keys(data).length === 0) {
          throw new AdminError("RULE_BLOCKED", "原始记录缺少可恢复的配置字段，无法自动回滚");
        }

        const current = await tx.apiConfig.findUnique({
          where: { id: op.targetId },
          select: { id: true, label: true, isVerified: true, lastVerifiedAt: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "目标 API 配置已不存在");
        }
        before = {
          id: current.id,
          label: current.label,
          isVerified: current.isVerified,
          lastVerifiedAt: iso(current.lastVerifiedAt),
        };
        after = {
          id: current.id,
          label: (data.label as string | undefined) ?? current.label,
          isVerified: (data.isVerified as boolean | undefined) ?? current.isVerified,
          lastVerifiedAt:
            "lastVerifiedAt" in data
              ? iso(data.lastVerifiedAt as Date | null)
              : iso(current.lastVerifiedAt),
        };

        const updated = await tx.apiConfig.updateMany({
          where: { id: op.targetId, updatedAt: expected },
          data: data as never,
        });
        assertCasHit(updated.count, "API 配置已被修改，无法自动回滚，请刷新后重试");
      } else if (op.action === ORDER_UPDATE_ACTION) {
        const snapshot = asRecord(op.beforeData);
        if (snapshot.status === "REFUNDED" || snapshot.status === "FAILED") {
          throw new AdminError("RULE_BLOCKED", "原订单状态由支付回调写入，不能通过管理台回滚");
        }
        const restoreStatus = pickEnum(snapshot.status, ORDER_STATUSES, "订单状态");
        const current = await tx.order.findUnique({
          where: { id: op.targetId },
          select: { id: true, status: true, completedAt: true },
        });
        if (!current) {
          throw new AdminError("NOT_FOUND", "目标订单已不存在");
        }
        before = { id: current.id, status: current.status, completedAt: iso(current.completedAt) };
        after = {
          id: current.id,
          status: restoreStatus,
          completedAt: restoreStatus === "COMPLETED" ? iso(current.completedAt) : null,
        };

        const updated = await tx.order.updateMany({
          where: { id: op.targetId, updatedAt: expected, status: current.status },
          data: {
            status: restoreStatus,
            ...(restoreStatus === "COMPLETED" ? {} : { completedAt: null }),
          },
        });
        assertCasHit(updated.count, "订单状态已变化，无法自动回滚，请刷新后重试");
      } else {
        throw new AdminError("RULE_BLOCKED", `操作类型 ${op.action} 暂不支持自动回滚`);
      }

      const diff = buildDiff(before, after);
      const rollbackLog = await createOpLog(tx, {
        ...baseLogInput,
        reason: reason ? `回滚 ${op.id}：${reason}` : `回滚 ${op.id}`,
        beforeData: before,
        afterData: after,
        diff,
        status: "PENDING_AUDIT",
      });

      return { rollbackLog, post };
    });

    let effective = rolled.rollbackLog;
    const post = rolled.post;
    if (post?.kind === "trading") {
      const previous = post.previous;
      const outcome = await syncTradingConfig(post.restore);
      if (!outcome.ok) {
        // 交易类失败：把库内值还原为回滚前，再报 502（与交易写同语义）
        await prisma.$transaction(async (tx) => {
          await tx.userProfile.updateMany({
            where: { uid: op.targetId },
            data: { isTradingEnabled: previous.isTradingEnabled },
          });
          await tx.tradingParams.updateMany({
            where: { uid: op.targetId },
            data: { status: previous.status },
          });
        });
        await updateOpLog(prisma, effective.id, {
          status: "FAILED",
          errorCode: "BRIDGE_SYNC_FAILED",
          errorMessage: outcome.error || "27 同步失败",
          warnings: [{ ...bridgeFailureWarning("bridge_sync_failed", outcome), reverted: true }],
        });
        throw new AdminError(
          "BRIDGE_SYNC_FAILED",
          `回滚未能下发到交易侧，库内值已还原：${outcome.error || "unknown"}`,
          { opId: effective.id, traceId: outcome.traceId },
        );
      }
    } else if (post?.kind === "strategy") {
      const outcome = await syncStrategyStatus(post.strategyId, post.status);
      if (!outcome.ok) {
        effective = await updateOpLog(prisma, effective.id, {
          status: "APPLIED_WITH_WARNINGS",
          warnings: [bridgeFailureWarning("bridge_sync_failed", outcome)],
        });
      }
    }

    await prisma.adminOperationLog.update({
      where: { id: op.id },
      data: { status: "ROLLED_BACK", rolledBackAt: new Date() },
    });

    const finalized = await finalizeOp(effective);
    return apiOk(opResponseData(finalized), {
      requestId,
      message: finalized.status === "APPLIED_WITH_WARNINGS" ? "已回滚；下游同步待补偿" : "已回滚",
    });
  } catch (error) {
    return apiFail(error instanceof Error ? error : new Error(String(error)), requestId);
  }
}

/** 文件型配置回滚：按原 beforeData 反向写回，expectedMtimeMs 做乐观并发 */
async function rollbackFileConfig(
  op: AdminOperationLog,
  expectedMtimeMs: number | null,
  reason: string | null,
  logInput: {
    requestId: string;
    idempotencyKey: string;
    nonce: string | null;
    actorUid: string;
    actorRole: string;
    level: "L0" | "L1";
    action: string;
    targetType: string;
    targetId: string;
    ip: string | null;
    userAgent: string | null;
  },
): Promise<AdminOperationLog> {
  const key = op.targetId;
  if (!isAdminFileKey(key)) {
    throw new AdminError("RULE_BLOCKED", `未知的配置文件：${key}`);
  }
  if (expectedMtimeMs === null) {
    throw new AdminError("VALIDATION_FAILED", "回滚文件配置需要 expectedMtimeMs（并发控制必填）");
  }

  const snapshot = await readConfigFile(key);
  if (Math.abs(snapshot.mtimeMs - expectedMtimeMs) > 1) {
    throw new AdminError("CONFLICT_STALE", "配置文件已被他人修改，请刷新后重试");
  }

  const beforePatch = asRecord(op.beforeData);
  const entries = Object.entries(beforePatch);
  if (entries.length === 0) {
    throw new AdminError("RULE_BLOCKED", "原始记录缺少可恢复的配置值，无法自动回滚");
  }
  if (entries.some(([, value]) => value === null || value === undefined)) {
    throw new AdminError("RULE_BLOCKED", "存在原始值缺失（null）的配置项，无法自动回滚");
  }

  const plan = planMonitorPatch(snapshot.data, Object.fromEntries(entries));
  const diff = buildDiff(plan.before, plan.after);

  const op_ = await createOpLog(prisma, {
    ...logInput,
    reason: reason ? `回滚 ${op.id}：${reason}` : `回滚 ${op.id}`,
    beforeData: plan.before,
    afterData: plan.after,
    diff,
    status: "PENDING_AUDIT",
  });

  let snapshotPath: string;
  try {
    snapshotPath = await serializeFileWrite(() =>
      writeConfigAtomic(key, snapshot, plan.next, plan.after),
    );
  } catch (error) {
    await updateOpLog(prisma, op_.id, {
      status: "FAILED",
      errorCode: "FILE_WRITE_FAILED",
      errorMessage: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }

  const withSnapshot = await updateOpLog(prisma, op_.id, { snapshotPath });
  await prisma.adminOperationLog.update({
    where: { id: op.id },
    data: { status: "ROLLED_BACK", rolledBackAt: new Date() },
  });
  return withSnapshot;
}
