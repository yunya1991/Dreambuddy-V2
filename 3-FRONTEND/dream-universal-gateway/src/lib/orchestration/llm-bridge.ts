/**
 * LLM 桥接层
 *
 * 从 api_configs 表读取用户配置的 LLM 凭证（category=LLM），
 * 解密后注入到 LLM 请求中。支持 OpenAI/DeepSeek/百炼/Claude 等多提供商。
 * 如果用户未配置 LLM，降级到 process.env.DEEPSEEK_API_KEY。
 *
 * 多凭证降级（2026-09-06）：getLLMCredentials 返回所有已验证配置（createdAt desc），
 * callLLM 依次尝试，遇 402（余额不足）/401（认证失败）自动降级到下一个凭证；
 * 末尾追加 .env 兜底。非凭证错误（超时/500/网络）直接抛出，不降级。
 */

import { prisma } from '@/lib/prisma';
import { decrypt, encrypt } from '@/lib/encryption';

// ============================================================
// 类型定义
// ============================================================

export interface LLMFunctionDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface LLMCallOptions {
  prompt: string;
  systemPrompt?: string;
  temperature?: number;
  maxTokens?: number;
  timeoutMs?: number;
  functions?: LLMFunctionDefinition[];
  functionCall?: 'auto' | 'none' | string;
}

export interface LLMFunctionCall {
  name: string;
  arguments: Record<string, unknown>;
}

export interface LLMCallResult {
  content: string;
  model: string;
  tokensUsed: number;
  latencyMs: number;
  functionCall?: LLMFunctionCall | null;
}

interface LLMCredential {
  provider: string;
  apiKey: string;
  baseUrl?: string;
  model?: string;
}

/** 携带 HTTP status 的调用错误，用于精确识别 402/401 触发降级 */
class LLMHTTPError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'LLMHTTPError';
  }
}

/** 触发自动降级的 HTTP 状态码：402=余额不足，401=认证失败 */
const FALLBACK_STATUS_CODES = new Set([401, 402]);

// ============================================================
// 提供商配置
// ============================================================

