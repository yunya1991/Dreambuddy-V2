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
    "6. 你没有下单、写库、改配置权限；但具备上述只读分析能力，不得声称\"无法分析\"。",
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

export interface CapabilityRunResult {
  ok: boolean;
  capability: string;
  output?: string;
  error?: string;
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

  if (cap.entry.kind === "l1_query") {
    // 模型常把"分析类原问题"直接塞进 question，会被 L1 分析闸门交回 L2；
    // 取数能力优先用 symbol 组装确定性取数问法，保证拿到事实数据。
    const symbol = String(params.symbol ?? "").trim();
    let question = String(params.question ?? params.query ?? "").trim();
    if (id === "market.price" && symbol) {
      question = `查询${symbol}价格`;
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
    const res = await callDshHandler(
      cap.entry.module || id,
      { node_output: params },
      cap.latency_ms,
    );
    return {
      ok: res.ok === true,
      capability: id,
      output: res.ok ? clip(res.output) : undefined,
      error: res.ok ? undefined : res.error || `${cap.entry.module}_no_output`,
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
