/**
 * SPEC-52 F5 — 插件白名单解析与启停规则单测
 */
import { mkdtemp, rm } from 'fs/promises';
import os from 'os';
import path from 'path';
import {
  PluginError,
  listPlugins,
  parseWhitelist,
  setPluginEnabled,
  summarizeGroups,
} from '@/lib/plugins/registry';

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(path.join(os.tmpdir(), 'plugin-state-'));
  process.env.PRODUCT_USAGE_DIR = dir;
});

afterEach(async () => {
  delete process.env.PRODUCT_USAGE_DIR;
  await rm(dir, { recursive: true, force: true });
});

describe('parseWhitelist', () => {
  it('解析扁平条目与数组/布尔值', () => {
    const text = [
      'version: "v1"',
      'entries:',
      '  - id: "demo-plugin"',
      '    source: "local"',
      '    status: "approved"',
      '    risk_level: "low"',
      '    security_scanned: true',
      '    permitted_profiles: ["web", "sandbox"]',
      '    notes: "示例"',
    ].join('\n');

    const entries = parseWhitelist(text);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      id: 'demo-plugin',
      status: 'approved',
      securityScanned: true,
      permittedProfiles: ['web', 'sandbox'],
    });
  });
});

describe('真实白名单', () => {
  it('自有/社区分组与禁止项识别正确', async () => {
    const items = await listPlugins();
    expect(items.length).toBeGreaterThan(10);
    expect(summarizeGroups(items).own).toBeGreaterThan(5);

    const own = items.find((item) => item.id === 'dreambuddy-c1');
    expect(own?.group).toBe('own');
    expect(own?.enableable).toBe(true);
    expect(own?.permissions).toContain('read:market');

    const community = items.find((item) => item.id === '@puwenhui/dsh-rag-kb');
    expect(community?.group).toBe('community');
    expect(community?.enableable).toBe(true);

    const forbidden = items.find((item) => item.id === '*trading*');
    expect(forbidden?.enableable).toBe(false);
    expect(forbidden?.permissions).toEqual([]);
  });

  it('禁止项不可启用，合法项可沙箱启停并写审计', async () => {
    await expect(setPluginEnabled('*trading*', true)).rejects.toBeInstanceOf(PluginError);

    const enabled = await setPluginEnabled('dreambuddy-c1', true);
    expect(enabled.enabled).toBe(true);
    expect(enabled.enabledProfile).toBe('sandbox');

    const disabled = await setPluginEnabled('dreambuddy-c1', false);
    expect(disabled.enabled).toBe(false);
  });

  it('未登记插件拒绝', async () => {
    await expect(setPluginEnabled('not-registered-plugin', true)).rejects.toMatchObject({
      code: 'PLUGIN_NOT_REGISTERED',
    });
  });
});
