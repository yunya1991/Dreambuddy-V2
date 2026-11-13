/**
 * SPEC-52 F6 — 工具 profile 单测
 */
import {
  TOOL_PROFILES,
  filterToolsByProfile,
  profileSystemPrompt,
  resolveToolProfile,
} from '@/lib/agent/tool-profiles';
import type { Tool } from 'ai';

function dummyTools(names: string[]): Record<string, Tool> {
  return Object.fromEntries(names.map((name) => [name, { description: name } as unknown as Tool]));
}

describe('tool profiles', () => {
  it('工作台默认 platform 只读', () => {
    const profile = resolveToolProfile({ surface: 'workbench' });
    expect(profile.id).toBe('platform');
    expect(profile.canProposeOrders).toBe(false);
    expect(profile.allowedTools).not.toContain('propose_order_intent');
  });

  it('交易产品未开通时降级为 platform', () => {
    const profile = resolveToolProfile({ surface: 'trading', entitled: false });
    expect(profile.id).toBe('platform');
    expect(profile.canProposeOrders).toBe(false);
  });

  it('交易产品已开通时使用 trading_proposal', () => {
    const profile = resolveToolProfile({ surface: 'trading', entitled: true });
    expect(profile.id).toBe('trading_proposal');
    expect(profile.canProposeOrders).toBe(true);
    expect(profile.allowedTools).toContain('propose_order_intent');
  });

  it('白名单过滤：写工具与未注册工具不可见', () => {
    const tools = dummyTools([
      'recall',
      'record',
      'verify',
      'read_signals',
      'propose_order_intent',
      'unknown_tool',
    ]);
    const platform = filterToolsByProfile(tools, TOOL_PROFILES.platform);
    expect(Object.keys(platform ?? {})).toEqual(['recall']);

    const trading = filterToolsByProfile(tools, TOOL_PROFILES.trading_proposal);
    expect(Object.keys(trading ?? {}).sort()).toEqual(
      ['propose_order_intent', 'read_signals', 'recall'].sort(),
    );
  });

  it('每个 profile 都有边界声明', () => {
    for (const profile of Object.values(TOOL_PROFILES)) {
      expect(profileSystemPrompt(profile).length).toBeGreaterThan(0);
    }
  });
});
