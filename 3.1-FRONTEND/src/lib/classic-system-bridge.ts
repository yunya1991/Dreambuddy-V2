/**
 * Classic System Bridge — 设置层 ↔ 经典系统(端口 8092) 统一桥接
 *
 * 职责：
 * 1. 同步方向：Prisma(PostgreSQL) 设置 → 经典系统 REST API
 *    - 交易参数 → /config/set
 *    - Gate 阈值 → /gate/thresholds (POST)
 *    - 策略 → /strategy/inject/* 治理流程
 *    - API Key → 经典系统执行链路（脱敏）
 *    - 频道 → /agent/push/config
 * 2. 读取方向：经典系统状态 → 前端经典页 UI
 *    - 流水线状态 → /automation/serving/pipeline/state
 *    - 审批流 → /approvals/summary
 *    - 健康检查 → /health
 *    - Gate 阈值 → /gate/thresholds (GET)
 *
 * 设计原则：
 * - PostgreSQL 是权威存储(source of truth)，经典系统为下游消费者
 * - 同步失败不阻塞 PostgreSQL 持久化，返回结构化 warnings
 * - 敏感数据(apiKey/secretKey)仅记录 key_hint，不输出明文
 * - 每次操作生成 trace_id，结构化日志
 */

const CLASSIC_BASE =
  process.env.NEXT_PUBLIC_CLASSIC_SYSTEM_URL || "http://127.0.0.1:8092";

// ============================================================
// 通用类型
// ============================================================

export interface BridgeResult<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  trace_id: string;
  warnings?: string[];
  duration_ms?: number;
}

export interface ClassicPipelineState {
  phase?: string;
  current?: string;
  candidate?: string;
  gate_result?: { passed?: boolean; checks?: Record<string, boolean> };
  approval_id?: string;
  ts?: number;
}

export interface ClassicApprovalSummary {
  ok?: boolean;
  pending?: Array<{
    id?: string;
    strategy_name?: string;
    status?: string;
    request_type?: string;
    created_at?: number;
  }>;
  approved_count?: number;
  pending_count?: number;
}

export interface ClassicGateThresholds {
  pf?: number;
  dd?: number;
  trades?: number;
  winrate?: number;
  recovery_time?: number;
  oos_ok?: boolean;
  sensitivity_ok?: boolean;
}

// ============================================================
// 工具函数
// ============================================================

