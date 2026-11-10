/**
 * @jest-environment node
 *
 * providers env 矩阵测试：未配置 → null；openai → 模型实例；
 * openai-compatible + baseURL → 模型实例；缺 baseURL → null。
 */
import { resolveAgentModel } from './providers';

const ENV_KEYS = ['AGENT_PROVIDER', 'AGENT_MODEL', 'AGENT_API_KEY', 'AGENT_BASE_URL'] as const;

describe('resolveAgentModel env 矩阵', () => {
  let saved: Record<string, string | undefined>;

  beforeEach(() => {
    saved = Object.fromEntries(ENV_KEYS.map((k) => [k, process.env[k]]));
    for (const k of ENV_KEYS) delete process.env[k];
  });

  afterEach(() => {
    for (const k of ENV_KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  });

  it('未配置 API key → null（degraded）', () => {
    expect(resolveAgentModel()).toBeNull();
  });

  it('openai：有 key → 模型实例', () => {
    process.env.AGENT_PROVIDER = 'openai';
    process.env.AGENT_API_KEY = 'sk-test';
    process.env.AGENT_MODEL = 'gpt-4o-mini';
    const model = resolveAgentModel();
    expect(model).not.toBeNull();
    expect(typeof (model as { modelId?: string })?.modelId).toBe('string');
  });

  it('openai-compatible + baseURL → 模型实例', () => {
    process.env.AGENT_PROVIDER = 'openai-compatible';
    process.env.AGENT_API_KEY = 'sk-test';
    process.env.AGENT_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1';
    process.env.AGENT_MODEL = 'qwen-plus';
    const model = resolveAgentModel();
    expect(model).not.toBeNull();
  });

  it('openai-compatible 缺 baseURL → null', () => {
    process.env.AGENT_PROVIDER = 'openai-compatible';
    process.env.AGENT_API_KEY = 'sk-test';
    expect(resolveAgentModel()).toBeNull();
  });

  it('未知 provider → null', () => {
    process.env.AGENT_PROVIDER = 'anthropic-native';
    process.env.AGENT_API_KEY = 'sk-test';
    expect(resolveAgentModel()).toBeNull();
  });

  it('调用级 provider/model 覆盖 env', () => {
    process.env.AGENT_API_KEY = 'sk-test';
    const model = resolveAgentModel({
      provider: 'openai-compatible',
      model: 'deepseek-chat',
    });
    // 缺 baseURL → 仍 null
    expect(model).toBeNull();
    process.env.AGENT_BASE_URL = 'http://127.0.0.1:11434/v1';
    expect(resolveAgentModel({ provider: 'openai-compatible', model: 'deepseek-chat' })).not.toBeNull();
  });
});