/** 各提供商的默认 API 端点和模型 */
const PROVIDER_DEFAULTS: Record<string, { endpoint: string; model: string }> = {
  openai: { endpoint: 'https://api.openai.com/v1/chat/completions', model: 'gpt-4o' },
  deepseek: { endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-chat' },
  dashscope: { endpoint: 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions', model: 'qwen3.8-max' },
  anthropic: { endpoint: 'https://api.anthropic.com/v1/messages', model: 'claude-sonnet-4-20250514' },
  custom: { endpoint: '', model: 'gpt-4o' },
};

// ============================================================
// 凭证获取
// ============================================================

/**
 * 从数据库获取用户配置的所有可用 LLM 凭证（按 createdAt desc 排序）
 * 仅返回 isVerified=true 的配置；解密失败的配置尝试用环境变量 key 重新加密恢复。
 */
async function getLLMCredentials(uid?: string): Promise<LLMCredential[]> {
  // 开发环境使用固定 uid
  const effectiveUid = uid || process.env.DEV_ROUTE_UID || 'dev-user';
  const results: LLMCredential[] = [];

  try {
    // 优先按 uid 查找所有已验证配置
    let configs = await prisma.apiConfig.findMany({
      where: {
        uid: effectiveUid,
        category: 'LLM',
        isVerified: true,
      },
      orderBy: { createdAt: 'desc' },
    });

    // 开发环境降级：如果指定 uid 找不到，读取任何已验证的 LLM 配置
    if (configs.length === 0) {
      configs = await prisma.apiConfig.findMany({
        where: {
          category: 'LLM',
          isVerified: true,
        },
        orderBy: { createdAt: 'desc' },
      });
    }

    for (const config of configs) {
      try {
        const decrypted = decrypt(config.encryptedData, config.iv, config.authTag);
        const credentials = JSON.parse(decrypted) as { apiKey?: string; model?: string };

        if (credentials.apiKey) {
          results.push({
            provider: config.provider,
            apiKey: credentials.apiKey,
            baseUrl: config.baseUrl || undefined,
            model: credentials.model || undefined,
          });
        }
      } catch (decryptError) {
        // 数据库凭证解密失败（如 ENCRYPTION_KEY 变更）→ 用环境变量 key 重新加密并更新
        console.warn(`[llm-bridge] 配置 ${config.provider}(${config.id}) 解密失败，尝试用环境变量 key 重新加密`, decryptError);
        const envApiKey = process.env.DEEPSEEK_API_KEY;
        if (envApiKey) {
          try {
            const newCreds = JSON.stringify({ apiKey: envApiKey, model: 'deepseek-chat' });
            const newEnc = encrypt(newCreds);
            await prisma.apiConfig.update({
              where: { id: config.id },
              data: {
                encryptedData: newEnc.encryptedData,
                iv: newEnc.iv,
                authTag: newEnc.authTag,
              },
            });
            results.push({
              provider: config.provider,
              apiKey: envApiKey,
              baseUrl: config.baseUrl || undefined,
              model: 'deepseek-chat',
            });
          } catch (reEncryptError) {
            console.warn(`[llm-bridge] 配置 ${config.id} 重新加密失败，跳过`, reEncryptError);
          }
        }
      }
    }
  } catch (error) {
    console.warn('[llm-bridge] 读取用户 LLM 配置失败，将使用环境变量', error);
  }

  return results;
}

/**
 * 获取降级凭证（从环境变量）
 */
function getFallbackCredential(): LLMCredential {
  // 优先使用阿里云 DashScope 凭证
  const dashscopeKey = process.env.DASHSCOPE_API_KEY || process.env.DEEPSEEK_API_KEY || '';
  if (dashscopeKey) {
    return {
      provider: 'dashscope',
      apiKey: dashscopeKey,
      baseUrl: process.env.DASHSCOPE_BASE_URL,
      model: process.env.DASHSCOPE_MODEL || process.env.DEEPSEEK_MODEL || 'qwen3.8-max',
    };
  }
  return {
    provider: 'deepseek',
    apiKey: '',
    baseUrl: undefined,
    model: 'deepseek-chat',
  };
}

// ============================================================
// LLM 调用
// ============================================================

/**
 * 调用 LLM（统一入口）
 *
 * 依次尝试所有已验证凭证（createdAt desc）+ .env 兜底；
 * 遇 402/401 自动降级到下一个凭证，非凭证错误直接抛出。
 * 支持 OpenAI/DeepSeek/百炼（兼容 OpenAI 格式）和 Claude。
 */
export async function callLLM(options: LLMCallOptions, uid?: string): Promise<LLMCallResult> {
  const credentials = await getLLMCredentials(uid);

  // 末尾追加 .env 兜底凭证（去重：避免与数据库配置重复）
  const fallback = getFallbackCredential();
  if (fallback.apiKey && !credentials.some(c => c.apiKey === fallback.apiKey)) {
    credentials.push(fallback);
  }

  const usable = credentials.filter(c => c.apiKey);
  if (usable.length === 0) {
    throw new Error('[llm-bridge] 无可用 LLM 凭证：未配置用户 LLM 且 DEEPSEEK_API_KEY 未设置');
  }

  let lastError: unknown = null;
  for (let i = 0; i < usable.length; i++) {
    const credential = usable[i];
    try {
      const result = await callLLMWithCredential(credential, options);
      if (i > 0) {
        console.log(`[llm-bridge] ✅ 降级成功：第 ${i + 1}/${usable.length} 个凭证 (${credential.provider}) 调用成功`);
      }
      return result;
    } catch (error: unknown) {
      lastError = error;
      const hasNext = i < usable.length - 1;
      // 仅对 402（余额）/401（认证）降级到下一个凭证；超时/500/网络错误直接抛出
      if (error instanceof LLMHTTPError && FALLBACK_STATUS_CODES.has(error.status) && hasNext) {
        console.warn(
          `[llm-bridge] ⚠️ ${credential.provider} 凭证失败 (HTTP ${error.status})，自动降级到下一个配置 (${i + 2}/${usable.length})`
        );
        continue;
      }
      throw error;
    }
  }

  throw lastError instanceof Error ? lastError : new Error('[llm-bridge] 无可用 LLM 凭证');
}

/**
 * 用单个凭证调用 LLM（从 callLLM 拆出，供降级遍历复用）
 */
async function callLLMWithCredential(credential: LLMCredential, options: LLMCallOptions): Promise<LLMCallResult> {
  const defaults = PROVIDER_DEFAULTS[credential.provider] || PROVIDER_DEFAULTS.deepseek;
  const endpoint = credential.baseUrl
    ? `${credential.baseUrl.replace(/\/$/, '')}${credential.provider === 'anthropic' ? '/v1/messages' : '/chat/completions'}`
    : defaults.endpoint;
  const model = credential.model || defaults.model;
  const timeoutMs = options.timeoutMs || 30000;

  const startTime = Date.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    if (credential.provider === 'anthropic') {
      // Claude 使用不同的 API 格式
      const result = await callAnthropic(endpoint, credential.apiKey, model, options, controller);
      const latencyMs = Date.now() - startTime;
      return { ...result, latencyMs };
    }

    // OpenAI 兼容格式（OpenAI/DeepSeek/百炼/自定义）
    const messages: Array<{ role: string; content: string }> = [];
    if (options.systemPrompt) {
      messages.push({ role: 'system', content: options.systemPrompt });
    }
    messages.push({ role: 'user', content: options.prompt });

    // 构建 Function Calling 工具定义
    const tools = options.functions?.map(fn => ({
      type: 'function' as const,
      function: {
        name: fn.name,
        description: fn.description,
        parameters: fn.parameters,
      },
    }));

    const requestBody: Record<string, unknown> = {
      model,
      messages,
      temperature: options.temperature ?? 0.7,
      max_tokens: options.maxTokens ?? 2000,
      // PROP-20260829-C P2.1: 对齐 fallback-engine L153 P0 痕迹——
      // qwen3 思考链会导致 15s 超时；dashscope 必需，其余供应商忽略此字段
      enable_thinking: false,
    };

    // 添加 Function Calling 参数
    if (tools && tools.length > 0) {
      requestBody.tools = tools;
      requestBody.tool_choice = options.functionCall || 'auto';
    }

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${credential.apiKey}`,
      },
      body: JSON.stringify(requestBody),
      signal: controller.signal,
    });

    const latencyMs = Date.now() - startTime;

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new LLMHTTPError(
        response.status,
        `[llm-bridge] LLM 调用失败 (${response.status}): ${errorData.error?.message || response.statusText}`
      );
    }

    const data = await response.json();
    const message = data.choices?.[0]?.message;
    const content = message?.content ?? '';
    const tokensUsed = data.usage?.total_tokens || 0;

    // 解析 Function Call 结果
    let functionCall: LLMFunctionCall | null = null;
    if (message?.tool_calls?.[0]?.function) {
      const fc = message.tool_calls[0].function;
      try {
        const args = typeof fc.arguments === 'string' ? JSON.parse(fc.arguments) : fc.arguments;
        functionCall = { name: fc.name, arguments: args };
      } catch {
        functionCall = { name: fc.name, arguments: { raw: fc.arguments } };
      }
    } else if (message?.function_call) {
      // 兼容旧版 function_call 格式
      const fc = message.function_call;
      try {
        const args = typeof fc.arguments === 'string' ? JSON.parse(fc.arguments) : fc.arguments;
        functionCall = { name: fc.name, arguments: args };
      } catch {
        functionCall = { name: fc.name, arguments: { raw: fc.arguments } };
      }
    }

    return { content, model, tokensUsed, latencyMs, functionCall };
  } catch (error: unknown) {
    if (error instanceof Error && error.name === 'AbortError') {
      return {
        content: '(LLM 调用超时)',
        model: credential.provider,
        tokensUsed: 0,
        latencyMs: Date.now() - startTime,
      };
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * 调用 Anthropic Claude API（不同格式）
 */
async function callAnthropic(
  endpoint: string,
  apiKey: string,
  model: string,
  options: LLMCallOptions,
  controller: AbortController
): Promise<{ content: string; model: string; tokensUsed: number }> {
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model,
      max_tokens: options.maxTokens ?? 2000,
      temperature: options.temperature ?? 0.7,
      system: options.systemPrompt || '',
      messages: [{ role: 'user', content: options.prompt }],
    }),
    signal: controller.signal,
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new LLMHTTPError(
      response.status,
      `[llm-bridge] Claude 调用失败 (${response.status}): ${errorData.error?.message || response.statusText}`
    );
  }

  const data = await response.json();
  const content = data.content?.[0]?.text ?? '';
  const tokensUsed = (data.usage?.input_tokens || 0) + (data.usage?.output_tokens || 0);

  return { content, model, tokensUsed };
}
