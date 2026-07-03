/**
 * API配置 - 测试连接
 * POST /api/config/api-keys/test
 * 根据provider调用对应的连通性测试
 */
import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';
import { execSync } from 'child_process';
import { prisma } from '@/lib/prisma';
import { resolveApiKeysTestRouteUid } from '@/lib/development-route-uids';
import { decrypt } from '@/lib/encryption';

interface TestResult {
  success: boolean;
  message: string;
  latency?: number;
  model?: string;
}

async function testOKXWithCredentials(
  apiKey: string,
  secretKey: string,
  passphrase: string,
  environment: string
): Promise<TestResult> {
  const start = Date.now();
  try {
    const baseUrl = 'https://www.okx.com';
    const timestamp = new Date().toISOString();
    const signStr = `${timestamp}GET/api/v5/account/balance`;
    const signature = crypto.createHmac('sha256', secretKey)
      .update(signStr)
      .digest('base64');

    const response = await fetch(`${baseUrl}/api/v5/account/balance`, {
      headers: {
        'OK-ACCESS-KEY': apiKey,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': timestamp,
        'OK-ACCESS-PASSPHRASE': passphrase,
      },
    });

    const latency = Date.now() - start;
    const data = await response.json();

    if (data.code === '0') {
      return {
        success: true,
        message: `OKX ${environment}连接成功`,
        latency,
      };
    } else {
      return {
        success: false,
        message: `OKX连接失败: ${data.msg || '未知错误'}`,
        latency,
      };
    }
  } catch (error) {
    const latency = Date.now() - start;
    return {
      success: false,
      message: `OKX连接失败: ${error instanceof Error ? error.message : '未知错误'}`,
      latency,
    };
  }
}

async function testOpenAI(
  apiKey: string,
  baseUrl?: string
): Promise<TestResult> {
  const start = Date.now();
  try {
    const url = baseUrl
      ? `${baseUrl.replace(/\/$/, '')}/v1/models`
      : 'https://api.openai.com/v1/models';

    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(15000),
    });

    const latency = Date.now() - start;

    if (response.ok) {
      const data = await response.json();
      const modelCount = data.data?.length || 0;
      return {
        success: true,
        message: `OpenAI 连接成功，可用模型 ${modelCount} 个`,
        latency,
      };
    } else {
      const errorData = await response.json().catch(() => ({}));
      return {
        success: false,
        message: `OpenAI 连接失败: ${errorData.error?.message || `HTTP ${response.status}`}`,
        latency,
      };
    }
  } catch (error) {
    const latency = Date.now() - start;
    return {
      success: false,
      message: `OpenAI 连接失败: ${error instanceof Error ? error.message : '未知错误'}`,
      latency,
    };
  }
}

async function testDashscope(
  apiKey: string,
  baseUrl?: string
): Promise<TestResult> {
  const start = Date.now();
  try {
    const url = baseUrl
      ? `${baseUrl.replace(/\/$/, '')}/api/v1/models`
      : 'https://dashscope.aliyuncs.com/api/v1/models';

    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(15000),
    });

    const latency = Date.now() - start;

    if (response.ok) {
      const data = await response.json();
      const modelCount = data.data?.models?.length || data.data?.length || 0;
      return {
        success: true,
        message: `百炼 DashScope 连接成功，可用模型 ${modelCount} 个`,
        latency,
      };
    } else {
      const errorData = await response.json().catch(() => ({}));
      return {
        success: false,
        message: `百炼连接失败: ${errorData.message || errorData.code || `HTTP ${response.status}`}`,
        latency,
      };
    }
  } catch (error) {
    const latency = Date.now() - start;
    return {
      success: false,
      message: `百炼连接失败: ${error instanceof Error ? error.message : '未知错误'}`,
      latency,
    };
  }
}

