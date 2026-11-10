/**
 * POST /api/agent/chat
 * 52-LobeHub 协议集成 Phase 1 — 内置 LLM 协议层入口（模型路由 + MCP 消费）。
 *
 * Body: { messages: UIMessage[], provider?: string, model?: string }
 *
 * 流程：resolveAgentModel（env 驱动）→ null 则 200 degraded 信封；
 * 否则 MCP client 取 cognition tools → streamText（stopWhen: stepCountIs(5)）
 * → toUIMessageStreamResponse()（供 @ai-sdk/react useChat 消费）。
 *
 * 边界（硬约束）：本层只做模型路由 + MCP 消费；禁止交易/策略/风控/记忆写能力；
 * 认知读写只经 L0 cognition 壳（写工具由服务端拒绝，天然只读）。
 *
 * FAIL-OPEN：任何异常/未配置 → 200 + { ok:false, data:null, degraded:true }，
 * 永不阻塞主链路。只读：GET/PUT/DELETE 返回 405。
 */
import { NextRequest, NextResponse } from 'next/server';
import { convertToModelMessages, stepCountIs, streamText } from 'ai';
import type { Tool, UIMessage } from 'ai';
import { resolveAgentModel } from '@/lib/agent/providers';
import { getCognitionMcpClient } from '@/lib/agent/mcp-client';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const SYSTEM_PROMPT = [
  '你是 DreamBuddy 内置协议层的对话助手。',
  '你只可使用已注册的 MCP 工具回答；工具结果须如实引用，不得编造。',
  '你没有交易、策略、风控或记忆写能力；认知查询仅通过 cognition 工具完成。',
].join('\n');

function degraded(reason: string) {
  return NextResponse.json({ ok: false, data: null, degraded: true, error: reason });
}

export async function POST(request: NextRequest) {
  let body: { messages?: UIMessage[]; provider?: string; model?: string };
  try {
    body = await request.json();
  } catch {
    return degraded('invalid_json_body');
  }

  if (!Array.isArray(body?.messages)) {
    return degraded('messages_required');
  }

  try {
    const model = resolveAgentModel({ provider: body.provider, model: body.model });
    if (!model) {
      // 未配置 AGENT_API_KEY / baseURL / 未知 provider → 降级信封，不阻塞前端
      return degraded('model_not_configured');
    }

    // MCP tools 获取失败不致命：退化为无工具对话
    let tools: Record<string, Tool> | undefined;
    try {
      tools = await getCognitionMcpClient().toAiSdkTools();
    } catch (e) {
      console.warn('[AgentChat] MCP tools 降级:', e instanceof Error ? e.message : e);
      tools = undefined;
    }

    const result = streamText({
      model,
      system: SYSTEM_PROMPT,
      messages: convertToModelMessages(body.messages),
      tools,
      stopWhen: stepCountIs(5),
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
