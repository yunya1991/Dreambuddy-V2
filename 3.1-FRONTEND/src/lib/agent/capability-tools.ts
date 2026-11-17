/**
 * 系统能力工具集（只读）——让对话模型"知道自己能调什么、什么时候调"。
 *
 * 设计要点：
 * 1. 能力目录（CAPABILITY_CATALOG）是唯一事实源，既注入 system prompt，也通过
 *    `system_capabilities` 工具供模型主动查询，避免模型凭印象声称"没有分析能力"。
 * 2. 所有工具只读：取数走 L1（/api/data/query），分析走 DSH 子代理
 *    （technical / macro / sentiment / valuation / risk / c_drive），
 *    历史验证走 6-TRADING 回测绑定；不提供下单、写库、改配置能力。
 * 3. 全部 FAIL-OPEN：失败返回 { ok:false, error }，由模型如实说明，不阻断对话。
 */
import { tool } from "ai";
import { z } from "zod";
import { callDshHandler } from "../dsh-execution-engine";
import { executeTradingBinding } from "../trading-capability";

export interface CapabilitySpec {
  /** 能力 ID（工具名或 DSH 模块名） */
  id: string;
  /** 人类可读名称 */
  name: string;
  /** 何时使用（写进 prompt 的路由依据） */
  when: string;
  /** 典型耗时，帮助模型决定是否组合调用 */
  latency: string;
}

export const CAPABILITY_CATALOG: CapabilitySpec[] = [
  {
    id: "query_market_data",
    name: "L1 确定性取数",
    when: "问到具体价格、涨跌幅、指标数值、成交量、市值、资金费率、宏观读数等可量化事实时先调用；分析类问题也必须先取数，禁止凭记忆编造行情。",
    latency: "2-15s",
  },
  {
    id: "run_analysis",
    name: "DSH 多维分析",
    when: "需要趋势/结构/多空判断、市场状态、宏观驱动、情绪温度、估值位置、风险与仓位约束时按维度调用；维度可并行组合。",
    latency: "10-25s/维度",
  },
  {
    id: "run_analysis:c_drive",
    name: "C-Drive 矛盾驱动",
    when: "多个维度结论冲突（技术面看多但资金面看空）、需要找出主要矛盾与主导方、或需要给出综合裁决时调用。",
    latency: "15-25s",
  },
  {
    id: "run_backtest",
    name: "6-TRADING 历史验证",
    when: "用户问某策略/形态在历史上是否有效、想验证假设、或需要用历史胜率支撑结论时调用。",
    latency: "30-180s",
  },
];

/** 注入 system prompt 的紧凑能力卡（避免 prompt 过长）。 */
export const CAPABILITY_PROMPT = [
  "【系统能力目录（只读）】",
  "- query_market_data：L1 确定性取数（行情/指标/宏观读数），分析前必须先取数。",
  "- run_analysis(dimensions=[technical|macro|sentiment|valuation|risk])：DSH 多维分析，可并行。",
  "- run_analysis(dimensions=[c_drive])：C-Drive 矛盾裁决，用于维度冲突或需要主导矛盾时。",
  "- run_backtest：6-TRADING 历史回测验证（慢，仅用户明确要验证时调用）。",
  "【调度规则】",
  "1. 任何价格/指标类事实先调 query_market_data，结果标注时间与来源。",
  "2. 趋势/结构类问题：至少组合 technical + sentiment（必要时加 macro），结论必须引用工具输出。",
  "3. 维度结论互相冲突时，追加 c_drive 给出主导矛盾；不要自行拼凑矛盾。",
  "4. 工具失败或数据缺失时，明确说明缺失项与降级范围，禁止用训练记忆补行情数字。",
  "5. 你没有下单、写库、改配置权限；但具备上述只读分析能力，不得声称\"无法分析\"。",
].join("\n");

const ANALYSIS_DIMENSIONS = [
  "technical",
  "macro",
  "sentiment",
  "valuation",
  "risk",
  "c_drive",
] as const;

/** 工具输出截断：避免单次工具结果撑爆上下文。 */
function clip(value: unknown, max = 4000): string {
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value);
  } catch {
    text = String(value);
  }
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max)}…(truncated)` : text;
}

function l1BaseUrl(): string {
  return process.env.L1_INTERNAL_BASE_URL?.trim() || "http://127.0.0.1:3001";
}

export function createCapabilityTools() {
  return {
    system_capabilities: tool({
      description:
        "返回当前系统可用的只读能力目录（名称、适用场景、耗时）。当不确定该调用哪个能力时先查这里。",
      inputSchema: z.object({}),
      execute: async () => ({ ok: true, capabilities: CAPABILITY_CATALOG }),
    }),

    query_market_data: tool({
      description:
        "通过 L1 确定性通道取真实数据（价格、涨跌幅、技术指标、宏观读数、资金费率等）。分析类问题必须先调用本工具取数。",
      inputSchema: z.object({
        question: z.string().describe("自然语言取数问题，例如：查询比特币价格"),
      }),
      execute: async ({ question }) => {
        try {
          const res = await fetch(new URL("/api/data/query", l1BaseUrl()), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: question }),
            signal: AbortSignal.timeout(20_000),
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
          return {
            ok: false,
            error: e instanceof Error ? e.message : "l1_query_failed",
          };
        }
      },
    }),

    run_analysis: tool({
      description:
        "调用 DSH 子代理做多维只读分析。dimensions 至少一个：technical(技术面/趋势结构)、macro(宏观驱动)、sentiment(情绪资金)、valuation(估值)、risk(风险/仓位约束)、c_drive(矛盾裁决)。",
      inputSchema: z.object({
        dimensions: z
          .array(z.enum(ANALYSIS_DIMENSIONS))
          .min(1)
          .describe("要执行的分析维度，可并行组合"),
        question: z.string().describe("用户原始问题"),
        symbol: z.string().optional().describe("标的，如 BTC / ETH / 600519.SH"),
        context: z
          .string()
          .optional()
          .describe("已取到的行情事实（建议把 query_market_data 的结果放这里）"),
      }),
      execute: async ({ dimensions, question, symbol, context }) => {
        const results = await Promise.all(
          dimensions.map(async (dim) => {
            const res = await callDshHandler(
              dim,
              { node_output: { question, symbol, context } },
              25_000,
            );
            return {
              dimension: dim,
              ok: res.ok === true,
              output: res.ok ? clip(res.output) : "",
              error: res.ok ? "" : res.error || `${dim}_no_output`,
            };
          }),
        );
        return { ok: results.some((r) => r.ok), results };
      },
    }),

    run_backtest: tool({
      description:
        "调用 6-TRADING 回测引擎做历史验证（较慢，30-180s）。仅当用户明确要验证策略/形态历史有效性时使用。",
      inputSchema: z.object({
        symbol: z.string().describe("标的，如 BTC / ETH / 600519.SH"),
        note: z.string().optional().describe("验证要点，用于回测参数说明"),
      }),
      execute: async ({ symbol, note }) => {
        const res = await executeTradingBinding("dream-backtest", {
          symbol,
          note,
        });
        return {
          ok: res.ok,
          source: res.source,
          output: res.ok ? clip(res.output) : "",
          error: res.ok ? "" : res.error || "backtest_failed",
        };
      },
    }),
  };
}

export type CapabilityTools = ReturnType<typeof createCapabilityTools>;
