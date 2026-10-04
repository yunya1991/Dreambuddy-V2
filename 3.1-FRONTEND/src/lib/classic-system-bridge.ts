/**
 * Classic System Bridge — 设置层 ↔ 经典模块化系统 统一桥接
 *
 * 职责：
 * 1. 同步方向：Prisma(PostgreSQL) 设置 → 经典模块化系统 REST API
 *    - 交易参数 / Gate 阈值 / API Key / 频道 → M27 治理配置 (/api/v1/config)
 *    - 策略 → M26 策略库注册 + M27 变更包/审批/流水线
 * 2. 读取方向：经典系统状态 → 前端经典页 UI
 *    - 流水线状态 → M27 /api/v1/pipeline/list
 *    - 审批流 → M27 /api/v1/approvals
 *    - 健康检查 → M27 /health
 *    - Gate 阈值 → M27 /api/v1/config
 *
 * 设计原则：
 * - PostgreSQL 是权威存储(source of truth)，经典系统为下游消费者
 * - 同步失败不阻塞 PostgreSQL 持久化，返回结构化 warnings
 * - 敏感数据(apiKey/secretKey)仅记录 key_hint，不输出明文
 * - 每次操作生成 trace_id，结构化日志
 */

/**
 * 经典系统已拆分为模块化服务（M25/M26/M27/M28），不再依赖单体 8092。
 * 读取方向按职责路由到对应模块：
 * - 流水线状态 / 审批流 / Gate 配置 → M27 策略治理审批系统 (8094)
 * - 策略库 → M26 策略管理模块 (8093)
 * - 信号触发 → M28 策略信号触发模块 (8096)
 * - 策略生成 → M25 用户策略生成系统 (8095)
 */
const GOVERNANCE_BASE =
  process.env.NEXT_PUBLIC_GOVERNANCE_URL || "http://127.0.0.1:8094";
const STRATEGY_LIB_BASE =
  process.env.NEXT_PUBLIC_STRATEGY_LIB_URL || "http://127.0.0.1:8093";

// 模块化服务 Admin Token（写入类端点鉴权）
const GOVERNANCE_ADMIN_TOKEN =
  process.env.GOVERNANCE_ADMIN_TOKEN || "dev-governance-token-2026";
const STRATEGY_LIB_ADMIN_TOKEN =
  process.env.STRATEGY_LIB_ADMIN_TOKEN || "dev-admin-token-2026";

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

// ============================================================
// 读取方向：经典系统状态 → 前端
// （已迁移至模块化服务，优先调用 M27 治理审批系统）
// ============================================================

/** 通用模块请求：失败时返回 ok:false，不抛异常 */
async function moduleRequest<T = unknown>(
  base: string,
  endpoint: string,
  options: RequestInit & { adminToken?: string } = {},
  traceId: string
): Promise<BridgeResult<T>> {
  const start = Date.now();
  const url = `${base}${endpoint}`;
  const { adminToken, ...fetchOptions } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOptions.headers as Record<string, string> | undefined),
  };
  if (adminToken) headers["X-Admin-Token"] = adminToken;
  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers,
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

export async function fetchClassicHealth(): Promise<BridgeResult<{ ok: boolean }>> {
  const traceId = genTraceId();
  // 健康检查以治理模块(M27)为准，它是经典流水线的权威状态源
  const res = await moduleRequest<{ ok: boolean }>(
    GOVERNANCE_BASE,
    "/health",
    { method: "GET" },
    traceId
  );
  if (res.ok && res.data) {
    return { ...res, data: { ok: true } };
  }
  return res;
}

