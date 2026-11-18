/**
 * 能力注册表（单一事实源）——对话模型的「系统能力目录 + 统一调度入口」。
 *
 * 数据来自 capability-registry.json（抽取自 3+3 架构映射 / 54-L1 / 56-L2 / 47-MCP / 46-DSH）。
 * 新增能力只改 JSON，不改 prompt 与工具代码。
 *
 * 门禁（对齐 47 硬约束）：
 * - 只读：registry 中 readonly=false 的能力一律不暴露给对话模型；
 * - L2 对 L1 只读：l2_allowed=false 的能力拒绝由模型调用；
 * - 内部能力（internal）只做说明，不提供执行。
 */
import registryJson from "./capability-registry.json";
import { callDshHandler } from "../dsh-execution-engine";
import { executeTradingBinding } from "../trading-capability";
import { l1BaseUrl as getL1BaseUrl } from "../l1-base-url";

export type CapabilityLayer = "L0" | "L1" | "L2";
export type CapabilityKind =
  | "l1_query"
  | "dsh"
  | "script"
  | "http"
  | "pipeline"
  | "internal";

export interface CapabilityEntry {
  id: string;
  name: string;
  layer: CapabilityLayer;
  module: string;
  entry: {
    kind: CapabilityKind;
    module?: string;
    binding?: string;
    intent_hint?: string;
    reason?: string;
    note?: string;
    method?: string;
    path?: string;
    query?: Record<string, string>;
    recipe?: string;
  };
  when: string;
  params: Record<string, string>;
  latency_ms: number;
  readonly: boolean;
  l2_allowed: boolean;
  enabled: boolean;
}

const ALL = (registryJson.capabilities as CapabilityEntry[]) ?? [];

export interface CapabilityFilter {
  layer?: CapabilityLayer;
  keyword?: string;
}

/** 列出可被对话模型调用的能力（只读 + 允许 L2 + 已启用）。 */
export function listCapabilities(filter: CapabilityFilter = {}): CapabilityEntry[] {
  const keyword = filter.keyword?.trim().toLowerCase();
  return ALL.filter((c) => {
    if (!c.enabled || !c.readonly || !c.l2_allowed) return false;
    if (filter.layer && c.layer !== filter.layer) return false;
    if (keyword) {
      const haystack = `${c.id} ${c.name} ${c.when}`.toLowerCase();
      if (!haystack.includes(keyword)) return false;
    }
    return true;
  });
}

export function getCapability(id: string): CapabilityEntry | undefined {
  return ALL.find((c) => c.id === id);
}

/** 由注册表自动生成的能力路由摘要（注入 system prompt，避免文档与工具漂移）。 */
export function buildCapabilityPrompt(): string {
  const lines = listCapabilities().map(
    (c) => `- ${c.id}（${c.layer}，约 ${Math.round(c.latency_ms / 1000)}s）：${c.when}`,
  );
  return [
    "【系统能力目录（只读，来自 capability-registry）】",
    ...lines,
    "【调度规则】",
    "1. 用 system_capabilities 查看完整清单，用 run_capability(id, params) 执行。",
    "2. 价格/指标类事实先调 market.*，再进入分析；结论必须引用工具输出并标注时间与来源。",
    "3. 宏观读数用 data.macro_snapshot；链上周期/情绪极值/巨鲸流用 data.onchain_cycle；基本面用 data.fundamental_snapshot。禁止用训练记忆或默认值代替这些数据。",
    "4. 趋势/结构类问题：至少组合 dsh.technical + dsh.sentiment（必要时加 dsh.macro）；调度器会自动用真实数据补水。",
    "5. 维度结论冲突时调 dsh.c_drive 做裁决，不要自行拼凑矛盾。",
    "6. 用户要「完整交易研判/值不值得做/方向与情景」时，优先一次调用 trading.analysis_pipeline（按 6-TRADING A0-A3 编排），不要拆成多次单点调用。",
    "7. 工具失败或数据缺失时明确说明缺失项与降级范围，禁止用训练记忆补行情数字。",
    "8. 工具返回 degraded=true 或 note 含缺失项时，必须在结论中标注「该维度数据缺失」，不得当作真实信号。",
    "9. 调用 dsh.technical 时必须传 symbol；dsh.macro/dsh.sentiment 的输入由调度器注入真实数据，你不需要自己拼 indicators。",
    "10. 你没有下单、写库、改配置权限；但具备上述只读分析能力，不得声称\"无法分析\"。",
  ].join("\n");
}

