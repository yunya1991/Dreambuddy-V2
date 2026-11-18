/**
 * POST /api/agent/chat
 * 52-LobeHub 协议集成 Phase 1 — 内置 LLM 协议层入口（模型路由 + MCP 消费）。
 *
 * Body: { messages: UIMessage[], provider?: string, model?: string }
 *
 * 流程：L1 确定性直答优先（/api/data/query，命中则零 token 返回，不依赖 LLM）
 * → 未命中再 resolveAgentModel（env 驱动）→ null 则回显「模型未配置」文本流
 * → 否则 MCP client 取 cognition tools → streamText（stopWhen: stepCountIs(5)）
 * → toUIMessageStreamResponse()（供 @ai-sdk/react useChat 消费）。
 *
 * 边界（硬约束）：本层只做模型路由 + MCP 消费；禁止交易/策略/风控/记忆写能力；
 * 认知读写只经 L0 cognition 壳（写工具由服务端拒绝，天然只读）。
 *
 * FAIL-OPEN：任何异常/未配置 → 200 + { ok:false, data:null, degraded:true }，
 * 永不阻塞主链路。只读：GET/PUT/DELETE 返回 405。
 */
import { NextRequest, NextResponse } from "next/server";
import {
  convertToModelMessages,
  createUIMessageStream,
  createUIMessageStreamResponse,
  generateText,
  stepCountIs,
  streamText,
} from "ai";
import type { Tool, UIMessage } from "ai";
import { resolveAgentModel } from "@/lib/agent/providers";
import { getAgentMcpTools } from "@/lib/agent/mcp-multi-shell";
import {
  CAPABILITY_PROMPT,
  createCapabilityTools,
} from "@/lib/agent/capability-tools";
import {
  filterToolsByProfile,
  profileSystemPrompt,
  resolveToolProfile,
} from "@/lib/agent/tool-profiles";
import { isEntitled } from "@/lib/product/entitlement";
import {
  estimateChatCu,
  hasCompute,
  reserveCu,
  settleReservation,
  type UsageInput,
} from "@/lib/billing/meter";
import { maybeWriteSessionSummary } from "@/lib/agent/distill-outbox";
import {
  buildTakeoverContext,
  reviewL1Answer,
  type GateInput,
  type GateResult,
} from "@/lib/l1-answer-guard";
import { emitMonitorEvent } from "@/lib/monitor-bus";
import { createTraceHandle } from "@/lib/agent/run-trace";
import type { TraceSpan } from "@/types/run-trace";
import { randomUUID } from "crypto";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// 内层 L1 直答超时：必须大于 /api/data/query 的脚本上限（30s），
// 否则冷启动时内层先断，L1 结果永远拿不到而掉到未配置的 LLM 链路
const L1_TIMEOUT_MS = 32_000;

/** L1 门禁的统一提示（关闭 Agent 且 G1 fail 时使用） */
const L1_GATE_FAIL_HINT = "L1 无法可靠回答该问题，请开启 AI Agent 后重试。";

const SYSTEM_PROMPT = [
  "你是 DreamBuddy 内置协议层的对话助手。",
  "你只可使用已注册的工具回答；工具结果须如实引用，不得编造数字或行情。",
  "你具备只读分析能力（取数、多维度分析、矛盾裁决、历史回测），但没有下单、写库、改配置权限。",
  CAPABILITY_PROMPT,
].join("\n");

function degraded(reason: string) {
  return NextResponse.json({
    ok: false,
    data: null,
    degraded: true,
    error: reason,
  });
}

/** 取最后一条用户消息的纯文本（L1 只看当前问题，不拼历史）。 */
function extractLastUserText(messages: UIMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg?.role !== "user") continue;
    const text = (msg.parts ?? [])
      .filter((p): p is { type: "text"; text: string } => p?.type === "text")
      .map((p) => p.text)
      .join("")
      .trim();
    if (text) return text.slice(0, 2000);
  }
  return "";
}

