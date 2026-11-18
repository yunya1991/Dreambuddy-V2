/**
 * 52-LobeHub 协议集成 Phase 1 — 模型工厂（env 驱动）。
 *
 * 环境变量：
 *   AGENT_PROVIDER    openai | openai-compatible（默认 openai-compatible）
 *   AGENT_MODEL       模型名（openai 默认 gpt-4o-mini；compatible 默认 qwen-plus）
 *   AGENT_API_KEY     API key（缺失 → 返回 null，路由层走 degraded 信封）
 *   AGENT_BASE_URL    openai-compatible 必填（覆盖 Qwen/DeepSeek/Moonshot/ollama/vllm/本地网关）
 *
 * 说明：anthropic / google 原生 provider 属后续可选依赖（Phase 2+），
 * 当前通过 openai-compatible 网关即可覆盖绝大多数模型，不新增依赖。
 */
import { createOpenAI } from '@ai-sdk/openai';
import { extractReasoningMiddleware, wrapLanguageModel } from 'ai';
import type { LanguageModel } from 'ai';

export type AgentProviderKind = 'openai' | 'openai-compatible';

export interface ResolveModelOptions {
  provider?: string;
  model?: string;
  /** 覆盖 AGENT_BASE_URL（评审/门禁模型可与 worker 异构） */
  baseURL?: string;
  /** 覆盖 AGENT_API_KEY */
  apiKey?: string;
}

/**
 * DeepSeek 等 OpenAI 兼容网关把思维链放在 delta.reasoning_content，
 * 而 @ai-sdk/openai 不识别该字段（直接丢弃，前端因此看不到思考过程）。
 * 这里在 fetch 层把它搬进 delta.content 并用 <think> 包裹，
 * 再由 extractReasoningMiddleware 拆回 reasoning part。无该字段时是 no-op。
 */
function createReasoningShimFetch(baseFetch: typeof fetch): typeof fetch {
  return async (input, init) => {
    const response = await baseFetch(input, init);
    const contentType = response.headers.get('content-type') ?? '';
    if (!response.body || !contentType.includes('text/event-stream')) {
      return response;
    }

    const decoder = new TextDecoder();
    const encoder = new TextEncoder();
    let buffer = '';
    let inThink = false;

    const rewriteLine = (line: string): string => {
      if (!line.startsWith('data:')) return line;
      const payload = line.slice(5).trim();
      if (!payload || payload === '[DONE]') return line;
      try {
        const json = JSON.parse(payload) as {
          choices?: Array<{ delta?: Record<string, unknown> }>;
        };
        if (!Array.isArray(json.choices)) return line;
        for (const choice of json.choices) {
          const delta = choice?.delta;
          if (!delta) continue;
          const reasoning = delta.reasoning_content;
          if (typeof reasoning === 'string' && reasoning.length > 0) {
            delete delta.reasoning_content;
            delta.content = `${inThink ? '' : '<think>'}${reasoning}`;
            inThink = true;
            continue;
          }
          const content = delta.content;
          if (inThink && typeof content === 'string' && content.length > 0) {
            delta.content = `</think>${content}`;
            inThink = false;
          }
        }
        return `data: ${JSON.stringify(json)}`;
      } catch {
        return line;
      }
    };

    const transform = new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        buffer += decoder.decode(chunk, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          controller.enqueue(encoder.encode(`${rewriteLine(line)}\n`));
        }
      },
      flush(controller) {
        if (buffer) controller.enqueue(encoder.encode(rewriteLine(buffer)));
      },
    });

    // 已由 fetch 解压过：长度/编码头必须去掉，否则客户端会按旧长度截断
    const headers = new Headers(response.headers);
    headers.delete('content-encoding');
    headers.delete('content-length');

    return new Response(response.body.pipeThrough(transform), {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  };
}

/** reasoning part 拆分：<think>…</think> → reasoning，其余保持 text */
const REASONING_MIDDLEWARE = extractReasoningMiddleware({ tagName: 'think' });

/**
 * 解析模型实例。未配置 API key / 缺 baseURL / 未知 provider → null（FAIL-OPEN）。
 * 本函数只构建 provider 实例，不发网络请求。
 */
export function resolveAgentModel(opts: ResolveModelOptions = {}): LanguageModel | null {
  const provider = (opts.provider ?? process.env.AGENT_PROVIDER ?? 'openai-compatible').trim();
  const apiKey = opts.apiKey?.trim() || process.env.AGENT_API_KEY?.trim();
  if (!apiKey) return null;

  if (provider === 'openai') {
    const modelName = (opts.model ?? process.env.AGENT_MODEL ?? 'gpt-4o-mini').trim();
    const openai = createOpenAI({
      apiKey,
      fetch: createReasoningShimFetch(globalThis.fetch),
    });
    return wrapLanguageModel({
      model: openai(modelName),
      middleware: REASONING_MIDDLEWARE,
    });
  }

  if (provider === 'openai-compatible') {
    const baseURL = opts.baseURL?.trim() || process.env.AGENT_BASE_URL?.trim();
    if (!baseURL) return null;
    const modelName = (opts.model ?? process.env.AGENT_MODEL ?? 'qwen-plus').trim();
    // @ai-sdk/openai 以自定义 baseURL 兼容所有 OpenAI 协议端点
    const compat = createOpenAI({
      baseURL,
      apiKey,
      name: 'openai-compatible',
      fetch: createReasoningShimFetch(globalThis.fetch),
    });
    // 必须显式走 Chat Completions：@ai-sdk/openai v2 的默认入口是 Responses API，
    // DeepSeek 在该接口只回传 encrypted reasoning（前端拿不到可读思维链）。
    // Chat Completions 会返回 delta.reasoning_content，由上面的 shim + 中间件转成 reasoning part。
    return wrapLanguageModel({
      model: compat.chat(modelName),
      middleware: REASONING_MIDDLEWARE,
    });
  }

  // 未知 provider → 降级
  return null;
}
