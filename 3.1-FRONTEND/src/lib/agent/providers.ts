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
import type { LanguageModel } from 'ai';

export type AgentProviderKind = 'openai' | 'openai-compatible';

export interface ResolveModelOptions {
  provider?: string;
  model?: string;
}

/**
 * 解析模型实例。未配置 API key / 缺 baseURL / 未知 provider → null（FAIL-OPEN）。
 * 本函数只构建 provider 实例，不发网络请求。
 */
export function resolveAgentModel(opts: ResolveModelOptions = {}): LanguageModel | null {
  const provider = (opts.provider ?? process.env.AGENT_PROVIDER ?? 'openai-compatible').trim();
  const apiKey = process.env.AGENT_API_KEY?.trim();
  if (!apiKey) return null;

  if (provider === 'openai') {
    const modelName = (opts.model ?? process.env.AGENT_MODEL ?? 'gpt-4o-mini').trim();
    const openai = createOpenAI({ apiKey });
    return openai(modelName);
  }

  if (provider === 'openai-compatible') {
    const baseURL = process.env.AGENT_BASE_URL?.trim();
    if (!baseURL) return null;
    const modelName = (opts.model ?? process.env.AGENT_MODEL ?? 'qwen-plus').trim();
    // @ai-sdk/openai 以自定义 baseURL 兼容所有 OpenAI 协议端点
    const compat = createOpenAI({ baseURL, apiKey, name: 'openai-compatible' });
    return compat(modelName);
  }

  // 未知 provider → 降级
  return null;
}
