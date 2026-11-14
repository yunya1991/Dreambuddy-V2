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
import { NextRequest, NextResponse } from 'next/server';
import {
  convertToModelMessages,
  createUIMessageStream,
  createUIMessageStreamResponse,
  stepCountIs,
  streamText,
} from 'ai';
import type { Tool, UIMessage } from 'ai';
import { resolveAgentModel } from '@/lib/agent/providers';
import { getCognitionMcpClient } from '@/lib/agent/mcp-client';
import { filterToolsByProfile, profileSystemPrompt, resolveToolProfile } from '@/lib/agent/tool-profiles';
import { isEntitled } from '@/lib/product/entitlement';
import {
  estimateChatCu,
  hasCompute,
  reserveCu,
  settleReservation,
  type UsageInput,
} from '@/lib/billing/meter';
import { maybeWriteSessionSummary } from '@/lib/agent/distill-outbox';
import { randomUUID } from 'crypto';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// 内层 L1 直答超时：必须大于 /api/data/query 的脚本上限（15s），
// 否则冷启动时内层先断，L1 结果永远拿不到而掉到未配置的 LLM 链路
const L1_TIMEOUT_MS = 16_000;

const SYSTEM_PROMPT = [
  '你是 DreamBuddy 内置协议层的对话助手。',
  '你只可使用已注册的 MCP 工具回答；工具结果须如实引用，不得编造。',
  '你没有交易、策略、风控或记忆写能力；认知查询仅通过 cognition 工具完成。',
].join('\n');

function degraded(reason: string) {
  return NextResponse.json({ ok: false, data: null, degraded: true, error: reason });
}

/** 取最后一条用户消息的纯文本（L1 只看当前问题，不拼历史）。 */
function extractLastUserText(messages: UIMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg?.role !== 'user') continue;
    const text = (msg.parts ?? [])
      .filter((p): p is { type: 'text'; text: string } => p?.type === 'text')
      .map((p) => p.text)
      .join('')
      .trim();
    if (text) return text.slice(0, 2000);
  }
  return '';
}

/** 用 UIMessage 文本流回显一段纯文本（useChat 可直接渲染，避免 JSON 信封导致「无返回」）。 */
function textUiResponse(text: string) {
  const stream = createUIMessageStream({
    execute: ({ writer }) => {
      const id = randomUUID();
      writer.write({ type: 'text-start', id });
      writer.write({ type: 'text-delta', id, delta: text });
      writer.write({ type: 'text-end', id });
    },
  });
  return createUIMessageStreamResponse({ stream });
}

/**
 * L1 确定性直答（零 token、不依赖模型）：命中且门控为 L1_DIRECT 时返回答案文本。
 * FAIL-OPEN：脚本超时/异常/未命中一律返回 null，继续走 L2 LLM。
 */
async function tryL1Direct(message: string, traceId: string): Promise<string | null> {
  const base = process.env.L1_INTERNAL_BASE_URL?.trim() || 'http://127.0.0.1:3001';
  try {
    const res = await fetch(new URL('/api/data/query', base), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-request-id': traceId },
      body: JSON.stringify({ message, trace_id: traceId }),
      signal: AbortSignal.timeout(L1_TIMEOUT_MS),
    });
    const json = (await res.json()) as {
      ok?: boolean;
      data?: {
        handled?: boolean;
        answer?: string;
        route_signal?: { decision?: string };
      };
    };
    const data = json?.data;
    const decision = String(data?.route_signal?.decision ?? '').toUpperCase();
    const answer = typeof data?.answer === 'string' ? data.answer.trim() : '';
    if (json?.ok === true && data?.handled === true && decision === 'L1_DIRECT' && answer) {
      return answer;
    }
    return null;
  } catch (e) {
    console.warn('[AgentChat] L1 直答降级:', e instanceof Error ? e.message : e);
    return null;
  }
}

