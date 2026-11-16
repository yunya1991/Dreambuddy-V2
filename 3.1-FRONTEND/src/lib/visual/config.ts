// 统计能力看板配置（TASKS-20261116 T8-6）
// 职责：默认配置（2 tab / 13 卡）、localStorage 持久化、读取时防御性归一化。
// 设计约束：配置只决定「挂哪些卡」，不决定能力是否存在；能力仍从 manifest 取回。

import {
  MAX_PANELS_PER_TAB,
  MAX_TABS,
  buildPanelKey,
  type PanelSpec,
  type PanelTab,
} from './panelKey';
import type { CapabilitySchema } from '@/components/visual/types';

export const CONFIG_KEY = 'dreambuddy.visual.panels.v1';
export const CONFIG_VERSION = 1;
export const DEFAULT_ACTIVE_TAB = 'rec';
export const BUILTIN_TAB_IDS = ['rec', 'all'] as const;

// 装配器默认值（SPEC-54 R2 决策 1：基准 US500；与 capability_resolve.py 保持一致）
export const DEFAULT_SYMBOL = 'BTC';
export const DEFAULT_BENCHMARK = 'US500';
export const DEFAULT_DAYS = 750;

export interface BoardConfig {
  version: number;
  tabs: PanelTab[];
  activeId: string;
}

/**
 * 默认 13 卡（首次进入）。
 * 只有数据自足出口（D-K01/K02/K03）能直接取数；其余 10 张需要输入序列，
 * 卡片会显式提示「需要输入序列」，由「＋ 能力库」补参后使用，绝不伪造图。
 */
export const DEFAULT_PANELS: PanelSpec[] = [
  { capability_id: 'D-K01', title: '关系推荐（只读出口）', args: { target: 'BTC' }, kind: 'table' },
  { capability_id: 'D-K02', title: '同类现象归纳', args: {}, kind: 'table' },
  { capability_id: 'D-K03', title: '期级信号（只读出口）', args: {}, kind: 'table' },
  { capability_id: 'D-E17', title: '类别看板（跨资产）', args: {}, kind: 'table' },
  { capability_id: 'D-E16', title: '聚合曲线（跨资产）', args: {}, kind: 'series' },
  { capability_id: 'D-E15', title: '趋势：价格 + EMA26', args: {}, kind: 'series' },
  { capability_id: 'D-E10', title: '回撤路径', args: {}, kind: 'series' },
  { capability_id: 'D-A14', title: '拥挤度（分位）', args: {}, kind: 'table' },
  { capability_id: 'D-G22', title: '显著性（HAC / DSR）', args: {}, kind: 'table' },
  { capability_id: 'D-E19', title: '点亮投影（四轴五态）', args: {}, kind: 'matrix' },
  { capability_id: 'D-E07', title: '状态转移（周期）', args: {}, kind: 'matrix' },
  { capability_id: 'D-J13', title: '长记忆（Hurst / DFA）', args: {}, kind: 'table' },
  { capability_id: 'D-G16', title: '组合 VaR / CVaR', args: {}, kind: 'table' },
];

export function defaultTabs(): PanelTab[] {
  return [
    { id: 'rec', title: '推荐总览', panels: [], builtin: true },
    { id: 'all', title: '全部出口', panels: DEFAULT_PANELS.map((panel) => ({ ...panel })), builtin: true },
  ];
}

