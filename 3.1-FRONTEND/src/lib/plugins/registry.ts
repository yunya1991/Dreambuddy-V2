/**
 * SPEC-52 F5 — DSH 插件市场注册表（只读白名单 + 沙箱启停）
 *
 * 唯一事实源：`53-DSH插件模块/plugin_whitelist.yaml`（deny-by-default）。
 * 本模块只做「发现 → 白名单校验 → 沙箱启用 → 审计」，不做真实安装；
 * 所有插件一律以 sandbox profile 启用，不得进入交易热路径。
 */
import { appendFile, mkdir, readFile, writeFile } from 'fs/promises';
import path from 'path';
import { randomUUID } from 'crypto';

export type PluginGroup = 'own' | 'official' | 'community';
export type PluginStatus = 'approved' | 'candidate' | 'forbidden';

export interface PluginEntry {
  id: string;
  source: string;
  version: string;
  status: PluginStatus;
  owner: string;
  riskLevel: string;
  securityScanned: boolean;
  sandboxVerified: boolean;
  failOpenVerified: boolean;
  permittedProfiles: string[];
  notes: string;
}

export interface PluginView extends PluginEntry {
  group: PluginGroup;
  permissions: string[];
  enabled: boolean;
  enabledProfile: string | null;
  enabledAt: string | null;
  /** 是否允许在沙箱启用（forbidden 与通配条目拒绝） */
  enableable: boolean;
  rejectReason: string | null;
}

export interface PluginAuditRecord {
  id: string;
  plugin_id: string;
  action: 'enable' | 'disable' | 'reject' | 'install' | 'uninstall';
  result: 'ok' | 'denied';
  profile: string;
  trace_id: string;
  created_at: string;
}

