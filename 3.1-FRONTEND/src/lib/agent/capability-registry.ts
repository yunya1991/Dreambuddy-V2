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

export type CapabilityLayer = "L0" | "L1" | "L2";
export type CapabilityKind = "l1_query" | "dsh" | "script" | "internal";

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
    "3. 趋势/结构类问题：至少组合 dsh.technical + dsh.sentiment（必要时加 dsh.macro）。",
    "4. 维度结论冲突时调 dsh.c_drive 做裁决，不要自行拼凑矛盾。",
    "5. 工具失败或数据缺失时明确说明缺失项与降级范围，禁止用训练记忆补行情数字。",
    "6. 工具返回 degraded=true 时，必须在结论中标注「该维度数据缺失/为默认中性」，不得当作真实信号。",
    "7. 调用 dsh.technical 时必须传 symbol，调度器会先用 L1 真实指标补水；宏观/情绪无数据时如实说明。",
    "8. 你没有下单、写库、改配置权限；但具备上述只读分析能力，不得声称\"无法分析\"。",
  ].join("\n");
}

export const CAPABILITY_PROMPT = buildCapabilityPrompt();

function l1BaseUrl(): string {
  return process.env.L1_INTERNAL_BASE_URL?.trim() || "http://127.0.0.1:3001";
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
      note: placeholder
        ? "DSH 未返回有效结果或仅有默认中性值，不可作为结论依据"
        : undefined,
    };
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
