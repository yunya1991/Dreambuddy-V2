/**
 * llm-config.ts — 网关 LLM 配置单一真源
 * PROP-20260828B · Phase 2（Z1 补查①：三份配置归一）
 *
 * 修复历史：
 *   - 2026-08-28 前：chat route / fallback-engine / llm-bridge 三份独立配置，
 *     deepseek 兜底端点分歧（/v1 vs 无 /v1）
 *   - 归一后：本模块为 env 解析唯一入口；
 *     deepseek 端点正典 = https://api.deepseek.com/chat/completions
 *     （DeepSeek 官方 base_url 即含版本路径，无需 /v1；与 llm-bridge PROVIDER_DEFAULTS 对齐）
 */

export interface GatewayLLMConfig {
  apiKey: string;
  endpoint: string;
  model: string;
}

/** 端点正典：无 /v1（DeepSeek 官方 base_url 语义） */
export const DEEPSEEK_CANONICAL_ENDPOINT = 'https://api.deepseek.com/chat/completions';

/**
 * 解析当前生效的 LLM 配置：DashScope(百炼) 优先，DeepSeek 兜底。
 * 端点统一拼接 /chat/completions（去掉尾部斜杠）。
 */
export function getGatewayLLMConfig(): GatewayLLMConfig {
  const apiKey = process.env.DASHSCOPE_API_KEY || process.env.DEEPSEEK_API_KEY || '';
  const endpoint = process.env.DASHSCOPE_BASE_URL
    ? process.env.DASHSCOPE_BASE_URL.replace(/\/+$/, '') + '/chat/completions'
    : DEEPSEEK_CANONICAL_ENDPOINT;
  const model = process.env.DASHSCOPE_MODEL || process.env.DEEPSEEK_MODEL || 'deepseek-v4-pro';
  return { apiKey, endpoint, model };
}