export async function POST(request: NextRequest) {
  let body: {
    messages?: UIMessage[];
    provider?: string;
    model?: string;
    /** 对话来源；profile 由服务端按产品开通状态决定，前端不能自选 profile */
    surface?: 'workbench' | 'trading';
  };
  try {
    body = await request.json();
  } catch {
    return degraded('invalid_json_body');
  }

  if (!Array.isArray(body?.messages)) {
    return degraded('messages_required');
  }

  const traceId = request.headers.get('x-request-id')?.trim() || randomUUID();

  // L1 确定性直答优先：行情/数据/技术面等意图命中时零 token 返回，不依赖 LLM 配置
  const userText = extractLastUserText(body.messages);
  if (userText) {
    const l1Answer = await tryL1Direct(userText, traceId);
    if (l1Answer) return textUiResponse(l1Answer);
  }

  try {
    const model = resolveAgentModel({ provider: body.provider, model: body.model });
    if (!model) {
      // 未配置 AGENT_API_KEY / baseURL：用文本流显式告知（JSON 信封会让 useChat 静默无返回）
      return textUiResponse(
        '当前未配置对话模型（AGENT_API_KEY / AGENT_BASE_URL），只能回答 L1 确定性查询（行情、数据、技术面、风控等）。\n\n请先在服务端配置模型后再试。',
      );
    }

    // SPEC-52 F4：交易产品零余额锁定（平台只读仍可用）
    if (body.surface === 'trading' && !(await hasCompute())) {
      return NextResponse.json(
        {
          ok: false,
          data: null,
          error: { code: 'INSUFFICIENT_CU', message: 'CU 余额不足，交易产品已锁定。' },
        },
        { status: 403 },
      );
    }

    // SPEC-52 F6：服务端注入工具 profile（前端只声明 surface，不自选 profile）
    const profile = resolveToolProfile({
      surface: body.surface === 'trading' ? 'trading' : 'workbench',
      entitled: isEntitled(),
    });

    // MCP tools 获取失败不致命：退化为无工具对话
    let tools: Record<string, Tool> | undefined;
    try {
      const allTools = await getCognitionMcpClient().toAiSdkTools();
      tools = filterToolsByProfile(allTools, profile);
    } catch (e) {
      console.warn('[AgentChat] MCP tools 降级:', e instanceof Error ? e.message : e);
      tools = undefined;
    }

    // SPEC-52 F4：预扣 → 结算（账本只追加；未产生 usage 时预扣自动释放）
    const reservation = reserveCu(traceId, estimateChatCu(0));

    const result = streamText({
      model,
      system: `${SYSTEM_PROMPT}\n${profileSystemPrompt(profile)}`,
      messages: convertToModelMessages(body.messages),
      tools,
      stopWhen: stepCountIs(5),
      onFinish: async (event) => {
        // Phase 3 蒸馏桥出口：会话轮数 ≥2 且有实质工具结果时写 session_summary 到 outbox。
        // FAIL-OPEN：maybeWriteSessionSummary 内部已 catch，此处再兜底绝不影响流响应。
        try {
          const hasToolResults = event.steps.some((s) => s.toolResults.length > 0);
          maybeWriteSessionSummary({ messages: body.messages ?? [], hasToolResults });
        } catch (e) {
          console.warn('[AgentChat] distill outbox 失败（FAIL-OPEN）:', e instanceof Error ? e.message : e);
        }

        // SPEC-52 F4：按实际 token / 工具调用结算
        try {
          const inputTokens = event.usage?.inputTokens ?? 0;
          const outputTokens = event.usage?.outputTokens ?? 0;
          const toolCalls = event.steps.reduce((count, step) => count + step.toolCalls.length, 0);
          const inputs: UsageInput[] = [];
          if (inputTokens > 0) inputs.push({ dimension: 'llm_input', quantity: inputTokens, ref: 'agent_chat' });
          if (outputTokens > 0) inputs.push({ dimension: 'llm_output', quantity: outputTokens, ref: 'agent_chat' });
          if (toolCalls > 0) inputs.push({ dimension: 'tool_call', quantity: toolCalls, ref: profile.id });
          await settleReservation(reservation, inputs);
        } catch (e) {
          console.warn('[AgentChat] usage 结算失败（FAIL-OPEN）:', e instanceof Error ? e.message : e);
        }
      },
    });
    return result.toUIMessageStreamResponse();
  } catch (e) {
    // FAIL-OPEN：模型调用/网络异常不阻塞主链路
    console.warn('[AgentChat] degraded:', e instanceof Error ? e.message : e);
    return degraded(e instanceof Error ? e.message : 'agent_chat_failed');
  }
}

export async function GET() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/agent/chat accepts POST only' },
    { status: 405 },
  );
}

export async function PUT() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/agent/chat accepts POST only' },
    { status: 405 },
  );
}

export async function DELETE() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/agent/chat accepts POST only' },
    { status: 405 },
  );
}
