/**
 * SPEC-52 F5 — DSH 真实插件安装（profile 写入 + pnpm）
 *
 * 机制（本地 DSH 架构原生能力）：
 *   dsh plugin --profile <profile> add <pkg>
 *   → 在 $DSH_HOME/profiles/<profile>/ 下转发 pnpm，写 package.json + dsh.profile.bundles。
 *
 * 边界（硬约束）：
 *  - 只允许白名单内、且 permitted_profiles 包含目标 profile 的 npm 包；
 *  - 默认只允许 sandbox profile（DSH_INSTALL_PROFILES 可白名单扩展）；
 *  - 核心 bundle（@deepseek-ai/dsh-base|dsh-headless）禁止卸载；
 *  - 所有安装/卸载写 plugin_audit.jsonl。
 */
import { execFile } from 'child_process';
import { promisify } from 'util';
import { readFile } from 'fs/promises';
import path from 'path';
import { appendPluginAudit, listPlugins, type PluginView } from '@/lib/plugins/registry';

const run = promisify(execFile);
const CORE_BUNDLES = new Set(['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-headless']);

export interface InstalledDshPlugin {
  name: string;
  spec: string;
  installed: boolean;
  is_core: boolean;
  in_bundles: boolean;
  whitelist: {
    status: string;
    group: string;
    permitted_profiles: string[];
  } | null;
}

export interface DshProfileInfo {
  profile: string;
  home: string;
  dir: string;
  exists: boolean;
  bundles: string[];
  dependencies: Record<string, string>;
  installed: InstalledDshPlugin[];
  installable_profiles: string[];
}

export function dshHome(): string {
  if (process.env.DSH_HOME) return process.env.DSH_HOME;
  const root = process.env.DREAMBUDDY_ROOT || path.resolve(process.cwd(), '..');
  return path.join(root, '1-ARCHITECTURE', 'dream-harness-bridge', '.dsh-home');
}

export function dshBin(): string {
  return process.env.DSH_BIN || 'dsh';
}

export function allowedInstallProfiles(): string[] {
  return (process.env.DSH_INSTALL_PROFILES || 'sandbox')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function profileDir(profile: string): string {
  return path.join(dshHome(), 'profiles', profile);
}

interface ProfilePackage {
  dependencies?: Record<string, string>;
  dsh?: { profile?: { bundles?: string[] } };
}

async function readProfilePackage(profile: string): Promise<ProfilePackage | null> {
  try {
    return JSON.parse(await readFile(path.join(profileDir(profile), 'package.json'), 'utf-8')) as ProfilePackage;
  } catch {
    return null;
  }
}

/** 校验某白名单条目是否可安装到目标 profile；返回拒绝原因或 null。 */
export function validateInstall(entry: PluginView | undefined, profile: string): string | null {
  if (!entry) return '插件未在白名单登记';
  if (entry.id.includes('*')) return '通配禁止项不可安装';
  if (entry.status === 'forbidden' || entry.riskLevel === 'forbidden') return '禁止清单插件';
  if (entry.source === 'local') return '本地插件无需 npm 安装';
  if (!allowedInstallProfiles().includes(profile)) return `profile ${profile} 未在安装白名单`;
  if (entry.permittedProfiles.length > 0 && !entry.permittedProfiles.includes(profile)) {
    return `插件未授权 profile ${profile}`;
  }
  return null;
}

export async function listDshProfile(profile = 'sandbox'): Promise<DshProfileInfo> {
  const dir = profileDir(profile);
  const pkg = await readProfilePackage(profile);
  const dependencies = pkg?.dependencies ?? {};
  const bundles = pkg?.dsh?.profile?.bundles ?? [];
  const whitelist = await listPlugins().catch(() => [] as PluginView[]);

  const installed: InstalledDshPlugin[] = Object.entries(dependencies).map(([name, spec]) => {
    const entry = whitelist.find((item) => item.id === name);
    return {
      name,
      spec,
      installed: true,
      is_core: CORE_BUNDLES.has(name),
      in_bundles: bundles.includes(name),
      whitelist: entry
        ? {
            status: entry.status,
            group: entry.group,
            permitted_profiles: entry.permittedProfiles,
          }
        : null,
    };
  });

  return {
    profile,
    home: dshHome(),
    dir,
    exists: pkg !== null,
    bundles,
    dependencies,
    installed: installed.sort((a, b) => Number(b.is_core) - Number(a.is_core)),
    installable_profiles: allowedInstallProfiles(),
  };
}

interface DshCommandResult {
  ok: boolean;
  stdout: string;
  stderr: string;
}

async function runDshPlugin(profile: string, args: string[]): Promise<DshCommandResult> {
  try {
    const result = await run(dshBin(), ['plugin', '--profile', profile, ...args], {
      cwd: profileDir(profile),
      env: { ...process.env, DSH_HOME: dshHome() },
      timeout: 180_000,
      maxBuffer: 4 * 1024 * 1024,
    });
    return { ok: true, stdout: result.stdout, stderr: result.stderr };
  } catch (e) {
    const error = e as { stdout?: string; stderr?: string; message?: string };
    return {
      ok: false,
      stdout: error.stdout ?? '',
      stderr: error.stderr ?? error.message ?? 'dsh plugin 执行失败',
    };
  }
}

export async function installDshPlugin(packageName: string, profile = 'sandbox'): Promise<DshProfileInfo> {
  const whitelist = await listPlugins();
  const entry = whitelist.find((item) => item.id === packageName);
  const reject = validateInstall(entry, profile);
  if (reject) {
    await appendPluginAudit({
      plugin_id: packageName,
      action: 'install',
      result: 'denied',
      profile,
      trace_id: '',
    });
    throw new DshInstallError('PLUGIN_INSTALL_DENIED', reject);
  }

  const result = await runDshPlugin(profile, ['add', packageName]);
  await appendPluginAudit({
    plugin_id: packageName,
    action: 'install',
    result: result.ok ? 'ok' : 'denied',
    profile,
    trace_id: '',
  });
  if (!result.ok) {
    throw new DshInstallError('PLUGIN_INSTALL_FAILED', result.stderr.slice(-800));
  }
  return listDshProfile(profile);
}

export async function uninstallDshPlugin(packageName: string, profile = 'sandbox'): Promise<DshProfileInfo> {
  if (CORE_BUNDLES.has(packageName)) {
    await appendPluginAudit({
      plugin_id: packageName,
      action: 'uninstall',
      result: 'denied',
      profile,
      trace_id: '',
    });
    throw new DshInstallError('PLUGIN_CORE_PROTECTED', '核心 bundle 不允许卸载');
  }
  if (!allowedInstallProfiles().includes(profile)) {
    throw new DshInstallError('PLUGIN_PROFILE_NOT_PERMITTED', `profile ${profile} 未在安装白名单`);
  }

  const result = await runDshPlugin(profile, ['remove', packageName]);
  await appendPluginAudit({
    plugin_id: packageName,
    action: 'uninstall',
    result: result.ok ? 'ok' : 'denied',
    profile,
    trace_id: '',
  });
  if (!result.ok) {
    throw new DshInstallError('PLUGIN_UNINSTALL_FAILED', result.stderr.slice(-800));
  }
  return listDshProfile(profile);
}

export class DshInstallError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