/** 用 UIMessage 文本流回显一段纯文本（useChat 可直接渲染，避免 JSON 信封导致「无返回」）。 */
function textUiResponse(
  text: string,
  headers?: Record<string, string>,
  spans?: TraceSpan[],
) {
  const stream = createUIMessageStream({
    execute: ({ writer }) => {
      // 先回放已产生的调度轨迹，前端右侧时间线可与正文同时出现
      for (const span of spans ?? []) {
        writer.write({ type: "data-trace", id: span.span_id, data: span });
      }
      const id = randomUUID();
      writer.write({ type: "text-start", id });
      writer.write({ type: "text-delta", id, delta: text });
      writer.write({ type: "text-end", id });
    },
  });
  return createUIMessageStreamResponse({ stream, headers });
}

interface L1DirectResult {
  answer: string;
  intent: string;
  data: unknown;
  routeSignal: GateInput["routeSignal"];
}

/**
 * L1 确定性直答（零 token、不依赖模型）：命中且门控为 L1_DIRECT 时返回答案文本。
 * FAIL-OPEN：脚本超时/异常/未命中一律返回 null，继续走 L2 LLM。
 */
async function tryL1Direct(
  message: string,
  traceId: string,
): Promise<L1DirectResult | null> {
  const base =
    process.env.L1_INTERNAL_BASE_URL?.trim() || "http://127.0.0.1:3001";
  try {
    const res = await fetch(new URL("/api/data/query", base), {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-request-id": traceId },
      body: JSON.stringify({ message, trace_id: traceId }),
      signal: AbortSignal.timeout(L1_TIMEOUT_MS),
    });
    const json = (await res.json()) as {
      ok?: boolean;
      data?: {
        handled?: boolean;
        answer?: string;
        intent?: string;
        data?: unknown;
        route_signal?: GateInput["routeSignal"];
      };
    };
    const data = json?.data;
    const decision = String(data?.route_signal?.decision ?? "").toUpperCase();
    const answer = typeof data?.answer === "string" ? data.answer.trim() : "";
    if (
      json?.ok === true &&
      data?.handled === true &&
      decision === "L1_DIRECT" &&
      answer
    ) {
      return {
        answer,
        intent: String(data?.intent ?? "unknown"),
        data: data?.data,
        routeSignal: data?.route_signal,
      };
    }
    return null;
  } catch (e) {
    console.warn(
      "[AgentChat] L1 直答降级:",
      e instanceof Error ? e.message : e,
    );
    return null;
  }
}

/**
 * L2 门禁 judge（G3 灰区轻审）：低延迟模型由 AGENT_JUDGE_MODEL 指定，
 * 未配置时沿用 AGENT_MODEL；仍缺配置 → 抛错，由 guard 按 timeout 放行。
 */
async function judgeL1Answer(prompt: string): Promise<string> {
  const model = resolveAgentModel({
    model: process.env.AGENT_JUDGE_MODEL?.trim() || undefined,
  });
  if (!model) throw new Error("judge_model_unavailable");
  const { text } = await generateText({
    model,
    prompt,
    temperature: 0,
    maxOutputTokens: 200,
  });
  return text;
}

function gateHeaders(gate: GateResult): Record<string, string> {
  const headers: Record<string, string> = {
    "x-l1-gate": gate.verdict,
    "x-l1-gate-ms": String(gate.gateMs),
  };
  if (gate.reasons.length > 0) {
    headers["x-l1-gate-reasons"] = gate.reasons.join(",").slice(0, 300);
  }
  return headers;
}

/** 门禁结果打点（FAIL-OPEN：监控失败绝不影响主链路） */
function emitGateEvent(
  traceId: string,
  gate: GateResult,
  agentEnabled: boolean,
) {
  try {
    emitMonitorEvent({
      trace_id: traceId,
      uid: "anonymous",
      layer: "router",
      phase: "routed",
      status: gate.verdict === "fail" ? "denied" : "completed",
      intent: "l1_gate",
      duration_ms: gate.gateMs,
      message_preview: `l1_gate=${gate.verdict}${agentEnabled ? "+agent" : ""}`,
      extra: {
        verdict: gate.verdict,
        reasons: gate.reasons,
        missing: gate.missing,
        judge_ms: gate.judgeMs,
      },
    });
  } catch {
    /* ignore */
  }
}