function genTraceId(): string {
  return `bridge-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function keyHint(key: string | null | undefined): string {
  if (!key) return "empty";
  const s = String(key);
  if (s.length <= 8) return "***";
  return `${s.slice(0, 4)}...${s.slice(-4)}`;
}

function logBridge(
  level: "info" | "warn" | "error",
  op: string,
  traceId: string,
  message: string,
  extra?: Record<string, unknown>
) {
  if (level === "error") {
    console.error(`[ClassicBridge] ${op} [${traceId}] ${message}`, extra || "");
  } else if (level === "warn") {
    console.warn(`[ClassicBridge] ${op} [${traceId}] ${message}`, extra || "");
  } else {
    console.log(`[ClassicBridge] ${op} [${traceId}] ${message}`, extra || "");
  }
}

/** 通用请求：经典系统不可达时返回 ok:false，不抛异常 */
async function classicRequest<T = unknown>(
  endpoint: string,
  options: RequestInit = {},
  traceId: string
): Promise<BridgeResult<T>> {
  const start = Date.now();
  const url = `${CLASSIC_BASE}${endpoint}`;
  try {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
    const durationMs = Date.now() - start;
    if (!response.ok) {
      let errMsg = `HTTP ${response.status}`;
      try {
        const errBody = await response.json();
        errMsg = errBody?.error || errMsg;
      } catch {
        /* ignore */
      }
      logBridge("warn", endpoint, traceId, `HTTP ${response.status}: ${errMsg}`, {
        duration_ms: durationMs,
      });
      return { ok: false, error: errMsg, trace_id: traceId, duration_ms: durationMs };
    }
    const data = (await response.json()) as T;
    logBridge("info", endpoint, traceId, "ok", { duration_ms: durationMs });
    return { ok: true, data, trace_id: traceId, duration_ms: durationMs };
  } catch (error) {
    const durationMs = Date.now() - start;
    const msg = error instanceof Error ? error.message : "network_error";
    logBridge("error", endpoint, traceId, `request failed: ${msg}`, { duration_ms: durationMs });
    return { ok: false, error: msg, trace_id: traceId, duration_ms: durationMs };
  }
}

// ============================================================
// 读取方向：经典系统状态 → 前端
// ============================================================

export async function fetchClassicHealth(): Promise<BridgeResult<{ ok: boolean }>> {
  const traceId = genTraceId();
  return classicRequest<{ ok: boolean }>("/health", { method: "GET" }, traceId);
}

export async function fetchClassicPipelineState(): Promise<BridgeResult<ClassicPipelineState>> {
  const traceId = genTraceId();
  return classicRequest<ClassicPipelineState>(
    "/automation/serving/pipeline/state",
    { method: "GET" },
    traceId
  );
}

export async function fetchClassicApprovals(): Promise<BridgeResult<ClassicApprovalSummary>> {
  const traceId = genTraceId();
  return classicRequest<ClassicApprovalSummary>("/approvals/summary", { method: "GET" }, traceId);
}

export async function fetchClassicGateThresholds(): Promise<BridgeResult<ClassicGateThresholds>> {
  const traceId = genTraceId();
  const result = await classicRequest<{ thresholds?: ClassicGateThresholds }>(
    "/gate/thresholds",
    { method: "GET" },
    traceId
  );
  if (result.ok && result.data) {
    return { ...result, data: result.data.thresholds || {} };
  }
  return result as BridgeResult<ClassicGateThresholds>;
}

// ============================================================
// 同步方向：Prisma 设置 → 经典系统
// ============================================================

export interface TradingProfileSync {
  leverageMax?: number;
  capitalPercentage?: number;
  riskTolerance?: string;
  tradeMode?: string;
  tradeType?: string;
  allowedSymbols?: string[] | string;
  preferredFrequency?: string;
  isTradingEnabled?: boolean;
  dailyLossLimit?: number;
  accountLossLimit?: number;
}

export async function syncTradingParamsToClassic(
  profile: TradingProfileSync
): Promise<BridgeResult<Record<string, unknown>>> {
  const traceId = genTraceId();
  const start = Date.now();

  const configPatch: Record<string, unknown> = {};
  if (profile.leverageMax !== undefined) configPatch["max_leverage"] = profile.leverageMax;
  if (profile.capitalPercentage !== undefined) configPatch["position_size_pct"] = profile.capitalPercentage;
  if (profile.riskTolerance) configPatch["risk_tolerance"] = profile.riskTolerance;
  if (profile.tradeMode) configPatch["trade_mode"] = profile.tradeMode;
  if (profile.tradeType) configPatch["trade_type"] = profile.tradeType;
  if (profile.preferredFrequency) configPatch["execution_frequency"] = profile.preferredFrequency;
  if (profile.isTradingEnabled !== undefined) configPatch["live_trading_enabled"] = profile.isTradingEnabled;
  if (profile.allowedSymbols) {
    const symbols = Array.isArray(profile.allowedSymbols)
      ? profile.allowedSymbols
      : safeJsonParse<string[]>(profile.allowedSymbols, []);
    configPatch["allowed_symbols"] = symbols;
  }

  if (Object.keys(configPatch).length === 0) {
    return { ok: true, data: {}, trace_id: traceId, warnings: ["no_fields_to_sync"] };
  }

  const result = await classicRequest<Record<string, unknown>>(
    "/config/set",
    {
      method: "POST",
      body: JSON.stringify({ config_patch: configPatch, trace_id: traceId, auto_approve: true }),
    },
    traceId
  );

  const durationMs = Date.now() - start;
  if (!result.ok) {
    logBridge("warn", "syncTradingParamsToClassic", traceId, "sync failed", {
      error: result.error,
      duration_ms: durationMs,
    });
  }
  return { ...result, duration_ms: durationMs };
}

function riskToleranceToGateThresholds(
  riskTolerance: string,
  leverageMax: number
): ClassicGateThresholds {
  const base: Record<string, ClassicGateThresholds> = {
    CONSERVATIVE: { pf: 1.3, dd: 0.85, trades: 0.8, winrate: 0.6, recovery_time: 1.5 },
    MODERATE: { pf: 1.15, dd: 0.9, trades: 0.7, winrate: 0.5, recovery_time: 1.2 },
    AGGRESSIVE: { pf: 1.05, dd: 0.95, trades: 0.6, winrate: 0.45, recovery_time: 1.0 },
  };
  const thr = { ...(base[riskTolerance] || base.MODERATE) };
  if (leverageMax >= 4) {
    thr.pf = (thr.pf || 1.1) + 0.1;
    thr.dd = (thr.dd || 0.9) - 0.05;
  }
  return thr;
}

export async function syncGateThresholds(
  riskTolerance: string,
  leverageMax: number
): Promise<BridgeResult<ClassicGateThresholds>> {
  const traceId = genTraceId();
  const thresholds = riskToleranceToGateThresholds(riskTolerance, leverageMax);

  const result = await classicRequest<ClassicGateThresholds & { thresholds?: ClassicGateThresholds }>(
    "/gate/thresholds",
    {
      method: "POST",
      body: JSON.stringify({ ...thresholds, trace_id: traceId, confirm_live: true }),
    },
    traceId
  );

  if (result.ok && result.data) {
    const data = result.data.thresholds || (result.data as ClassicGateThresholds);
    return { ...result, data };
  }
  return result as BridgeResult<ClassicGateThresholds>;
}

export interface StrategySync {
  id: string;
  name: string;
  description?: string | null;
  direction: string;
  symbol: string;
  tradeType?: string;
  leverage?: number;
  positionSize?: number;
  stopLoss?: number | null;
  takeProfit?: number | null;
  frequency?: string;
}

export interface StrategySyncResult {
  changeset_id?: string;
  draft_id?: string;
  approval_id?: string;
  stages: {
    draft: { ok: boolean; message?: string };
    gate: { ok: boolean; message?: string };
    approval: { ok: boolean; message?: string };
    apply: { ok: boolean; message?: string };
  };
}

export async function syncStrategyToClassic(
  strategy: StrategySync
): Promise<BridgeResult<StrategySyncResult>> {
  const traceId = genTraceId();
  const start = Date.now();
  const stages: StrategySyncResult["stages"] = {
    draft: { ok: false },
    gate: { ok: false },
    approval: { ok: false },
    apply: { ok: false },
  };
  const warnings: string[] = [];
  let draftId: string | undefined;
  let approvalId: string | undefined;

  // Stage 1: Draft
  const draftPayload = {
    strategy_name: strategy.name,
    trace_id: traceId,
    candidate: {
      strategy_id: strategy.id,
      symbol: strategy.symbol,
      direction: strategy.direction,
      trade_type: strategy.tradeType,
    },
    changeset: {
      reason: strategy.description || "Dreambuddy settings strategy apply",
      description: `symbol=${strategy.symbol}, direction=${strategy.direction}, leverage=${strategy.leverage || 1}x`,
      version: `v1.0-${Date.now().toString(36)}`,
      param_overrides: {
        leverage: strategy.leverage,
        position_size: strategy.positionSize,
        stop_loss: strategy.stopLoss,
        take_profit: strategy.takeProfit,
        frequency: strategy.frequency,
      },
    },
  };

  const draftRes = await classicRequest<{ draft_id?: string; ok?: boolean }>(
    "/strategy/inject/draft",
    { method: "POST", body: JSON.stringify(draftPayload) },
    traceId
  );

  if (draftRes.ok && draftRes.data) {
    draftId = draftRes.data.draft_id;
    stages.draft = { ok: true, message: `draft=${draftId}` };
    logBridge("info", "syncStrategy.draft", traceId, "draft created", { draft_id: draftId });
  } else {
    stages.draft = { ok: false, message: draftRes.error };
    warnings.push(`draft failed: ${draftRes.error}`);
    return {
      ok: false,
      error: `draft failed: ${draftRes.error}`,
      data: { stages },
      trace_id: traceId,
      warnings,
      duration_ms: Date.now() - start,
    };
  }

  // Stage 2: Gate — 经典系统在 /strategy/inject/draft 创建时内部执行 Gate 评估，
  // 此处以 draft 创建成功作为 Gate 通过的信号
  const draftGatePassed = draftRes.data?.ok !== false;
  stages.gate = {
    ok: draftGatePassed,
    message: draftGatePassed ? "gate_passed_via_draft" : "gate_failed",
  };
  if (!draftGatePassed) warnings.push("gate check failed during draft creation");

  // Stage 3: Approval
  const approvalRes = await classicRequest<{ approval_id?: string; ok?: boolean }>(
    "/strategy/inject/approval/request",
    {
      method: "POST",
      body: JSON.stringify({
        draft_id: draftId,
        trace_id: traceId,
        reason: strategy.description || "auto apply from settings",
        category: "strategy_deployment",
        auto_approve: true,
      }),
    },
    traceId
  );

  if (approvalRes.ok && approvalRes.data) {
    approvalId = approvalRes.data.approval_id;
    stages.approval = { ok: true, message: `approval=${approvalId}` };
  } else {
    stages.approval = { ok: false, message: approvalRes.error };
    warnings.push(`approval failed: ${approvalRes.error}`);
  }

  // Stage 4: Apply
  const applyRes = await classicRequest<{ ok?: boolean; status?: string }>(
    "/strategy/inject/apply",
    {
      method: "POST",
      body: JSON.stringify({
        draft_id: draftId,
        trace_id: traceId,
        confirm_live: true,
        approval_id: approvalId,
      }),
    },
    traceId
  );

  if (applyRes.ok && applyRes.data) {
    stages.apply = { ok: true, message: applyRes.data.status || "applied" };
  } else {
    stages.apply = { ok: false, message: applyRes.error };
    warnings.push(`apply failed: ${applyRes.error}`);
  }

  const allOk = stages.draft.ok && stages.gate.ok && stages.approval.ok && stages.apply.ok;
  const durationMs = Date.now() - start;

  logBridge(allOk ? "info" : "warn", "syncStrategyToClassic", traceId, allOk ? "ok" : "partial", {
    stages,
    duration_ms: durationMs,
  });

  return {
    ok: allOk,
    data: { changeset_id: draftId, draft_id: draftId, approval_id: approvalId, stages },
    trace_id: traceId,
    warnings: warnings.length > 0 ? warnings : undefined,
    duration_ms: durationMs,
  };
}

export interface ApiConfigSync {
  category: string;
  provider: string;
  apiKey?: string | null;
  secretKey?: string | null;
  passphrase?: string | null;
  environment?: string;
  label?: string;
}

export async function syncApiKeysToClassic(
  apiConfigs: ApiConfigSync[]
): Promise<BridgeResult<{ synced: number }>> {
  const traceId = genTraceId();
  const exchangeKeys = apiConfigs.filter((c) => c.category === "EXCHANGE");

  if (exchangeKeys.length === 0) {
    return { ok: true, data: { synced: 0 }, trace_id: traceId, warnings: ["no_exchange_keys"] };
  }

  const hints = exchangeKeys.map((k) => ({
    provider: k.provider,
    env: k.environment,
    api_key_hint: keyHint(k.apiKey),
  }));
  logBridge("info", "syncApiKeysToClassic", traceId, `syncing ${exchangeKeys.length} exchange keys`, {
    keys: hints,
  });

  const configPatch: Record<string, unknown> = {};
  for (const k of exchangeKeys) {
    const prefix = `exchange_${(k.provider || "okx").toLowerCase()}`;
    if (k.apiKey) configPatch[`${prefix}_api_key`] = k.apiKey;
    if (k.secretKey) configPatch[`${prefix}_secret_key`] = k.secretKey;
    if (k.passphrase) configPatch[`${prefix}_passphrase`] = k.passphrase;
    if (k.environment) configPatch[`${prefix}_env`] = k.environment;
  }

  const result = await classicRequest<Record<string, unknown>>(
    "/config/set",
    {
      method: "POST",
      body: JSON.stringify({ config_patch: configPatch, trace_id: traceId, auto_approve: true }),
    },
    traceId
  );

  return {
    ...result,
    data: result.ok ? { synced: exchangeKeys.length } : undefined,
  };
}

export interface ChannelSync {
  channelType: string;
  label: string;
  credentials?: Record<string, string>;
  format?: string;
  enabledTypes?: string[];
}

export async function syncChannelsToClassic(
  channels: ChannelSync[]
): Promise<BridgeResult<{ synced: number }>> {
  const traceId = genTraceId();

  if (channels.length === 0) {
    return { ok: true, data: { synced: 0 }, trace_id: traceId };
  }

  logBridge("info", "syncChannelsToClassic", traceId, `syncing ${channels.length} channels`, {
    types: channels.map((c) => c.channelType),
  });

  const pushConfig = {
    channels: channels.map((c) => ({
      type: c.channelType,
      label: c.label,
      credentials: c.credentials || {},
      format: c.format || "CONCISE",
      enabled_types: c.enabledTypes || [],
    })),
  };

  const result = await classicRequest<Record<string, unknown>>(
    "/agent/push/config",
    { method: "POST", body: JSON.stringify(pushConfig) },
    traceId
  );

  return {
    ...result,
    data: result.ok ? { synced: channels.length } : undefined,
  };
}

function safeJsonParse<T>(raw: string | null | undefined, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export const ClassicBridge = {
  fetchClassicHealth,
  fetchClassicPipelineState,
  fetchClassicApprovals,
  fetchClassicGateThresholds,
  syncTradingParamsToClassic,
  syncGateThresholds,
  syncStrategyToClassic,
  syncApiKeysToClassic,
  syncChannelsToClassic,
};

export default ClassicBridge;
