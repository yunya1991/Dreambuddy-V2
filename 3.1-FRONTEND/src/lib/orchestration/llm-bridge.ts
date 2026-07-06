/**
 * LLM 桥接层
 *
 * 从 api_configs 表读取用户配置的 LLM 凭证（category=LLM），
 * 解密后注入到 LLM 请求中。支持 OpenAI/DeepSeek/百炼/Claude 等多提供商。
 * 如果用户未配置 LLM，降级到 process.env.DEEPSEEK_API_KEY。
 */

import { prisma } from '@/lib/prisma';
import { decrypt, encrypt } from '@/lib/encryption';

// ============================================================
// 类型定义
// ============================================================

export interface LLMCallOptions {
  prompt: string;
  systemPrompt?: string;
  temperature?: number;
  maxTokens?: number;
  timeoutMs?: number;
}

export interface LLMCallResult {
  content: string;
  model: string;
  tokensUsed: number;
  latencyMs: number;
}

interface LLMCredential {
  provider: string;
  apiKey: string;
  baseUrl?: string;
  model?: string;
}

// ============================================================
// 提供商配置
// ============================================================

/** 各提供商的默认 API 端点和模型 */
const PROVIDER_DEFAULTS: Record<string, { endpoint: string; model: string }> = {
  openai: { endpoint: 'https://api.openai.com/v1/chat/completions', model: 'gpt-4o' },
  deepseek: { endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-chat' },
  dashscope: { endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', model: 'qwen-plus' },
  anthropic: { endpoint: 'https://api.anthropic.com/v1/messages', model: 'claude-sonnet-4-20250514' },
  custom: { endpoint: '', model: 'gpt-4o' },
};

// ============================================================
// 凭证获取
// ============================================================

/**
 * 从数据库获取用户配置的默认 LLM 凭证
 * 优先使用 isVerified=true 的配置
 */
async function getLLMCredential(uid?: string): Promise<LLMCredential | null> {
  // 开发环境使用固定 uid
  const effectiveUid = uid || process.env.DEV_ROUTE_UID || 'dev-user';

  try {
    // 优先按 uid 查找
    let config = await prisma.apiConfig.findFirst({
      where: {
        uid: effectiveUid,
        category: 'LLM',
        isVerified: true,
      },
      orderBy: { createdAt: 'desc' },
    });

    // 开发环境降级：如果指定 uid 找不到，读取任何已验证的 LLM 配置
    if (!config) {
      config = await prisma.apiConfig.findFirst({
        where: {
          category: 'LLM',
          isVerified: true,
        },
        orderBy: { createdAt: 'desc' },
      });
    }

    if (!config) return null;

    try {
      const decrypted = decrypt(config.encryptedData, config.iv, config.authTag);
      const credentials = JSON.parse(decrypted) as { apiKey?: string; model?: string };

      if (!credentials.apiKey) return null;

      return {
        provider: config.provider,
        apiKey: credentials.apiKey,
        baseUrl: config.baseUrl || undefined,
        model: credentials.model || undefined,
      };
    } catch (decryptError) {
      // 数据库凭证解密失败（如 ENCRYPTION_KEY 变更）→ 用环境变量 key 重新加密并更新
      console.warn('[llm-bridge] 数据库凭证解密失败，用环境变量 key 重新加密并更新');
      const envApiKey = process.env.DEEPSEEK_API_KEY;
      if (envApiKey) {
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
        return {
          provider: config.provider,
          apiKey: envApiKey,
          baseUrl: config.baseUrl || undefined,
          model: 'deepseek-chat',
        };
      }
      return null;
    }
  } catch (error) {
    console.warn('[llm-bridge] 读取用户 LLM 配置失败，将使用环境变量', error);
    return null;
  }
}

/**
 * 获取降级凭证（从环境变量）
 */
function getFallbackCredential(): LLMCredential {
  const apiKey = process.env.DEEPSEEK_API_KEY || '';
  return {
    provider: 'deepseek',
    apiKey,
    baseUrl: undefined,
    model: process.env.DEEPSEEK_MODEL || 'deepseek-chat',
  };
}

// ============================================================
// LLM 调用
// ============================================================

/**
 * 调用 LLM（统一入口）
 *
 * 优先使用用户配置的 LLM 凭证，降级到环境变量。
 * 支持 OpenAI/DeepSeek/百炼（兼容 OpenAI 格式）和 Claude。
 */
export async function callLLM(options: LLMCallOptions, uid?: string): Promise<LLMCallResult> {
  const credential = (await getLLMCredential(uid)) || getFallbackCredential();

  if (!credential.apiKey) {
    throw new Error('[llm-bridge] 无可用 LLM 凭证：未配置用户 LLM 且 DEEPSEEK_API_KEY 未设置');
  }

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

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${credential.apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages,
        temperature: options.temperature ?? 0.7,
        max_tokens: options.maxTokens ?? 2000,
      }),
      signal: controller.signal,
    });

    const latencyMs = Date.now() - startTime;

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(`[llm-bridge] LLM 调用失败 (${response.status}): ${errorData.error?.message || response.statusText}`);
    }

    const data = await response.json();
    const content = data.choices?.[0]?.message?.content ?? '';
    const tokensUsed = data.usage?.total_tokens || 0;

    return { content, model, tokensUsed, latencyMs };
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
    throw new Error(`[llm-bridge] Claude 调用失败 (${response.status}): ${errorData.error?.message || response.statusText}`);
  }

  const data = await response.json();
  const content = data.content?.[0]?.text ?? '';
  const tokensUsed = (data.usage?.input_tokens || 0) + (data.usage?.output_tokens || 0);

  return { content, model, tokensUsed };
}
