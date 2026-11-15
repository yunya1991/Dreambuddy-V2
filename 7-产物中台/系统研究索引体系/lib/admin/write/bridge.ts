// ============================================================================
// BridgeSync：中台写库后下发 27 治理配置（SPEC-7 §4.1 step 8 / ADR-6）
// ----------------------------------------------------------------------------
// 契约与 3.1-FRONTEND/src/lib/classic-system-bridge.ts 保持一致：
//   PUT {GOVERNANCE_BASE_URL}/api/v1/config  body = 命名空间补丁
//   · trading.live_trading_enabled —— 交易总开关（交易类，失败必须回滚）
//   · trading.trading_status —— 交易状态
//   · strategy_status[strategyId] —— 策略启停（非交易类，失败转待补偿）
// 超时 ADMIN_BRIDGE_TIMEOUT_MS；任何失败都返回 ok:false，由调用方决定语义。
// ============================================================================

import {
  ADMIN_BRIDGE_TIMEOUT_MS,
  ENV_GOVERNANCE_ADMIN_TOKEN,
  GOVERNANCE_ADMIN_TOKEN_HEADER,
  GOVERNANCE_BASE_URL,
} from "../constants.ts";

/** 与 3.1 共用的 config key 常量（R10：变更需双端同步评审） */
export const BRIDGE_CONFIG_KEYS = {
  tradingNamespace: "trading",
  liveTradingEnabled: "live_trading_enabled",
  tradingStatus: "trading_status",
  strategyStatusNamespace: "strategy_status",
} as const;

export interface BridgeSyncOutcome {
  ok: boolean;
  error?: string;
  traceId: string;
  durationMs: number;
  patch: Record<string, unknown>;
}

export function newBridgeTraceId(): string {
  return `admin-bridge-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** 下发一组配置补丁；失败不抛异常（调用方按动作类别决定回滚/补偿） */
export async function putGovernanceConfig(
  patch: Record<string, unknown>,
  traceId = newBridgeTraceId(),
): Promise<BridgeSyncOutcome> {
  const started = Date.now();
  const token = process.env[ENV_GOVERNANCE_ADMIN_TOKEN];
  if (!token) {
    return {
      ok: false,
      error: `${ENV_GOVERNANCE_ADMIN_TOKEN} 未配置`,
      traceId,
      durationMs: 0,
      patch,
    };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ADMIN_BRIDGE_TIMEOUT_MS);
  try {
    const res = await fetch(`${GOVERNANCE_BASE_URL}/api/v1/config`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        [GOVERNANCE_ADMIN_TOKEN_HEADER]: token,
      },
      body: JSON.stringify(patch),
      signal: controller.signal,
    });
    const durationMs = Date.now() - started;
    if (!res.ok) {
      const body = (await res.json().catch(() => null)) as { error?: string } | null;
      return {
        ok: false,
        error: body?.error || `27 返回 ${res.status}`,
        traceId,
        durationMs,
        patch,
      };
    }
    const body = (await res.json().catch(() => null)) as { ok?: boolean } | null;
    if (body && body.ok === false) {
      return { ok: false, error: "27 返回 ok=false", traceId, durationMs, patch };
    }
    return { ok: true, traceId, durationMs, patch };
  } catch (error) {
    const message =
      error instanceof Error && error.name === "AbortError"
        ? `27 配置同步超时（${ADMIN_BRIDGE_TIMEOUT_MS}ms）`
        : error instanceof Error
          ? error.message
          : String(error);
    return { ok: false, error: message, traceId, durationMs: Date.now() - started, patch };
  } finally {
    clearTimeout(timer);
  }
}

/** 交易类动作：交易开关 / 交易状态，同一命名空间一次下发 */
export async function syncTradingConfig(input: {
  liveTradingEnabled?: boolean;
  status?: string;
}): Promise<BridgeSyncOutcome> {
  const trading: Record<string, unknown> = {};
  if (input.liveTradingEnabled !== undefined) {
    trading[BRIDGE_CONFIG_KEYS.liveTradingEnabled] = input.liveTradingEnabled;
  }
  if (input.status !== undefined) {
    trading[BRIDGE_CONFIG_KEYS.tradingStatus] = input.status;
  }
  if (Object.keys(trading).length === 0) {
    return { ok: true, traceId: newBridgeTraceId(), durationMs: 0, patch: {} };
  }
  return putGovernanceConfig({ [BRIDGE_CONFIG_KEYS.tradingNamespace]: trading });
}

/** 非交易类动作：策略启停（失败仅记 warnings，待补偿重试） */
export async function syncStrategyStatus(
  strategyId: string,
  status: string,
): Promise<BridgeSyncOutcome> {
  return putGovernanceConfig({
    [BRIDGE_CONFIG_KEYS.strategyStatusNamespace]: {
      [strategyId]: { status, updated_at: Date.now() },
    },
  });
}

/** 失败警告条目（写入 opLog.warnings，补偿任务按 kind + patch 重试） */
export function bridgeFailureWarning(kind: string, outcome: BridgeSyncOutcome) {
  return {
    kind,
    at: new Date().toISOString(),
    error: outcome.error || "unknown",
    attempts: 1,
    patch: outcome.patch,
    traceId: outcome.traceId,
  };
}