export class PluginError extends Error {
  constructor(
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

const SANDBOX_PROFILE = 'sandbox';

export function pluginRuntimeDir(): string {
  if (process.env.PRODUCT_USAGE_DIR) return process.env.PRODUCT_USAGE_DIR;
  const root = process.env.DREAMBUDDY_ROOT || path.resolve(process.cwd(), '..');
  return path.join(root, '52-lobehub协议集成', 'runtime');
}

function whitelistPath(): string {
  const root = process.env.DREAMBUDDY_ROOT || path.resolve(process.cwd(), '..');
  return path.join(root, '53-DSH插件模块', 'plugin_whitelist.yaml');
}

function statePath(): string {
  return path.join(pluginRuntimeDir(), 'plugin_state.json');
}

function auditPath(): string {
  return path.join(pluginRuntimeDir(), 'plugin_audit.jsonl');
}

function parseScalar(raw: string): unknown {
  const value = raw.trim();
  if (value.startsWith('"') && value.endsWith('"')) return value.slice(1, -1);
  if (value.startsWith('[') && value.endsWith(']')) {
    const inner = value.slice(1, -1).trim();
    if (!inner) return [];
    return inner
      .split(',')
      .map((item) => parseScalar(item))
      .filter((item): item is string => typeof item === 'string' && item.length > 0);
  }
  if (value === 'true') return true;
  if (value === 'false') return false;
  if (/^-?\d+(\.\d+)?$/.test(value)) return Number(value);
  return value;
}

/** 解析白名单（该文件结构固定：entries 下为扁平 key/value 块）。 */
export function parseWhitelist(text: string): PluginEntry[] {
  const entries: PluginEntry[] = [];
  let inEntries = false;
  let current: Record<string, unknown> | null = null;

  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    if (!line.startsWith(' ') && trimmed === 'entries:') {
      inEntries = true;
      continue;
    }
    if (!inEntries) continue;

    const item = line.match(/^\s{2}- \s*(.*)$/);
    if (item) {
      if (current) entries.push(toEntry(current));
      current = {};
      const kv = item[1].match(/^([\w-]+):\s*(.*)$/);
      if (kv) current[kv[1]] = parseScalar(kv[2]);
      continue;
    }
    const kv = line.match(/^\s{4}([\w-]+):\s*(.*)$/);
    if (kv && current) current[kv[1]] = parseScalar(kv[2]);
  }
  if (current) entries.push(toEntry(current));
  return entries;
}

function toEntry(raw: Record<string, unknown>): PluginEntry {
  const asString = (value: unknown, fallback = '') => (typeof value === 'string' ? value : fallback);
  const asBool = (value: unknown) => value === true;
  const profiles = Array.isArray(raw.permitted_profiles)
    ? (raw.permitted_profiles as string[])
    : [];
  return {
    id: asString(raw.id),
    source: asString(raw.source, 'unknown'),
    version: asString(raw.version, asString(raw.npm_version, '*')),
    status: asString(raw.status, 'candidate') as PluginStatus,
    owner: asString(raw.owner, ''),
    riskLevel: asString(raw.risk_level, 'medium'),
    securityScanned: asBool(raw.security_scanned),
    sandboxVerified: asBool(raw.sandbox_verified),
    failOpenVerified: asBool(raw.fail_open_verified),
    permittedProfiles: profiles,
    notes: asString(raw.notes),
  };
}

function groupOf(entry: PluginEntry): PluginGroup {
  if (entry.source === 'local' || entry.owner === 'dreambuddy') return 'own';
  if (entry.id.startsWith('@deepseek-ai/') || entry.owner === 'deepseek') return 'official';
  return 'community';
}

function permissionsOf(entry: PluginEntry): string[] {
  if (entry.status === 'forbidden' || entry.riskLevel === 'forbidden') return [];
  // SPEC-52 §9.4：第三方插件只读市场，不允许写交易
  return ['read:market', 'ui:panel'];
}

function enableableReason(entry: PluginEntry): string | null {
  if (entry.id.includes('*')) return '通配禁止项不可安装';
  if (entry.status === 'forbidden' || entry.riskLevel === 'forbidden') return '禁止清单插件';
  if (entry.permittedProfiles.length > 0 && !entry.permittedProfiles.includes(SANDBOX_PROFILE)) {
    return '未授权 sandbox profile';
  }
  return null;
}

async function readEntries(): Promise<PluginEntry[]> {
  const text = await readFile(whitelistPath(), 'utf-8');
  return parseWhitelist(text).filter((entry) => entry.id.length > 0);
}

interface PluginState {
  [id: string]: { enabled: boolean; profile: string; enabled_at: string };
}

async function readState(): Promise<PluginState> {
  try {
    return JSON.parse(await readFile(statePath(), 'utf-8')) as PluginState;
  } catch {
    return {};
  }
}

async function writeState(state: PluginState): Promise<void> {
  await mkdir(pluginRuntimeDir(), { recursive: true });
  await writeFile(statePath(), JSON.stringify(state, null, 2), 'utf-8');
}

export async function listPlugins(): Promise<PluginView[]> {
  const [entries, state] = await Promise.all([readEntries(), readState()]);
  return entries.map((entry) => {
    const group = groupOf(entry);
    const rejectReason = enableableReason(entry);
    const local = state[entry.id];
    return {
      ...entry,
      group,
      permissions: permissionsOf(entry),
      enabled: Boolean(local?.enabled),
      enabledProfile: local?.profile ?? null,
      enabledAt: local?.enabled_at ?? null,
      enableable: rejectReason === null,
      rejectReason,
    };
  });
}

export async function appendPluginAudit(
  record: Omit<PluginAuditRecord, 'id' | 'created_at'>,
): Promise<void> {
  return appendAudit(record);
}

async function appendAudit(record: Omit<PluginAuditRecord, 'id' | 'created_at'>): Promise<void> {
  await mkdir(pluginRuntimeDir(), { recursive: true });
  const full: PluginAuditRecord = {
    ...record,
    id: randomUUID(),
    created_at: new Date().toISOString(),
  };
  await appendFile(auditPath(), JSON.stringify(full) + '\n', 'utf-8');
}

export async function setPluginEnabled(
  id: string,
  enabled: boolean,
  profile: string = SANDBOX_PROFILE,
): Promise<PluginView> {
  const entries = await readEntries();
  const entry = entries.find((item) => item.id === id);
  if (!entry) {
    await appendAudit({ plugin_id: id, action: enabled ? 'enable' : 'disable', result: 'denied', profile, trace_id: '' });
    throw new PluginError('PLUGIN_NOT_REGISTERED', '插件未在白名单登记');
  }
  if (enabled) {
    const reject = enableableReason(entry);
    if (reject) {
      await appendAudit({ plugin_id: id, action: 'enable', result: 'denied', profile, trace_id: '' });
      throw new PluginError('PLUGIN_FORBIDDEN', reject);
    }
    if (!entry.permittedProfiles.includes(profile)) {
      await appendAudit({ plugin_id: id, action: 'enable', result: 'denied', profile, trace_id: '' });
      throw new PluginError('PLUGIN_PROFILE_NOT_PERMITTED', '该插件不允许进入所选 profile');
    }
  }

  const state = await readState();
  state[id] = {
    enabled,
    profile,
    enabled_at: new Date().toISOString(),
  };
  await writeState(state);
  await appendAudit({
    plugin_id: id,
    action: enabled ? 'enable' : 'disable',
    result: 'ok',
    profile,
    trace_id: '',
  });

  const plugins = await listPlugins();
  return plugins.find((item) => item.id === id) as PluginView;
}

export async function readPluginAudit(limit = 50): Promise<PluginAuditRecord[]> {
  try {
    const raw = await readFile(auditPath(), 'utf-8');
    return raw
      .split('\n')
      .filter(Boolean)
      .flatMap((line) => {
        try {
          return [JSON.parse(line) as PluginAuditRecord];
        } catch {
          return [];
        }
      })
      .slice(-limit)
      .reverse();
  } catch {
    return [];
  }
}

export function summarizeGroups(items: PluginView[]): Record<PluginGroup, number> {
  return items.reduce(
    (acc, item) => {
      acc[item.group] += 1;
      return acc;
    },
    { own: 0, official: 0, community: 0 } as Record<PluginGroup, number>,
  );
}
