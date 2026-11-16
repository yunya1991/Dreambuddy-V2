// 统计能力看板配置（TASKS-20261116 T2-4 / T8-3 的纯函数层）
// 设计约束：panel_key = capability_id + hash(args)，重复添加定位已有卡而不是新建。

export type VisualKind = 'table' | 'series' | 'matrix' | 'tree' | 'graph';

export interface PanelSpec {
  capability_id: string;
  title: string;
  kind?: VisualKind;
  args: Record<string, unknown>;
  collapsed?: boolean;
}

export interface PanelTab {
  id: string;
  title: string;
  panels: PanelSpec[];
  builtin?: boolean;
}

export const MAX_TABS = 8;
export const MAX_PANELS_PER_TAB = 12;

/** 稳定序列化：对象键排序，保证同一 args 得到同一 key */
export function stableStringify(value: unknown): string {
  if (value === null || value === undefined) return 'null';
  if (typeof value !== 'object') return JSON.stringify(value) ?? 'null';
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
    .join(',')}}`;
}

/** djb2：短、稳定、无依赖 */
export function hashKey(input: string): string {
  let hash = 5381;
  for (let index = 0; index < input.length; index += 1) {
    hash = ((hash << 5) + hash + input.charCodeAt(index)) >>> 0;
  }
  return hash.toString(36);
}

export function buildPanelKey(panel: Pick<PanelSpec, 'capability_id' | 'args'>): string {
  return `${panel.capability_id}#${hashKey(stableStringify(panel.args ?? {}))}`;
}

export function findPanelIndex(panels: PanelSpec[], panel: Pick<PanelSpec, 'capability_id' | 'args'>): number {
  const key = buildPanelKey(panel);
  return panels.findIndex((item) => buildPanelKey(item) === key);
}

export interface AddPanelResult {
  tab: PanelTab;
  added: boolean;
  key: string;
  reason?: 'duplicate' | 'limit';
  duplicateIndex?: number;
}

/** 往 tab 加卡：同 key 去重；超上限拒绝（由 UI 提示清理，不静默截断） */
export function addPanelToTab(tab: PanelTab, panel: PanelSpec): AddPanelResult {
  const key = buildPanelKey(panel);
  const existing = findPanelIndex(tab.panels, panel);
  if (existing >= 0) {
    return { tab, added: false, key, reason: 'duplicate', duplicateIndex: existing };
  }
  if (tab.panels.length >= MAX_PANELS_PER_TAB) {
    return { tab, added: false, key, reason: 'limit' };
  }
  return { tab: { ...tab, panels: [...tab.panels, panel] }, added: true, key };
}

/** 只删配置，不删能力 */
export function removePanelFromTab(tab: PanelTab, key: string): PanelTab {
  return { ...tab, panels: tab.panels.filter((panel) => buildPanelKey(panel) !== key) };
}

export interface AddTabResult {
  tabs: PanelTab[];
  added: boolean;
  tabId?: string;
  reason?: 'limit';
}

export function addTab(tabs: PanelTab[], title: string): AddTabResult {
  if (tabs.length >= MAX_TABS) return { tabs, added: false, reason: 'limit' };
  const tabId = `tab-${hashKey(`${title}:${tabs.length}:${tabs.map((tab) => tab.id).join(',')}`)}`;
  return { tabs: [...tabs, { id: tabId, title, panels: [] }], added: true, tabId };
}

/** 默认 tab（builtin）不可删 */
export function removeTab(tabs: PanelTab[], tabId: string): PanelTab[] {
  return tabs.filter((tab) => !(tab.id === tabId && !tab.builtin));
}