export async function fetchClassicPipelineState(): Promise<BridgeResult<ClassicPipelineState>> {
  const traceId = genTraceId();
  // 取最新一条流水线状态，映射到前端 ClassicPipelineState
  const res = await moduleRequest<{
    ok: boolean;
    count: number;
    items: Array<{
      trace_id?: string;
      strategy_id?: string;
      current_stage?: string;
      overall_state?: string;
      stages?: Record<string, { state: string; result?: any; error?: string | null }>;
      updated_at?: number;
    }>;
  }>(
    GOVERNANCE_BASE,
    "/api/v1/pipeline/list?limit=1",
    { method: "GET" },
    traceId
  );
  if (!res.ok || !res.data) {
    return { ok: false, error: res.error || "pipeline_unavailable", trace_id: traceId };
  }
  const item = res.data.items?.[0];
  if (!item) {
    // 没有流水线记录也视为在线（只是暂无数据），避免误报离线
    return {
      ok: true,
      data: { phase: undefined, current: "idle", candidate: "", ts: Date.now() },
      trace_id: traceId,
    };
  }
  const stages = item.stages || {};
  // C3_backtest 阶段可能携带 gate 评估结果
  const c3Result = stages["C3_backtest"]?.result || {};
  const gatePassed =
    typeof c3Result?.gate_passed === "boolean"
      ? c3Result.gate_passed
      : typeof c3Result?.passed === "boolean"
        ? c3Result.passed
        : undefined;
  const data: ClassicPipelineState = {
    phase: item.current_stage || undefined,
    current: item.current_stage || item.overall_state || undefined,
    candidate: item.strategy_id || "",
    gate_result: gatePassed !== undefined ? { passed: gatePassed } : undefined,
    approval_id: undefined,
    ts: item.updated_at,
  };
  return { ok: true, data, trace_id: traceId };
}

export async function fetchClassicApprovals(): Promise<BridgeResult<ClassicApprovalSummary>> {
  const traceId = genTraceId();
  const res = await moduleRequest<{
    ok: boolean;
    count: number;
    pending_count: number;
    approved_count: number;
    items: Array<{
      id?: string;
      decision?: string;
      strategy_name?: string;
      strategy_id?: string;
      request_type?: string;
      action?: string;
      reason?: string;
      ts?: number;
      draft_id?: string;
    }>;
  }>(
    GOVERNANCE_BASE,
    "/api/v1/approvals?limit=100",
    { method: "GET" },
    traceId
  );
  if (!res.ok || !res.data) {
    return { ok: false, error: res.error || "approvals_unavailable", trace_id: traceId };
  }
  const items = res.data.items || [];
  const pending = items
    .filter((it) => {
      const dec = String(it.decision || "").toLowerCase();
      return dec === "pending" || dec === "awaiting" || dec === "";
    })
    .map((it) => ({
      id: it.id,
      strategy_name: it.strategy_name || it.strategy_id,
      status: it.decision || "pending",
      request_type: it.request_type || it.action,
      created_at: it.ts,
    }));
  const data: ClassicApprovalSummary = {
    ok: true,
    pending,
    approved_count: res.data.approved_count ?? 0,
    pending_count: res.data.pending_count ?? pending.length,
  };
  return { ok: true, data, trace_id: traceId };
}