export const CAPABILITY_PROMPT = buildCapabilityPrompt();

function l1BaseUrl(): string {
  return getL1BaseUrl();
}

/** 工具输出截断：避免单次结果撑爆上下文。 */
export function clip(value: unknown, max = 4000): string {
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value);
  } catch {
    text = String(value);
  }
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}…(truncated)` : text;
}

async function runL1Query(
  question: string,
  timeoutMs: number,
): Promise<{ ok: boolean; answer?: string; decision?: string; degraded?: boolean; error?: string }> {
  try {
    const res = await fetch(new URL("/api/data/query", l1BaseUrl()), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question }),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const json = (await res.json()) as {
      ok?: boolean;
      data?: {
        handled?: boolean;
        answer?: string;
        degraded?: boolean;
        route_signal?: { decision?: string };
      };
    };
    const data = json?.data ?? {};
    return {
      ok: json?.ok === true && data.handled === true,
      answer: data.answer ?? "",
      decision: data.route_signal?.decision ?? "",
      degraded: data.degraded === true,
    };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "l1_query_failed" };
  }
}

/** 同实例只读 API 调用（L1_INTERNAL_BASE_URL 指向前端自身）。 */
async function apiGet(
  path: string,
  query: Record<string, string> | undefined,
  timeoutMs: number,
): Promise<{ ok: boolean; data?: Record<string, unknown>; error?: string }> {
  try {
    const url = new URL(path, l1BaseUrl());
    for (const [k, v] of Object.entries(query ?? {})) url.searchParams.set(k, v);
    const res = await fetch(url, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    });
    const json = (await res.json().catch(() => null)) as Record<
      string,
      unknown
    > | null;
    if (!res.ok || !json) return { ok: false, error: `http_${res.status}` };
    return { ok: json.ok !== false, data: json };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "http_failed" };
  }
}

function toNum(v: unknown): number | undefined {
  if (v === null || v === undefined || v === "") return undefined;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export interface MacroSnapshot {
  /** DSH macro 子代理的 indicators（只放真实存在的项） */
  indicators: Record<string, number>;
  /** 原始宏观读数，供模型引用 */
  metrics: Record<string, number>;
  /** 无入库数据源的指标（不伪造 0） */
  missing: string[];
  timestamp?: string;
}

/** 拉取云端宏观快照（/api/data/macro → 19-DAL mm_metrics）。 */
export async function fetchMacroSnapshot(): Promise<MacroSnapshot> {
  const res = await apiGet("/api/data/macro", undefined, 10_000);
  const d = res.data ?? {};
  const keys = [
    "dxy",
    "us10y_yield",
    "vix",
    "gold",
    "sp500",
    "fed_funds_rate",
    "nasdaq",
    "m2_supply",
    "cpi_yoy",
  ];
  const metrics: Record<string, number> = {};
  for (const k of keys) {
    const n = toNum(d[k]);
    if (n !== undefined) metrics[k] = n;
  }
  const indicators: Record<string, number> = {};
  if (metrics.fed_funds_rate !== undefined)
    indicators.interest_rate = metrics.fed_funds_rate;
  if (metrics.m2_supply !== undefined)
    indicators.liquidity_m2 = metrics.m2_supply;
  if (metrics.cpi_yoy !== undefined) indicators.cpi_yoy = metrics.cpi_yoy;
  if (metrics.us10y_yield !== undefined)
    indicators.treasury_10y = metrics.us10y_yield;
  if (metrics.dxy !== undefined) indicators.dxy = metrics.dxy;
  if (metrics.vix !== undefined) indicators.vix = metrics.vix;

  // GDP 当前没有入库数据源：如实标注缺失，不用 0 冒充
  const missing: string[] = [];
  if (indicators.interest_rate === undefined) missing.push("interest_rate");
  if (indicators.cpi_yoy === undefined) missing.push("cpi_yoy");
  if (indicators.liquidity_m2 === undefined) missing.push("m2_supply");
  missing.push("gdp_yoy");

  return {
    indicators,
    metrics,
    missing,
    timestamp: typeof d.timestamp === "string" ? d.timestamp : undefined,
  };
}

export interface SentimentSnapshot {
  /** DSH sentiment 子代理的 sentiment 入参 */
  sentiment: Record<string, unknown>;
  /** 原始读数，供模型引用 */
  metrics: Record<string, number>;
  missing: string[];
}

/**
 * 拉取链上情绪/资金快照（/api/onchain/panewslab）。
 * score/impact 由固定规则从真实读数合成（非 LLM 编造），规则写在 rationale 里便于复核。
 */
export async function fetchSentimentSnapshot(): Promise<SentimentSnapshot> {
  const res = await apiGet("/api/onchain/panewslab", undefined, 15_000);
  const cycle = (res.data?.cycle ?? {}) as Record<string, unknown>;
  const exchange = (res.data?.exchange ?? {}) as Record<string, unknown>;

  const fgi = toNum(cycle.fear_greed) ?? toNum(cycle.bottom_fear_greed);
  const mvrv = toNum(cycle.mvrv);
  const nupl = toNum(cycle.nupl);
  const netflow = toNum(exchange.whale_netflow_to_ex_usd);
  const balChg = toNum(exchange.btc_balance_chg30d_pct);

  const metrics: Record<string, number> = {};
  if (fgi !== undefined) metrics.fear_greed = fgi;
  if (mvrv !== undefined) metrics.mvrv = mvrv;
  if (nupl !== undefined) metrics.nupl = nupl;
  if (netflow !== undefined) metrics.whale_netflow_to_ex_usd = netflow;
  if (balChg !== undefined) metrics.btc_balance_chg30d_pct = balChg;

  const rationale: string[] = [];
  let score = 0.5;
  if (fgi !== undefined) {
    score += (fgi - 50) / 200; // ±0.25
    rationale.push(`恐惧贪婪=${fgi}`);
  }
  if (netflow !== undefined) {
    // 巨鲸净流入交易所 = 潜在抛压（负分），净流出 = 提币（正分）
    const adj = -Math.sign(netflow) * Math.min(Math.abs(netflow) / 5e8, 0.15);
    score += adj;
    rationale.push(`巨鲸净流(正=流入交易所)=${netflow}`);
  }
  if (balChg !== undefined) {
    // 交易所余额 30 天增加 = 供给压力（负分）
    const adj = -Math.sign(balChg) * Math.min(Math.abs(balChg) / 20, 0.1);
    score += adj;
    rationale.push(`交易所BTC余额30日变化=${balChg}%`);
  }
  score = Math.min(1, Math.max(0, score));
  const impact = score > 0.55 ? "BULLISH" : score < 0.45 ? "BEARISH" : "NEUTRAL";
  if (fgi === undefined)
    rationale.push("未取到恐惧贪婪指数，情绪结论仅基于资金流");

  const missing: string[] = [];
  if (fgi === undefined) missing.push("fear_greed");
  if (netflow === undefined) missing.push("whale_netflow");

  return {
    sentiment: { impact, score, fgi, components: metrics, rationale },
    metrics,
    missing,
  };
}

/** DSH 子代理是否需要调用方先提供真实数据（HC-1：子代理不自己取数）。 */
function formatMacroContext(snap: MacroSnapshot): string {
  const label: Record<string, string> = {
    dxy: "美元指数",
    us10y_yield: "美债10Y(%)",
    vix: "VIX",
    gold: "黄金",
    sp500: "标普500",
    fed_funds_rate: "联邦基金利率(%)",
    nasdaq: "纳指",
    m2_supply: "M2",
    cpi_yoy: "CPI同比(%)",
  };
  const parts = Object.entries(snap.metrics).map(
    ([k, v]) => `${label[k] ?? k}=${v}`,
  );
  if (snap.missing.length > 0)
    parts.push(`缺失=${snap.missing.join("/")}（数据源未入库，勿臆造）`);
  return parts.join("; ");
}

/**
 * 从 L1 技术指标答案解析 DSH technical 所需的结构化指标。
 * DSH 子代理遵循 HC-1「不生成原始数据」，必须由调用方提供 indicators；
 * 不注入时它会用默认值（RSI=50 / MACD=0）输出假中性。
 */
export function parseTechnicalIndicators(answer: string): Record<string, number> {
  const num = (re: RegExp): number | undefined => {
    const m = answer.match(re);
    if (!m) return undefined;
    const v = Number(m[1]);
    return Number.isFinite(v) ? v : undefined;
  };
  const price = num(/现价\s*(-?[\d.]+)/);
  const rsi14 = num(/RSI14\s*(-?[\d.]+)/);
  const macd = num(/DIF\s*(-?[\d.]+)/);
  const indicators: Record<string, number> = {};
  if (price !== undefined) indicators.price = price;
  if (rsi14 !== undefined) indicators.rsi14 = rsi14;
  if (macd !== undefined) indicators.macd = macd;
  return indicators;
}

/** DSH 输出是否只是默认占位（全中性 + RSI 恰为 50 / 宏观值全 0）。 */
export function looksPlaceholder(output: unknown): boolean {
  try {
    const data = (typeof output === "string" ? JSON.parse(output) : output) as {
      signals?: Array<{ value?: unknown; direction?: string; confidence?: number }>;
      charts?: unknown[];
    };
    const signals = data?.signals ?? [];
    if (signals.length === 0) return true;
    const allNeutral = signals.every((s) => s.direction === "neutral");
    const weak = signals.every((s) => (s.confidence ?? 0) <= 0.5);
    const defaultish = signals.every((s) => s.value === 0 || s.value === 50 || s.value === "NEUTRAL");
    return allNeutral && weak && defaultish && (data?.charts?.length ?? 0) === 0;
  } catch {
    return false;
  }
}

/** 由 L1 指标构造 C-Drive 需要的信号数组（它在顶层读 signals，不读 node_output）。 */
export function buildSignals(indicators: Record<string, number>) {
  const signals: Array<{
    name: string;
    value: number;
    direction: "long" | "short" | "neutral";
    confidence: number;
  }> = [];
  const rsi = indicators.rsi14;
  if (rsi !== undefined) {
    signals.push({
      name: "RSI14",
      value: rsi,
      direction: rsi < 30 ? "long" : rsi > 70 ? "short" : "neutral",
      confidence: 0.65,
    });
  }
  const macd = indicators.macd;
  if (macd !== undefined) {
    signals.push({
      name: "MACD",
      value: macd,
      direction: macd < 0 ? "short" : "long",
      confidence: 0.6,
    });
  }
  return signals;
}

/** 从自然语言推断标的（模型未显式传 symbol 时的兜底）。 */
const SYMBOL_ALIASES: Array<[RegExp, string]> = [
  [/比特币|\bBTC\b/i, "BTC"],
  [/以太坊|\bETH\b/i, "ETH"],
  [/索拉纳|\bSOL\b/i, "SOL"],
  [/黄金|\bXAU\b|gold/i, "XAU"],
  [/茅台|600519/i, "600519.SH"],
  [/宁德时代|300750/i, "300750.SZ"],
  [/比亚迪|002594/i, "002594.SZ"],
  [/中国平安|601318/i, "601318.SH"],
  [/招商银行|600036/i, "600036.SH"],
  [/腾讯|00700/i, "00700.HK"],
  [/阿里巴巴|09988/i, "09988.HK"],
];

export function inferSymbol(text: string): string {
  if (!text) return "";
  for (const [re, symbol] of SYMBOL_ALIASES) {
    if (re.test(text)) return symbol;
  }
  return "";
}

export interface CapabilityRunResult {
  ok: boolean;
  capability: string;
  output?: string;
  error?: string;
  /** true 表示工具虽返回但数据为默认占位，不可作为结论依据 */
  degraded?: boolean;
  note?: string;
}

/** 统一调度入口：按注册表 entry.kind 分发到 L1 / DSH / 6-TRADING。 */
export async function runCapability(
  id: string,
  params: Record<string, unknown> = {},
): Promise<CapabilityRunResult> {
  const cap = getCapability(id);
  if (!cap) {
    const known = listCapabilities()
      .map((c) => c.id)
      .join(", ");
    return { ok: false, capability: id, error: `未知能力「${id}」。可用：${known}` };
  }
  if (!cap.enabled) {
    return { ok: false, capability: id, error: `能力「${id}」未启用` };
  }
  if (!cap.readonly) {
    return { ok: false, capability: id, error: `能力「${id}」非只读，对话层禁止调用` };
  }
  if (!cap.l2_allowed) {
    return { ok: false, capability: id, error: `能力「${id}」不对 L2 开放（内部能力）` };
  }

  // 标的解析：显式 symbol 优先，否则从问题/上下文推断（模型经常忘记传 symbol）
  const symbol =
    String(params.symbol ?? "").trim() ||
    inferSymbol(
      [params.question, params.query, params.context]
        .filter((v) => typeof v === "string")
        .join(" "),
    );

  if (cap.entry.kind === "l1_query") {
    // 模型常把"分析类原问题"直接塞进 question，会被 L1 分析闸门交回 L2；
    // 取数能力优先用 symbol 组装确定性取数问法，保证拿到事实数据。
    let question = String(params.question ?? params.query ?? "").trim();
    if (id === "market.price" && symbol) {
      question = `查询${symbol}价格`;
    } else if (id === "market.technical_indicator" && symbol) {
      question = `查询${symbol}技术指标`;
    } else if (symbol && question && !question.includes(symbol)) {
      question = `${symbol} ${question}`;
    }
    if (!question) question = cap.when;
    const res = await runL1Query(question, cap.latency_ms);
    return {
      ok: res.ok,
      capability: id,
      output: res.answer ? clip(res.answer) : undefined,
      error: res.ok
        ? undefined
        : res.error ?? `L1 未直接命中（decision=${res.decision || "unknown"}）`,
    };
  }

  if (cap.entry.kind === "dsh") {
    const moduleName = cap.entry.module || id;
    let nodeOutput: Record<string, unknown> = { ...params };
    /** 数据缺失说明：非空时把结果标记为部分降级，避免模型把默认值当真实信号 */
    const missingNotes: string[] = [];

    // technical 子代理遵循 HC-1：只消费 indicators，不自行取数。
    // 不注入时它会用默认值（RSI=50 / MACD=0）输出假中性，因此先用 L1 真实指标补水。
    if (moduleName === "technical" && !nodeOutput.indicators && symbol) {
      const l1 = await runL1Query(`查询${symbol}技术指标`, 20_000);
      const indicators =
        l1.ok && l1.answer ? parseTechnicalIndicators(l1.answer) : {};
      if (Object.keys(indicators).length > 0) {
        nodeOutput = {
          ...nodeOutput,
          symbol,
          indicators,
          context: [nodeOutput.context, l1.answer].filter(Boolean).join("\n"),
        };
      }
    }

    // macro 子代理只读 node_output.indicators（gdp_yoy/cpi_yoy/interest_rate/liquidity_m2），
    // 不从任何数据源取数。此前无人注入 → 全 0。这里用 /api/data/macro 的真实读数补齐。
    if (moduleName === "macro" && !nodeOutput.indicators) {
      const snap = await fetchMacroSnapshot();
      if (Object.keys(snap.indicators).length > 0) {
        nodeOutput = {
          ...nodeOutput,
          symbol: symbol || undefined,
          indicators: snap.indicators,
          context: [nodeOutput.context, formatMacroContext(snap)]
            .filter(Boolean)
            .join("\n"),
          rationale: snap.metrics
            ? Object.entries(snap.metrics).map(([k, v]) => `${k}=${v}`)
            : [],
        };
      }
      if (snap.missing.length > 0) {
        missingNotes.push(`宏观缺失项：${snap.missing.join("/")}（数据源未入库）`);
      }
    }

    // sentiment 子代理只读 node_output.sentiment（impact/score/fgi），无注入时恒为默认中性 0.5。
    if (moduleName === "sentiment" && !nodeOutput.sentiment) {
      const snap = await fetchSentimentSnapshot();
      if (Object.keys(snap.metrics).length > 0) {
        nodeOutput = {
          ...nodeOutput,
          symbol: symbol || undefined,
          sentiment: snap.sentiment,
          context: [nodeOutput.context, JSON.stringify(snap.metrics)]
            .filter(Boolean)
            .join("\n"),
        };
      }
      if (snap.missing.length > 0) {
        missingNotes.push(`情绪缺失项：${snap.missing.join("/")}`);
      }
    }

    // c_drive 的 IPC 契约在顶层读 signals/confidence/direction，而不是 node_output；
    // 没有信号时用 L1 真实指标构造，避免它在空输入下返回 null。
    const payload: Record<string, unknown> = { node_output: nodeOutput };
    if (moduleName === "c_drive") {
      let signals = Array.isArray(nodeOutput.signals) ? nodeOutput.signals : [];
      if (signals.length === 0 && symbol) {
        const l1 = await runL1Query(`查询${symbol}技术指标`, 20_000);
        const indicators =
          l1.ok && l1.answer ? parseTechnicalIndicators(l1.answer) : {};
        signals = buildSignals(indicators);
      }
      Object.assign(payload, {
        node_id: "C1",
        confidence: 0.5,
        direction: "NEUTRAL",
        intent_type: "analysis",
        signals,
      });
    }

    const res = await callDshHandler(
      moduleName,
      payload,
      cap.latency_ms,
    );
    // 不同 handler 的结果字段不一致：subagent 用 output，c_drive 用 decision。
    const raw = res as unknown as {
      output?: unknown;
      decision?: unknown;
      data?: unknown;
    };
    const picked = raw.output ?? raw.decision ?? raw.data;
    const hasValue = picked !== undefined && picked !== null;
    const placeholder =
      res.ok && hasValue ? looksPlaceholder(picked) : !hasValue;
    return {
      ok: res.ok === true && hasValue,
      capability: id,
      output: hasValue ? clip(picked) : undefined,
      error: hasValue
        ? undefined
        : res.error || `${moduleName}_no_output`,
      degraded: placeholder || undefined,
      note: [
        placeholder
          ? "DSH 未返回有效结果或仅有默认中性值，不可作为结论依据"
          : "",
        ...missingNotes,
      ]
        .filter(Boolean)
        .join("；") || undefined,
    };
  }

  if (cap.entry.kind === "http") {
    const path = cap.entry.path;
    if (!path) {
      return { ok: false, capability: id, error: `能力「${id}」缺少 API 路径` };
    }
    const res = await apiGet(path, cap.entry.query, cap.latency_ms);
    if (!res.ok || !res.data) {
      return {
        ok: false,
        capability: id,
        error: res.error || `${id}_http_failed`,
      };
    }
    const degraded = res.data.degraded === true || res.data.ok === false;
    return {
      ok: !degraded,
      capability: id,
      output: clip(res.data),
      degraded: degraded || undefined,
      note: degraded ? "数据源不可达或为空，请如实说明缺失，勿用训练记忆补数" : undefined,
    };
  }

  if (cap.entry.kind === "pipeline") {
    if (cap.entry.recipe === "trading_analysis_v1") {
      return runTradingAnalysisPipeline(id, symbol, params);
    }
    return { ok: false, capability: id, error: `未知编排配方「${cap.entry.recipe}」` };
  }

  if (cap.entry.kind === "script") {
    const binding = cap.entry.binding;
    if (!binding) {
      return { ok: false, capability: id, error: `能力「${id}」缺少脚本绑定` };
    }
    const res = await executeTradingBinding(binding, params);
    return {
      ok: res.ok,
      capability: id,
      output: res.ok ? clip(res.output) : undefined,
      error: res.ok ? undefined : res.error || "script_failed",
    };
  }

  return {
    ok: false,
    capability: id,
    error: cap.entry.reason || `能力「${id}」为内部能力，不可直接调用`,
  };
}

/**
 * 6-TRADING A0-A3 综合研判编排（三层分工）：
 * - DreamOS(S)：本函数承担编排，串行取数 + 并行调度；
 * - DSH(C)：technical/sentiment/macro/risk 只做维度判断，数据由本层注入（HC-1 不生成原始数据）；
 * - 6-TRADING(A)：结论结构按 A0-A3 框架输出（主要矛盾→方向→关键位→失效条件）。
 * 任一维度缺失都会写入 missing，模型必须如实标注，不得补数。
 */
async function runTradingAnalysisPipeline(
  id: string,
  symbol: string,
  params: Record<string, unknown>,
): Promise<CapabilityRunResult> {
  if (!symbol) {
    return {
      ok: false,
      capability: id,
      error: "需要 symbol（如 BTC / ETH / 600519.SH）",
    };
  }
  const question =
    String(params.question ?? "").trim() || `${symbol} 综合交易研判`;

  // A0 取数：技术指标 + 宏观 + 情绪并行（三者互不依赖）
  const [l1Tech, macroSnap, sentSnap] = await Promise.all([
    runL1Query(`查询${symbol}技术指标`, 20_000),
    fetchMacroSnapshot(),
    fetchSentimentSnapshot(),
  ]);
  const technicalAnswer = l1Tech.ok ? l1Tech.answer ?? "" : "";
  const indicators = parseTechnicalIndicators(technicalAnswer);

  // A1-A3 维度判断并行下发；子代理不自行取数，数据统一注入
  const base = {
    symbol,
    question,
    ...(technicalAnswer ? { context: technicalAnswer } : {}),
  };
  const [technical, sentiment, macro, risk] = await Promise.all([
    callDshHandler(
      "technical",
      { node_output: { ...base, indicators } },
      25_000,
    ),
    callDshHandler(
      "sentiment",
      { node_output: { ...base, sentiment: sentSnap.sentiment } },
      25_000,
    ),
    callDshHandler(
      "macro",
      {
        node_output: {
          ...base,
          indicators: macroSnap.indicators,
          rationale: Object.entries(macroSnap.metrics).map(
            ([k, v]) => `${k}=${v}`,
          ),
        },
      },
      25_000,
    ),
    callDshHandler("risk", { node_output: { ...base, indicators } }, 25_000),
  ]);

  const pick = (r: {
    output?: unknown;
    decision?: unknown;
    data?: unknown;
  }): unknown => r?.output ?? r?.decision ?? r?.data ?? null;

  const dimensions = {
    technical: pick(technical as never),
    sentiment: pick(sentiment as never),
    macro: pick(macro as never),
    risk: pick(risk as never),
  };

  // 矛盾裁决：各维度结论交给 c_drive，避免上层自由发挥
  const signals = buildSignals(indicators);
  const conflict = await callDshHandler(
    "c_drive",
    {
      node_id: "C1",
      confidence: 0.5,
      direction: "NEUTRAL",
      intent_type: "analysis",
      signals,
      node_output: { symbol, question, dimensions },
    },
    30_000,
  );

  const missing: string[] = [
    ...macroSnap.missing.map((m) => `macro.${m}`),
    ...sentSnap.missing.map((m) => `sentiment.${m}`),
  ];
  if (!technicalAnswer) missing.push("technical.l1_data");

  const payload = {
    framework: "6-TRADING A0-A3（A0 取数 → A1-A3 多维判断 → 矛盾裁决 → 结论）",
    symbol,
    generated_at: new Date().toISOString(),
    data: {
      technical_l1: technicalAnswer || null,
      indicators,
      macro: macroSnap.metrics,
      sentiment: sentSnap.metrics,
    },
    dimensions,
    conflict: pick(conflict as never),
    missing,
    output_contract: [
      "1) 主要矛盾：以 conflict 裁决为准，不自行拼凑",
      "2) 方向与置信度：说明技术/情绪/宏观是否共振",
      "3) 关键位与失效条件：引用 indicators / technical 的具体数值",
      "4) 数据缺口：missing 中每一项都要标注，禁止编造",
    ],
  };

  return {
    ok: true,
    capability: id,
    output: clip(payload, 6000),
    degraded: missing.length > 0 || undefined,
    note:
      missing.length > 0
        ? `部分维度缺失：${missing.join(", ")}（需在结论中标注）`
        : undefined,
  };
}