async function testDeepSeek(
  apiKey: string,
  baseUrl?: string
): Promise<TestResult> {
  const start = Date.now();
  try {
    const url = baseUrl
      ? `${baseUrl.replace(/\/$/, '')}/chat/completions`
      : 'https://api.deepseek.com/chat/completions';

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: 'deepseek-chat',
        messages: [{ role: 'user', content: 'hi' }],
        max_tokens: 5,
      }),
      signal: AbortSignal.timeout(15000),
    });

    const latency = Date.now() - start;

    if (response.ok) {
      return {
        success: true,
        message: 'DeepSeek 连接成功',
        latency,
      };
    } else {
      const errorData = await response.json().catch(() => ({}));
      return {
        success: false,
        message: `DeepSeek 连接失败: ${errorData.error?.message || `HTTP ${response.status}`}`,
        latency,
      };
    }
  } catch (error) {
    const latency = Date.now() - start;
    return {
      success: false,
      message: `DeepSeek 连接失败: ${error instanceof Error ? error.message : '未知错误'}`,
      latency,
    };
  }
}

async function testAnthropic(
  apiKey: string,
  baseUrl?: string
): Promise<TestResult> {
  const start = Date.now();
  try {
    const url = baseUrl
      ? `${baseUrl.replace(/\/$/, '')}/v1/messages`
      : 'https://api.anthropic.com/v1/messages';

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: 'claude-3-haiku-20240307',
        max_tokens: 5,
        messages: [{ role: 'user', content: 'hi' }],
      }),
      signal: AbortSignal.timeout(15000),
    });

    const latency = Date.now() - start;

    if (response.ok) {
      return {
        success: true,
        message: 'Anthropic 连接成功',
        latency,
      };
    } else {
      const errorData = await response.json().catch(() => ({}));
      return {
        success: false,
        message: `Anthropic 连接失败: ${errorData.error?.message || `HTTP ${response.status}`}`,
        latency,
      };
    }
  } catch (error) {
    const latency = Date.now() - start;
    return {
      success: false,
      message: `Anthropic 连接失败: ${error instanceof Error ? error.message : '未知错误'}`,
      latency,
    };
  }
}

/**
 * 通用 OpenAI 兼容 API 测试（支持自定义 baseUrl 的第三方中转）
 */
async function testOpenAICompatible(
  apiKey: string,
  baseUrl: string
): Promise<TestResult> {
  const start = Date.now();
  try {
    const url = `${baseUrl.replace(/\/$/, '')}/v1/models`;

    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(15000),
    });

    const latency = Date.now() - start;

    if (response.ok) {
      const data = await response.json();
      const modelCount = data.data?.length || 0;
      return {
        success: true,
        message: `连接成功，可用模型 ${modelCount} 个`,
        latency,
      };
    } else {
      // 尝试 chat/completions 端点
      const chatUrl = `${baseUrl.replace(/\/$/, '')}/v1/chat/completions`;
      try {
        const chatResponse = await fetch(chatUrl, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${apiKey}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            model: 'gpt-3.5-turbo',
            messages: [{ role: 'user', content: 'hi' }],
            max_tokens: 5,
          }),
          signal: AbortSignal.timeout(15000),
        });
        const chatLatency = Date.now() - start;
        if (chatResponse.ok) {
          return {
            success: true,
            message: '连接成功（chat 模式）',
            latency: chatLatency,
          };
        }
        const errorData = await chatResponse.json().catch(() => ({}));
        return {
          success: false,
          message: `连接失败: ${errorData.error?.message || `HTTP ${chatResponse.status}`}`,
          latency: chatLatency,
        };
      } catch {
        return {
          success: false,
          message: `连接失败: HTTP ${response.status}`,
          latency,
        };
      }
    }
  } catch (error) {
    const latency = Date.now() - start;
    return {
      success: false,
      message: `连接失败: ${error instanceof Error ? error.message : '未知错误'}`,
      latency,
    };
  }
}

/**
 * 测试OKX连接
 * 使用okx CLI进行连通性测试
 */