export function defaultConfig(): BoardConfig {
  return { version: CONFIG_VERSION, tabs: defaultTabs(), activeId: DEFAULT_ACTIVE_TAB };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizePanel(raw: unknown): PanelSpec | null {
  if (!isRecord(raw)) return null;
  const capabilityId = typeof raw.capability_id === 'string' ? raw.capability_id.trim() : '';
  if (!capabilityId) return null;
  const args = isRecord(raw.args) ? (raw.args as Record<string, unknown>) : {};
  const panel: PanelSpec = {
    capability_id: capabilityId,
    title: typeof raw.title === 'string' && raw.title.trim() ? raw.title.trim() : capabilityId,
    args,
  };
  if (typeof raw.kind === 'string') panel.kind = raw.kind as PanelSpec['kind'];
  if (raw.collapsed === true) panel.collapsed = true;
  return panel;
}

function normalizePanels(raw: unknown): PanelSpec[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const panels: PanelSpec[] = [];
  for (const item of raw) {
    const panel = normalizePanel(item);
    if (!panel) continue;
    const key = buildPanelKey(panel);
    if (seen.has(key)) continue;
    seen.add(key);
    panels.push(panel);
    if (panels.length >= MAX_PANELS_PER_TAB) break;
  }
  return panels;
}

/**
 * 把任意来源（localStorage / 旧版本 / 手改 JSON）归一化成可用配置：
 * - builtin tab 永远存在且排在最前，顺序 rec → all；
 * - 自建 tab 最多补到 MAX_TABS，超出的丢弃；每 tab 最多 MAX_PANELS_PER_TAB 卡；
 * - 同 tab 内按 panel_key 去重；
 * - activeId 不存在时回落到 rec。
 */
export function normalizeConfig(raw: unknown): BoardConfig {
  const source = isRecord(raw) ? raw : {};
  const rawTabs = Array.isArray(source.tabs) ? source.tabs : [];

  const byId = new Map<string, PanelTab>();
  for (const item of rawTabs) {
    if (!isRecord(item) || typeof item.id !== 'string' || !item.id.trim()) continue;
    const id = item.id.trim();
    if (byId.has(id)) continue;
    byId.set(id, {
      id,
      title:
        typeof item.title === 'string' && item.title.trim() ? item.title.trim() : id,
      panels: normalizePanels(item.panels),
      builtin: item.builtin === true,
    });
  }

  const tabs: PanelTab[] = [];
  for (const id of BUILTIN_TAB_IDS) {
    const existing = byId.get(id);
    const fallback = defaultTabs().find((tab) => tab.id === id)!;
    tabs.push({
      ...fallback,
      panels: existing?.panels ?? fallback.panels,
      builtin: true,
    });
    byId.delete(id);
  }

  for (const tab of byId.values()) {
    if (tabs.length >= MAX_TABS) break;
    tabs.push({ ...tab, builtin: false });
  }

  const requestedActive = typeof source.activeId === 'string' ? source.activeId : '';
  const activeId = tabs.some((tab) => tab.id === requestedActive) ? requestedActive : DEFAULT_ACTIVE_TAB;

  return { version: CONFIG_VERSION, tabs, activeId };
}

export function parseConfig(text: string | null | undefined): BoardConfig {
  if (!text) return defaultConfig();
  try {
    return normalizeConfig(JSON.parse(text));
  } catch {
    return defaultConfig();
  }
}

export function serializeConfig(config: BoardConfig): string {
  return JSON.stringify(normalizeConfig(config));
}

export type ConfigStorage = Pick<Storage, 'getItem' | 'setItem'>;

export function loadConfig(storage?: ConfigStorage | null): BoardConfig {
  const target = storage ?? (typeof window === 'undefined' ? null : window.localStorage);
  if (!target) return defaultConfig();
  try {
    return parseConfig(target.getItem(CONFIG_KEY));
  } catch {
    return defaultConfig();
  }
}

export function saveConfig(config: BoardConfig, storage?: ConfigStorage | null): boolean {
  const target = storage ?? (typeof window === 'undefined' ? null : window.localStorage);
  if (!target) return false;
  try {
    target.setItem(CONFIG_KEY, serializeConfig(config));
    return true;
  } catch {
    // 配额满 / 隐私模式：FAIL-OPEN，不阻断界面
    return false;
  }
}

export function panelCount(tabs: PanelTab[]): number {
  return tabs.reduce((total, tab) => total + tab.panels.length, 0);
}

/**
 * 按 schema 生成卡片初始 args（SPEC-54 R3：不再固定 `{}`）。
 * 只填「装配器无法推断、但有能力层默认口径」的项：资产 / 基准 / auto 标量的 default；
 * derived 与 unsupported 一律不写，交给服务端装配器或显式缺参提示。
 */
export function defaultArgsForSchema(schema: CapabilitySchema): Record<string, unknown> {
  const args: Record<string, unknown> = {};
  if (schema.requires_symbol) args.symbol = DEFAULT_SYMBOL;
  if (schema.requires_benchmark) args.benchmark = DEFAULT_BENCHMARK;
  for (const arg of schema.args) {
    if (arg.source !== 'auto' || arg.required || arg.type !== 'scalar') continue;
    if (arg.name === 'symbol' || arg.name === 'benchmark' || arg.name === 'days') continue;
    const value = arg.default;
    if (value === null || value === undefined || typeof value === 'object') continue;
    args[arg.name] = value;
  }
  return args;
}

// ---------------------------------------------------------------- 服务端同步（SPEC-54 R3b）
// 存储层只有「面板行」，tab 标题与删除态用一条元数据行承载：
// panel_key = __tab__，args = {title, deleted?}。
export const TAB_META_KEY = '__tab__';
export const TAB_META_CAPABILITY = '__tab__';

export interface ServerPanelRow {
  tab_id: string;
  panel_key: string;
  capability_id: string;
  title?: string;
  kind?: string;
  args: Record<string, unknown>;
}

export interface ServerTabPayload {
  panel_key: string;
  capability_id: string;
  title?: string;
  kind?: string;
  args: Record<string, unknown>;
  data_provenance?: string;
}

function panelRow(panel: PanelSpec): ServerTabPayload {
  return {
    panel_key: buildPanelKey(panel),
    capability_id: panel.capability_id,
    title: panel.title,
    kind: panel.kind,
    args: panel.args ?? {},
    data_provenance: 'pool',
  };
}

/** tab → 服务端行（含 tab 元数据行；deleted=true 时只发墓碑） */
export function tabToServerRows(tab: PanelTab, deleted = false): ServerTabPayload[] {
  const meta: ServerTabPayload = {
    panel_key: TAB_META_KEY,
    capability_id: TAB_META_CAPABILITY,
    args: deleted ? { title: tab.title, deleted: true } : { title: tab.title },
  };
  if (deleted) return [meta];
  return [meta, ...tab.panels.map(panelRow)];
}

/**
 * 服务端行 → 本地配置：服务端有的 tab 以服务端为准（含空 tab 与墓碑删除），
 * 服务端没有记录的 tab 保留本地（首次登录/离线新增）。
 */
export function mergeServerPanels(config: BoardConfig, items: ServerPanelRow[]): BoardConfig {
  const groups = new Map<string, ServerPanelRow[]>();
  for (const item of items) {
    const list = groups.get(item.tab_id) ?? [];
    list.push(item);
    groups.set(item.tab_id, list);
  }

  let tabs: PanelTab[] = config.tabs.map((tab) => ({ ...tab }));
  for (const [tabId, rows] of groups) {
    const meta = rows.find((row) => row.panel_key === TAB_META_KEY);
    const index = tabs.findIndex((tab) => tab.id === tabId);

    if (meta?.args?.deleted === true) {
      if (index >= 0 && !tabs[index].builtin) tabs = tabs.filter((tab) => tab.id !== tabId);
      continue;
    }

    const title =
      typeof meta?.args?.title === 'string' && meta.args.title.trim()
        ? String(meta.args.title).trim()
        : tabs[index]?.title ?? tabId;
    const panels = normalizePanels(
      rows
        .filter((row) => row.panel_key !== TAB_META_KEY)
        .map((row) => ({
          capability_id: row.capability_id,
          title: row.title || row.capability_id,
          kind: row.kind || undefined,
          args: row.args,
        })),
    );

    if (index >= 0) {
      tabs[index] = { ...tabs[index], title, panels };
    } else if (tabs.length < MAX_TABS) {
      tabs.push({ id: tabId, title, panels, builtin: false });
    }
  }

  const activeId = tabs.some((tab) => tab.id === config.activeId)
    ? config.activeId
    : tabs[0]?.id ?? DEFAULT_ACTIVE_TAB;
  return { version: CONFIG_VERSION, tabs, activeId };
}
