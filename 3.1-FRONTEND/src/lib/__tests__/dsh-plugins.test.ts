/**
 * SPEC-52 F5 — DSH 真实安装（profile 读取 + 白名单校验）单测
 */
import { mkdir, mkdtemp, rm, writeFile } from 'fs/promises';
import os from 'os';
import path from 'path';
import { DshInstallError, listDshProfile, uninstallDshPlugin, validateInstall } from '@/lib/dsh/plugins';
import type { PluginView } from '@/lib/plugins/registry';

let home: string;

beforeEach(async () => {
  home = await mkdtemp(path.join(os.tmpdir(), 'dsh-home-'));
  process.env.DSH_HOME = home;
  process.env.DSH_INSTALL_PROFILES = 'sandbox';
  const dir = path.join(home, 'profiles', 'sandbox');
  await mkdir(dir, { recursive: true });
  await writeFile(
    path.join(dir, 'package.json'),
    JSON.stringify({
      name: 'dsh-profile-sandbox',
      dependencies: {
        '@deepseek-ai/dsh-base': '^0.1.5-rc.2',
        '@puwenhui/dsh-rag-kb': '^0.3.1',
        'unknown-plugin': '^1.0.0',
      },
      dsh: { profile: { bundles: ['@deepseek-ai/dsh-base', '@puwenhui/dsh-rag-kb'] } },
    }),
    'utf-8',
  );
});

afterEach(async () => {
  delete process.env.DSH_HOME;
  delete process.env.DSH_INSTALL_PROFILES;
  await rm(home, { recursive: true, force: true });
});

function entry(overrides: Partial<PluginView>): PluginView {
  return {
    id: 'demo-plugin',
    source: 'npm',
    version: '^1.0.0',
    status: 'candidate',
    owner: '',
    riskLevel: 'low',
    securityScanned: true,
    sandboxVerified: true,
    failOpenVerified: true,
    permittedProfiles: ['sandbox'],
    notes: '',
    group: 'community',
    permissions: ['read:market'],
    enabled: false,
    enabledProfile: null,
    enabledAt: null,
    enableable: true,
    rejectReason: null,
    ...overrides,
  };
}

describe('validateInstall', () => {
  it('未登记/通配/禁止项拒绝', () => {
    expect(validateInstall(undefined, 'sandbox')).toBe('插件未在白名单登记');
    expect(validateInstall(entry({ id: '*trading*' }), 'sandbox')).toBe('通配禁止项不可安装');
    expect(validateInstall(entry({ status: 'forbidden' }), 'sandbox')).toBe('禁止清单插件');
  });

  it('本地插件不走 npm 安装', () => {
    expect(validateInstall(entry({ source: 'local' }), 'sandbox')).toBe('本地插件无需 npm 安装');
  });

  it('profile 必须在安装白名单且被插件授权', () => {
    expect(validateInstall(entry({}), 'sandbox')).toBeNull();
    expect(validateInstall(entry({}), 'web')).toBe('profile web 未在安装白名单');
    expect(validateInstall(entry({ permittedProfiles: ['sandbox'] }), 'sandbox')).toBeNull();
  });
});

describe('listDshProfile', () => {
  it('读取已安装依赖并标注 core / bundle / 未登记', async () => {
    const profile = await listDshProfile('sandbox');
    expect(profile.exists).toBe(true);
    expect(profile.bundles).toHaveLength(2);

    const core = profile.installed.find((item) => item.name === '@deepseek-ai/dsh-base');
    expect(core?.is_core).toBe(true);
    expect(core?.in_bundles).toBe(true);

    const community = profile.installed.find((item) => item.name === '@puwenhui/dsh-rag-kb');
    expect(community?.whitelist?.group).toBe('community');

    const unknown = profile.installed.find((item) => item.name === 'unknown-plugin');
    expect(unknown?.whitelist).toBeNull();
  });

  it('核心 bundle 禁止卸载', async () => {
    await expect(uninstallDshPlugin('@deepseek-ai/dsh-base', 'sandbox')).rejects.toMatchObject({
      code: 'PLUGIN_CORE_PROTECTED',
    });
    await expect(uninstallDshPlugin('@deepseek-ai/dsh-base', 'sandbox')).rejects.toBeInstanceOf(DshInstallError);
  });
});