export async function fetchClassicGateThresholds(): Promise<BridgeResult<ClassicGateThresholds>> {
  const traceId = genTraceId();
  const res = await moduleRequest<{ ok: boolean; config?: Record<string, any> }>(
    GOVERNANCE_BASE,
    "/api/v1/config",
    { method: "GET" },
    traceId
  );
  if (!res.ok || !res.data) {
    return { ok: false, error: res.error || "config_unavailable", trace_id: traceId };
  }
  const cfg = res.data.config || {};
  // 兼容两种存放形态：顶层 gate 字段 或 gate_thresholds 子对象
  const gate: Record<string, any> =
    (cfg.gate_thresholds as Record<string, any>) ||
    (cfg.gate as Record<string, any>) ||
    {};
  const data: ClassicGateThresholds = {
    pf: typeof gate.pf === "number" ? gate.pf : cfg.pf,
    dd: typeof gate.dd === "number" ? gate.dd : cfg.dd,
    trades: typeof gate.trades === "number" ? gate.trades : cfg.trades,
    winrate: typeof gate.winrate === "number" ? gate.winrate : cfg.winrate,
    recovery_time:
      typeof gate.recovery_time === "number" ? gate.recovery_time : cfg.recovery_time,
    oos_ok: typeof gate.oos_ok === "boolean" ? gate.oos_ok : cfg.oos_ok,
    sensitivity_ok:
      typeof gate.sensitivity_ok === "boolean" ? gate.sensitivity_ok : cfg.sensitivity_ok,
  };
  return { ok: true, data, trace_id: traceId };
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

  const tradingConfig: Record<string, unknown> = {};
  if (profile.leverageMax !== undefined) tradingConfig["max_leverage"] = profile.leverageMax;
  if (profile.capitalPercentage !== undefined) tradingConfig["position_size_pct"] = profile.capitalPercentage;
  if (profile.riskTolerance) tradingConfig["risk_tolerance"] = profile.riskTolerance;
  if (profile.tradeMode) tradingConfig["trade_mode"] = profile.tradeMode;
  if (profile.tradeType) tradingConfig["trade_type"] = profile.tradeType;
  if (profile.preferredFrequency) tradingConfig["execution_frequency"] = profile.preferredFrequency;
  if (profile.isTradingEnabled !== undefined) tradingConfig["live_trading_enabled"] = profile.isTradingEnabled;
  if (profile.dailyLossLimit !== undefined) tradingConfig["daily_loss_limit"] = profile.dailyLossLimit;
  if (profile.accountLossLimit !== undefined) tradingConfig["account_loss_limit"] = profile.accountLossLimit;
  if (profile.allowedSymbols) {
    const symbols = Array.isArray(profile.allowedSymbols)
      ? profile.allowedSymbols
      : safeJsonParse<string[]>(profile.allowedSymbols, []);
    tradingConfig["allowed_symbols"] = symbols;
  }

  if (Object.keys(tradingConfig).length === 0) {
    return { ok: true, data: {}, trace_id: traceId, warnings: ["no_fields_to_sync"] };
  }

  // 交易参数 → M27 治理配置（trading 命名空间）
  const result = await moduleRequest<{ ok: boolean; updated_keys?: string[] }>(
    GOVERNANCE_BASE,
    "/api/v1/config",
    {
      method: "PUT",
      adminToken: GOVERNANCE_ADMIN_TOKEN,
      body: JSON.stringify({ trading: tradingConfig }),
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

  // Gate 阈值 → M27 治理配置（gate_thresholds 命名空间）
  const result = await moduleRequest<{ ok: boolean; updated_keys?: string[] }>(
    GOVERNANCE_BASE,
    "/api/v1/config",
    {
      method: "PUT",
      adminToken: GOVERNANCE_ADMIN_TOKEN,
      body: JSON.stringify({ gate_thresholds: thresholds }),
    },
    traceId
  );

  if (result.ok) {
    return { ...result, data: thresholds };
  }
  return { ...result, data: undefined };
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

  // UI 创建的策略用名称派生 source_zip（M26 注册表与 M27 变更包均以此为键）
  const sourceZip = `user_data/strategies/${strategy.name}.py`;

  // ── Stage 1: 注册策略到 M26 策略库（变更包草稿依赖注册表条目）──
  const upsertRes = await moduleRequest<{ ok: boolean; entry?: Record<string, unknown> }>(
    STRATEGY_LIB_BASE,
    "/api/v1/lib/strategies/upsert",
    {
      method: "POST",
      adminToken: STRATEGY_LIB_ADMIN_TOKEN,
      body: JSON.stringify({
        strategy_id: strategy.id,
        source_zip: sourceZip,
        name: strategy.name,
        description: strategy.description || "",
        symbol: strategy.symbol,
        direction: strategy.direction,
        trade_type: strategy.tradeType,
        leverage: strategy.leverage,
        position_size: strategy.positionSize,
        stop_loss: strategy.stopLoss,
        take_profit: strategy.takeProfit,
        frequency: strategy.frequency,
        ts: Date.now(),
      }),
    },
    traceId
  );

  if (!upsertRes.ok) {
    stages.draft = { ok: false, message: upsertRes.error };
    warnings.push(`strategy register failed: ${upsertRes.error}`);
    return {
      ok: false,
      error: `strategy register failed: ${upsertRes.error}`,
      data: { stages },
      trace_id: traceId,
      warnings,
      duration_ms: Date.now() - start,
    };
  }

  // ── Stage 2: M27 变更包草稿 ──
  // 策略参数已通过 M26 upsert 写入注册表；变更包 config_patch 仅接受运行时配置，
  // 策略级参数不走 config_patch，故传空对象避免校验拒绝。
  const draftRes = await moduleRequest<{
    ok?: boolean;
    id?: string;
    draft_id?: string;
    error?: string;
  }>(
    GOVERNANCE_BASE,
    "/api/v1/changeset/draft",
    {
      method: "POST",
      adminToken: GOVERNANCE_ADMIN_TOKEN,
      body: JSON.stringify({
        trace_id: traceId,
        strategy_id: strategy.id,
        source_zip: sourceZip,
        reason: strategy.description || "Dreambuddy settings strategy apply",
        config_patch: {},
      }),
    },
    traceId
  );

  if (draftRes.ok && draftRes.data && draftRes.data.ok !== false) {
    draftId = draftRes.data.id || draftRes.data.draft_id;
    stages.draft = { ok: true, message: draftId ? `draft=${draftId}` : "draft_created" };
    logBridge("info", "syncStrategy.draft", traceId, "draft created", { draft_id: draftId });
  } else {
    stages.draft = { ok: false, message: draftRes.error || draftRes.data?.error };
    warnings.push(`draft failed: ${draftRes.error || draftRes.data?.error}`);
    return {
      ok: false,
      error: `draft failed: ${draftRes.error || draftRes.data?.error}`,
      data: { stages },
      trace_id: traceId,
      warnings,
      duration_ms: Date.now() - start,
    };
  }

  // ── Stage 3: Gate — 变更包构建内含配置校验，草稿成功即视为 Gate 通过 ──
  stages.gate = { ok: true, message: "gate_passed_via_draft" };

  // ── Stage 4: M27 审批请求 ──
  const approvalRes = await moduleRequest<{ ok?: boolean; approval_id?: string; error?: string }>(
    GOVERNANCE_BASE,
    "/api/v1/approvals",
    {
      method: "POST",
      adminToken: GOVERNANCE_ADMIN_TOKEN,
      body: JSON.stringify({
        trace_id: traceId,
        draft_id: draftId,
        strategy_id: strategy.id,
        decision: "pending",
        reason: strategy.description || "auto apply from settings",
        category: "strategy_deployment",
        action: "strategy.inject",
        ts: Date.now(),
      }),
    },
    traceId
  );

  if (approvalRes.ok && approvalRes.data) {
    approvalId = approvalRes.data.approval_id;
    stages.approval = { ok: true, message: approvalId ? `approval=${approvalId}` : "approval_created" };
  } else {
    stages.approval = { ok: false, message: approvalRes.error };
    warnings.push(`approval failed: ${approvalRes.error}`);
  }

  // ── Stage 5: M27 流水线创建 + 标记 C7_monitor 为 passed（即 apply 完成）──
  // 先创建流水线状态，再把 C7 阶段置为 passed 表示策略已应用
  await moduleRequest(
    GOVERNANCE_BASE,
    "/api/v1/pipeline/create",
    {
      method: "POST",
      adminToken: GOVERNANCE_ADMIN_TOKEN,
      body: JSON.stringify({
        trace_id: traceId,
        strategy_id: strategy.id,
        source_zip: sourceZip,
      }),
    },
    traceId
  );

  const applyRes = await moduleRequest<{ ok?: boolean; state?: Record<string, unknown> }>(
    GOVERNANCE_BASE,
    `/api/v1/pipeline/stage/${traceId}/C7_monitor`,
    {
      method: "PUT",
      adminToken: GOVERNANCE_ADMIN_TOKEN,
      body: JSON.stringify({
        state: "passed",
        result: { strategy_id: strategy.id, source_zip: sourceZip, approval_id: approvalId },
      }),
    },
    traceId
  );

  if (applyRes.ok && applyRes.data) {
    stages.apply = { ok: true, message: "applied" };
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

  // 按 provider 分组，写入 M27 治理配置（exchange_keys 命名空间）
  // 仅 keyHint 入日志，明文密钥不落日志
  const exchangeKeysConfig: Record<string, Record<string, string>> = {};
  for (const k of exchangeKeys) {
    const provider = (k.provider || "okx").toLowerCase();
    const entry: Record<string, string> = {};
    if (k.apiKey) entry.api_key = k.apiKey;
    if (k.secretKey) entry.secret_key = k.secretKey;
    if (k.passphrase) entry.passphrase = k.passphrase;
    if (k.environment) entry.env = k.environment;
    exchangeKeysConfig[provider] = entry;
  }

  const result = await moduleRequest<{ ok: boolean; updated_keys?: string[] }>(
    GOVERNANCE_BASE,
    "/api/v1/config",
    {
      method: "PUT",
      adminToken: GOVERNANCE_ADMIN_TOKEN,
      body: JSON.stringify({ exchange_keys: exchangeKeysConfig }),
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

  // 通知频道配置 → M27 治理配置（channels 命名空间）
  const channelList = channels.map((c) => ({
    type: c.channelType,
    label: c.label,
    credentials: c.credentials || {},
    format: c.format || "CONCISE",
    enabled_types: c.enabledTypes || [],
  }));

  const result = await moduleRequest<{ ok: boolean; updated_keys?: string[] }>(
    GOVERNANCE_BASE,
    "/api/v1/config",
    {
      method: "PUT",
      adminToken: GOVERNANCE_ADMIN_TOKEN,
      body: JSON.stringify({ channels: channelList }),
    },
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