async function testOKX(environment: string, profile?: string): Promise<TestResult> {
  const start = Date.now();
  try {
    const profileFlag = profile ? `--profile ${profile}` : '--profile dreamdemo';
    const output = execSync(
      `okx market ticker BTC-USDT-SWAP ${profileFlag}`,
      { timeout: 15000, encoding: 'utf-8' }
    );
    const latency = Date.now() - start;

    if (output && output.includes('last')) {
      return {
        success: true,
        message: `OKX ${environment}连接正常，BTC ticker获取成功`,
        latency,
      };
    }
    return {
      success: false,
      message: `OKX返回数据异常: ${output.slice(0, 100)}`,
      latency,
    };
  } catch (error) {
    const latency = Date.now() - start;
    return {
      success: false,
      message: `OKX连接失败: ${error instanceof Error ? error.message : '未知错误'}`,
      latency,
    };
  }
}

// POST /api/config/api-keys/test
export async function POST(request: NextRequest) {
  const uid = await resolveApiKeysTestRouteUid(request);

  try {
    const body = await request.json();
    const { configId, provider, apiKey, secretKey, passphrase, environment, baseUrl, category } = body;

    let testProvider = provider;
    let testEnv = environment || 'demo';
    let testApiKey = apiKey;
    let testSecretKey = secretKey;
    let testPassphrase = passphrase || '';
    let testBaseUrl = baseUrl;
    let testCategory = category;

    // 如果提供了configId，从数据库读取并解密凭证
    if (configId) {
      const config = await prisma.apiConfig.findFirst({
        where: { id: configId, uid },
      });
      if (!config) {
        return NextResponse.json(
          { success: false, error: '配置不存在' },
          { status: 404 }
        );
      }
      testProvider = config.provider;
      testEnv = config.environment || 'demo';
      testBaseUrl = config.baseUrl;
      testCategory = config.category;
      // 解密凭证
      const decrypted = decrypt(config.encryptedData, config.iv, config.authTag);
      const credentials = JSON.parse(decrypted);
      testApiKey = credentials.apiKey;
      testSecretKey = credentials.secretKey;
      testPassphrase = credentials.passphrase || '';
    }

    let result: TestResult;

    switch (testProvider?.toLowerCase()) {
      case 'okx':
        // 优先使用直接凭证测试（支持保存前测试）
        if (testApiKey && testSecretKey) {
          result = await testOKXWithCredentials(testApiKey, testSecretKey, testPassphrase, testEnv);
        } else {
          // 降级到 CLI 测试（向后兼容）
          result = await testOKX(testEnv);
        }
        // 如果测试成功且有configId，更新验证状态
        if (result.success && configId) {
          await prisma.apiConfig.update({
            where: { id: configId },
            data: {
              isVerified: true,
              lastVerifiedAt: new Date(),
            },
          });
        }
        break;

      case 'openai':
        result = await testOpenAI(testApiKey, testBaseUrl || undefined);
        break;

      case 'dashscope':
      case 'aliyun':
      case 'qwen':
        result = await testDashscope(testApiKey, testBaseUrl || undefined);
        break;

      case 'deepseek':
        result = await testDeepSeek(testApiKey, testBaseUrl || undefined);
        break;

      case 'anthropic':
      case 'claude':
        result = await testAnthropic(testApiKey, testBaseUrl || undefined);
        break;

      case 'custom':
      case 'openai-compatible':
        if (!testBaseUrl) {
          result = {
            success: false,
            message: '自定义 API 需要提供 baseUrl',
          };
        } else {
          result = await testOpenAICompatible(testApiKey, testBaseUrl);
        }
        break;

      default:
        result = {
          success: false,
          message: `不支持的provider: ${testProvider}`,
        };
    }

    // 如果测试成功且有configId，更新验证状态（适用所有类别）
    if (result.success && configId) {
      await prisma.apiConfig.update({
        where: { id: configId },
        data: {
          isVerified: true,
          lastVerifiedAt: new Date(),
        },
      });
    }

    return NextResponse.json({ success: true, data: result });
  } catch (error) {
    console.error('测试连接失败:', error);
    return NextResponse.json(
      { success: false, error: '测试连接失败' },
      { status: 500 }
    );
  }
}