/**
 * 给流式响应注入 SSE 心跳注释（每 3s 一行 `: keepalive`）。
 * 模型首 token 前有 10s+ 静默，移动网络/企业代理会按空闲超时掐断连接，
 * 浏览器侧表现为 "network error"。心跳不进入 UIMessage 协议，客户端解析器会忽略。
 */
function withHeartbeat(response: Response, intervalMs = 3000): Response {
  const body = response.body;
  if (!body) return response;
  const reader = body.getReader();
  const encoder = new TextEncoder();
  let timer: ReturnType<typeof setInterval> | null = null;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      timer = setInterval(() => {
        try {
          controller.enqueue(encoder.encode(": keepalive\n\n"));
        } catch {
          if (timer) clearInterval(timer);
        }
      }, intervalMs);
    },
    async pull(controller) {
      const { done, value } = await reader.read();
      if (done) {
        if (timer) clearInterval(timer);
        controller.close();
        return;
      }
      controller.enqueue(value);
    },
    cancel(reason) {
      if (timer) clearInterval(timer);
      void reader.cancel(reason).catch(() => {});
    },
  });

  const headers = new Headers(response.headers);
  headers.set("X-Accel-Buffering", "no");
  return new Response(stream, { status: response.status, headers });
}

export async function POST(request: NextRequest) {
  let body: {
    messages?: UIMessage[];
    provider?: string;
    model?: string;
    /** 对话来源；profile 由服务端按产品开通状态决定，前端不能自选 profile */
    surface?: "workbench" | "trading";
    /** AI Agent 开关：false = 只走 L1 确定性直答；true = 允许大模型并按积分结算 */
    agent_enabled?: boolean;
  };
  try {
    body = await request.json();
  } catch {
    return degraded("invalid_json_body");
  }

  if (!Array.isArray(body?.messages)) {
    return degraded("messages_required");
  }

  const traceId = request.headers.get("x-request-id")?.trim() || randomUUID();
  // 未传 agent_enabled 的旧客户端保持原行为（视为开启）
  const agentEnabled = body.agent_enabled !== false;
  /** L1 门禁失败后注入给 L2 的接管上下文（非空即表示本次由 L2 接管） */
  let takeoverContext: string | null = null;

  // L1 确定性直答优先：行情/数据/技术面等意图命中时零 token 返回，不依赖 LLM 配置。
  // AI Agent 开启时，L1 直答必须先过 L2 门禁（G1 规则门 + G3 灰区轻审）；
  // 判定 fail → 同一路由接管重答（agent 开）或统一提示（agent 关）。
  const userText = extractLastUserText(body.messages);
  /** O0 调度轨迹：与 reasoning 同流透传，前端右侧时间线消费 */
  const trace = createTraceHandle(traceId);
  if (userText) {
    const endS1 = trace.start("S1", "意图识别与 L1 试探");
    const l1 = await tryL1Direct(userText, traceId);
    endS1(l1 ? "done" : "skipped", l1 ? `L1 命中：${l1.intent}` : "未命中，转 L2");
    if (l1) {
      const gateInput: GateInput = {
        message: userText,
        intent: l1.intent,
        answer: l1.answer,
        data: l1.data,
        routeSignal: l1.routeSignal,
      };
      const endGate = trace.start("A1", "L1 门禁复核", { role: "gate" });
      const gate = await reviewL1Answer(gateInput, {
        allowJudge: agentEnabled,
        judge: agentEnabled ? judgeL1Answer : undefined,
      });
      endGate(
        gate.verdict === "fail" ? "failed" : "done",
        gate.reasons.join(",") || gate.verdict,
      );
      const headers = gateHeaders(gate);
      emitGateEvent(traceId, gate, agentEnabled);

      if (gate.verdict !== "fail") {
        trace.start("L1", "L1 确定性直答", { role: "l1" })("done", l1.intent);
        trace.start("G1", "输出简报", { role: "g" })("done", "未调用大模型");
        return textUiResponse(l1.answer, headers, trace.history);
      }
      if (!agentEnabled) {
        trace.start("G1", "输出简报", { role: "g" })("done", "门禁未过且 Agent 关闭");
        return textUiResponse(L1_GATE_FAIL_HINT, headers, trace.history);
      }
      takeoverContext = buildTakeoverContext(gateInput, gate);
      console.info(
        "[AgentChat] L1 门禁未通过，L2 接管:",
        gate.reasons.join(",") || "unknown",
      );
    }
  }

  // 关闭 AI Agent：只保留 L1 规则回答，不调用大模型、不产生积分。
  // 未传 agent_enabled 的旧客户端保持原行为（向后兼容）。
  if (body.agent_enabled === false) {
    return textUiResponse(
      "AI Agent 未启用：当前只回答规则类问题。\n\n打开工作台右上角「AI Agent」开关后可使用完整推理（按 token 扣积分）。",
    );
  }

  try {
    const model = resolveAgentModel({
      provider: body.provider,
      model: body.model,
    });
    if (!model) {
      if (takeoverContext) {
        return textUiResponse(
          "L1 回答未通过复核，但当前未配置对话模型（AGENT_API_KEY / AGENT_BASE_URL），无法由 L2 接管重答。",
          { "x-l1-gate": "fail", "x-l2-takeover": "1" },
        );
      }
      // 未配置 AGENT_API_KEY / baseURL：用文本流显式告知（JSON 信封会让 useChat 静默无返回）
      return textUiResponse(
        "当前未配置对话模型（AGENT_API_KEY / AGENT_BASE_URL），只能回答 L1 确定性查询（行情、数据、技术面、风控等）。\n\n请先在服务端配置模型后再试。",
      );
    }

    // AI Agent 显式启用时才校验积分；余额不足直接拒绝，避免静默降级
    if (body.agent_enabled === true && !(await hasCompute())) {
      return NextResponse.json(
        {
          ok: false,
          data: null,
          error: {
            code: "INSUFFICIENT_CU",
            message: "AI Agent 积分不足，请充值后再启用。",
          },
        },
        { status: 403 },
      );
    }

    // SPEC-52 F4：交易产品零余额锁定（平台只读仍可用）
    if (body.surface === "trading" && !(await hasCompute())) {
      return NextResponse.json(
        {
          ok: false,
          data: null,
          error: {
            code: "INSUFFICIENT_CU",
            message: "CU 余额不足，交易产品已锁定。",
          },
        },
        { status: 403 },
      );
    }

    // SPEC-52 F6：服务端注入工具 profile（前端只声明 surface，不自选 profile）
    const profile = resolveToolProfile({
      surface: body.surface === "trading" ? "trading" : "workbench",
      entitled: isEntitled(),
    });

    // 系统能力工具（只读分析）始终可用；MCP tools 失败不致命，退化为仅能力工具
    const endS2 = trace.start("S2", "上下文与工具准备");
    const capabilityTools = createCapabilityTools(trace);
    let tools: Record<string, Tool> = { ...capabilityTools };
    try {
      const allTools = await getAgentMcpTools();
      tools = { ...capabilityTools, ...filterToolsByProfile(allTools, profile) };
    } catch (e) {
      console.warn(
        "[AgentChat] MCP tools 降级:",
        e instanceof Error ? e.message : e,
      );
    }
    endS2("done", `${Object.keys(tools).length} 个工具可用`);

    // SPEC-52 F4：预扣 → 结算（账本只追加；未产生 usage 时预扣自动释放）
    const reservation = reserveCu(traceId, estimateChatCu(0));

    const system = [
      SYSTEM_PROMPT,
      profileSystemPrompt(profile),
      takeoverContext ?? "",
    ]
      .filter(Boolean)
      .join("\n");

    const endL2 = trace.start("L2", "模型推理", { role: profile.id });
    const result = streamText({
      model,
      system,
      messages: convertToModelMessages(body.messages),
      tools,
      stopWhen: stepCountIs(5),
      onFinish: async (event) => {
        endL2(
          "done",
          `steps=${event.steps.length} tokens=${event.usage?.inputTokens ?? 0}/${event.usage?.outputTokens ?? 0}`,
        );
        // Phase 3 蒸馏桥出口：会话轮数 ≥2 且有实质工具结果时写 session_summary 到 outbox。
        // FAIL-OPEN：maybeWriteSessionSummary 内部已 catch，此处再兜底绝不影响流响应。
        try {
          const hasToolResults = event.steps.some(
            (s) => s.toolResults.length > 0,
          );
          maybeWriteSessionSummary({
            messages: body.messages ?? [],
            hasToolResults,
          });
        } catch (e) {
          console.warn(
            "[AgentChat] distill outbox 失败（FAIL-OPEN）:",
            e instanceof Error ? e.message : e,
          );
        }

        // SPEC-52 F4：按实际 token / 工具调用结算
        try {
          const inputTokens = event.usage?.inputTokens ?? 0;
          const outputTokens = event.usage?.outputTokens ?? 0;
          const toolCalls = event.steps.reduce(
            (count, step) => count + step.toolCalls.length,
            0,
          );
          const inputs: UsageInput[] = [];
          if (inputTokens > 0)
            inputs.push({
              dimension: "llm_input",
              quantity: inputTokens,
              ref: "agent_chat",
            });
          if (outputTokens > 0)
            inputs.push({
              dimension: "llm_output",
              quantity: outputTokens,
              ref: "agent_chat",
            });
          if (toolCalls > 0)
            inputs.push({
              dimension: "tool_call",
              quantity: toolCalls,
              ref: profile.id,
            });
          await settleReservation(reservation, inputs);
        } catch (e) {
          console.warn(
            "[AgentChat] usage 结算失败（FAIL-OPEN）:",
            e instanceof Error ? e.message : e,
          );
        }

        // O0：输出阶段打点（写入失败由 emit 内部吞掉，不影响已完成的响应）
        trace.start("G1", "汇总输出", { role: "g" })(
          "done",
          `工具调用 ${event.steps.reduce(
            (count, step) => count + step.toolCalls.length,
            0,
          )} 次`,
        );
      },
    });
    // 轨迹与 reasoning 共用一条 UIMessage 流：前端无需额外连接
    const uiStream = createUIMessageStream({
      execute: async ({ writer }) => {
        trace.attach((span) => {
          writer.write({ type: "data-trace", id: span.span_id, data: span });
        });
        // 回放 attach 之前的阶段（S1/S2），随后由 sink 实时追加
        for (const span of trace.history) {
          writer.write({ type: "data-trace", id: span.span_id, data: span });
        }
        writer.merge(result.toUIMessageStream({ sendReasoning: true }));
      },
    });
    return withHeartbeat(
      createUIMessageStreamResponse({
        stream: uiStream,
        headers: takeoverContext ? { "x-l2-takeover": "1" } : undefined,
      }),
    );
  } catch (e) {
    // FAIL-OPEN：模型调用/网络异常不阻塞主链路
    console.warn("[AgentChat] degraded:", e instanceof Error ? e.message : e);
    return degraded(e instanceof Error ? e.message : "agent_chat_failed");
  }
}

export async function GET() {
  return NextResponse.json(
    {
      error: "Method Not Allowed",
      message: "/api/agent/chat accepts POST only",
    },
    { status: 405 },
  );
}

export async function PUT() {
  return NextResponse.json(
    {
      error: "Method Not Allowed",
      message: "/api/agent/chat accepts POST only",
    },
    { status: 405 },
  );
}

export async function DELETE() {
  return NextResponse.json(
    {
      error: "Method Not Allowed",
      message: "/api/agent/chat accepts POST only",
    },
    { status: 405 },
  );
}
