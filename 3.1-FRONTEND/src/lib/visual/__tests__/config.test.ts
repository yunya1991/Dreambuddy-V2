import {
  CONFIG_KEY,
  DEFAULT_ACTIVE_TAB,
  DEFAULT_PANELS,
  defaultArgsForSchema,
  defaultConfig,
  loadConfig,
  mergeServerPanels,
  normalizeConfig,
  panelCount,
  parseConfig,
  saveConfig,
  serializeConfig,
  tabToServerRows,
  TAB_META_KEY,
  type ConfigStorage,
} from '../config';
import type { BoardConfig } from '../config';
import { MAX_PANELS_PER_TAB, MAX_TABS } from '../panelKey';

function memoryStorage(seed: Record<string, string> = {}): ConfigStorage & { data: Record<string, string> } {
  const data = { ...seed };
  return {
    data,
    getItem: (key: string) => (key in data ? data[key] : null),
    setItem: (key: string, value: string) => {
      data[key] = value;
    },
  };
}

describe('默认配置', () => {
  it('首次进入给 2 个 builtin tab / 13 卡', () => {
    const config = defaultConfig();
    expect(config.tabs.map((tab) => tab.id)).toEqual(['rec', 'all']);
    expect(config.tabs.every((tab) => tab.builtin)).toBe(true);
    expect(DEFAULT_PANELS).toHaveLength(13);
    expect(panelCount(config.tabs)).toBe(13);
    expect(config.activeId).toBe(DEFAULT_ACTIVE_TAB);
  });

  it('默认卡互不重复（panel_key 唯一）', () => {
    const keys = new Set(DEFAULT_PANELS.map((panel) => JSON.stringify([panel.capability_id, panel.args])));
    expect(keys.size).toBe(DEFAULT_PANELS.length);
  });
});

describe('normalizeConfig 防御', () => {
  it('非对象 / 空值 → 默认配置', () => {
    expect(normalizeConfig(null).tabs).toHaveLength(2);
    expect(normalizeConfig('oops').tabs).toHaveLength(2);
    expect(normalizeConfig({}).tabs).toHaveLength(2);
  });

  it('内置 tab 永远存在且排在自建 tab 之前', () => {
    const config = normalizeConfig({
      tabs: [{ id: 'mine', title: '自建', panels: [{ capability_id: 'D-A01', title: 'A01', args: {} }] }],
      activeId: 'mine',
    });
    expect(config.tabs.map((tab) => tab.id)).toEqual(['rec', 'all', 'mine']);
    expect(config.activeId).toBe('mine');
  });

  it('自建 tab 超上限被截断（含内置 2 个）', () => {
    const tabs = Array.from({ length: MAX_TABS + 3 }, (_, index) => ({
      id: `t${index}`,
      title: `t${index}`,
      panels: [],
    }));
    expect(normalizeConfig({ tabs }).tabs).toHaveLength(MAX_TABS);
  });

  it('单 tab 超上限 / 重复卡被裁掉', () => {
    const panels = Array.from({ length: MAX_PANELS_PER_TAB + 4 }, (_, index) => ({
      capability_id: 'D-A01',
      title: 'A01',
      args: { index },
    }));
    panels.push({ capability_id: 'D-A01', title: 'dup', args: { index: 0 } });
    const config = normalizeConfig({ tabs: [{ id: 'all', title: '全部出口', panels }] });
    const all = config.tabs.find((tab) => tab.id === 'all')!;
    expect(all.panels).toHaveLength(MAX_PANELS_PER_TAB);
  });

  it('activeId 不存在 → 回落到 rec', () => {
    expect(normalizeConfig({ tabs: [], activeId: 'ghost' }).activeId).toBe(DEFAULT_ACTIVE_TAB);
  });

  it('缺 capability_id 的卡被丢弃', () => {
    const config = normalizeConfig({
      tabs: [{ id: 'all', title: '全部出口', panels: [{ title: '无 id' }, null, 3] }],
    });
    expect(config.tabs.find((tab) => tab.id === 'all')!.panels).toHaveLength(0);
  });
});

describe('localStorage 持久化', () => {
  it('save → load 往返保留 tab 与卡', () => {
    const storage = memoryStorage();
    const config = normalizeConfig({
      tabs: [
        {
          id: 'all',
          title: '全部出口',
          builtin: true,
          panels: [{ capability_id: 'D-E17', title: '类别看板', args: { top: 3 } }],
        },
        { id: 'mine', title: '我的', panels: [{ capability_id: 'D-A01', title: 'A01', args: {} }] },
      ],
      activeId: 'mine',
    });
    expect(saveConfig(config, storage)).toBe(true);
    expect(storage.data[CONFIG_KEY]).toBeTruthy();

    const restored = loadConfig(storage);
    expect(restored.activeId).toBe('mine');
    expect(restored.tabs.map((tab) => tab.id)).toEqual(['rec', 'all', 'mine']);
    expect(restored.tabs.find((tab) => tab.id === 'mine')!.panels[0].capability_id).toBe('D-A01');
  });

  it('损坏 JSON → 回落默认配置，不抛异常', () => {
    const storage = memoryStorage({ [CONFIG_KEY]: '{not-json' });
    expect(loadConfig(storage).tabs).toHaveLength(2);
  });

  it('storage 写入失败 → 返回 false 且不抛出', () => {
    const storage: ConfigStorage = {
      getItem: () => null,
      setItem: () => {
        throw new Error('QuotaExceededError');
      },
    };
    expect(saveConfig(defaultConfig(), storage)).toBe(false);
    expect(parseConfig(null).tabs).toHaveLength(2);
    expect(serializeConfig(defaultConfig())).toContain('"version"');
  });
});

describe('卡片初始参数（SPEC-54 R3）', () => {
  it('按 schema 写入资产/基准默认值', () => {
    expect(
      defaultArgsForSchema({
        capability_id: 'D-A11',
        accepts_extra: false,
        requires_symbol: true,
        requires_benchmark: true,
        args: [
          { name: 'x', type: 'series', required: true, default: null, source: 'auto' },
        ],
      }),
    ).toEqual({ symbol: 'BTC', benchmark: 'US500' });
  });

  it('derived / 缺失 required 参数不写入 args', () => {
    const args = defaultArgsForSchema({
      capability_id: 'D-E08',
      accepts_extra: false,
      requires_symbol: true,
      requires_benchmark: false,
      args: [
        { name: 'factor', type: 'series', required: true, default: null, source: 'derived', derived_by: 'momentum_20d' },
        { name: 'forward', type: 'series', required: true, default: null, source: 'derived' },
      ],
    });
    expect(args).toEqual({ symbol: 'BTC' });
  });

  it('auto 标量 default 会被带入，symbol/benchmark/days 不重复写', () => {
    const args = defaultArgsForSchema({
      capability_id: 'D-J21',
      accepts_extra: false,
      requires_symbol: true,
      requires_benchmark: false,
      args: [
        { name: 'taus', type: 'scalar', required: false, default: [0.1, 0.5], source: 'auto' },
        { name: 'window', type: 'scalar', required: false, default: 20, source: 'auto' },
        { name: 'days', type: 'scalar', required: false, default: 750, source: 'auto' },
      ],
    });
    expect(args).toEqual({ symbol: 'BTC', window: 20 });
  });

  it('纯宏观能力不写 symbol', () => {
    expect(
      defaultArgsForSchema({
        capability_id: 'D-A10',
        accepts_extra: false,
        requires_symbol: false,
        requires_benchmark: false,
        args: [],
      }),
    ).toEqual({});
  });
});

describe('服务端配置同步（SPEC-54 R3b）', () => {
  function configWith(panels: BoardConfig['tabs'][number]['panels']): BoardConfig {
    return {
      version: 1,
      tabs: [
        { id: 'rec', title: '推荐总览', panels: [], builtin: true },
        { id: 'all', title: '全部出口', panels, builtin: true },
      ],
      activeId: 'all',
    };
  }

  it('tab → 服务端行含一条 tab 元数据行', () => {
    const rows = tabToServerRows(configWith([]).tabs[1]);
    expect(rows).toHaveLength(1);
    expect(rows[0].panel_key).toBe(TAB_META_KEY);
    expect(rows[0].args).toEqual({ title: '全部出口' });
  });

  it('删除 tab 只发墓碑行', () => {
    const rows = tabToServerRows(
      { id: 'mine', title: '我的', panels: [{ capability_id: 'D-A11', title: 'x', args: {} }] },
      true,
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].args).toEqual({ title: '我的', deleted: true });
  });

  it('服务端有记录时以服务端为准（标题 / 参数 / 顺序）', () => {
    const local = configWith([{ capability_id: 'D-E08', title: '本地旧卡', args: {} }]);
    const merged = mergeServerPanels(local, [
      { tab_id: 'all', panel_key: TAB_META_KEY, capability_id: TAB_META_KEY, args: { title: '服务端标题' } },
      {
        tab_id: 'all',
        panel_key: 'D-A11#k',
        capability_id: 'D-A11',
        title: '跨资产相关',
        kind: 'series',
        args: { symbol: 'BTC' },
      },
    ]);

    const tab = merged.tabs.find((item) => item.id === 'all')!;
    expect(tab.title).toBe('服务端标题');
    expect(tab.panels).toHaveLength(1);
    expect(tab.panels[0]).toMatchObject({ capability_id: 'D-A11', title: '跨资产相关', kind: 'series' });
  });

  it('服务端空 tab 覆盖本地（清空后不回弹默认卡）', () => {
    const local = configWith([{ capability_id: 'D-E08', title: '卡', args: {} }]);
    const merged = mergeServerPanels(local, [
      { tab_id: 'all', panel_key: TAB_META_KEY, capability_id: TAB_META_KEY, args: { title: '全部出口' } },
    ]);
    expect(merged.tabs.find((tab) => tab.id === 'all')!.panels).toHaveLength(0);
  });

  it('墓碑删除本地自建 tab；服务端未记录的 tab 保留本地', () => {
    const local: BoardConfig = {
      version: 1,
      tabs: [
        { id: 'rec', title: '推荐总览', panels: [], builtin: true },
        { id: 'mine', title: '我的', panels: [], builtin: false },
        { id: 'keep', title: '离线', panels: [], builtin: false },
      ],
      activeId: 'mine',
    };
    const merged = mergeServerPanels(local, [
      { tab_id: 'mine', panel_key: TAB_META_KEY, capability_id: TAB_META_KEY, args: { title: '我的', deleted: true } },
    ]);

    expect(merged.tabs.map((tab) => tab.id)).toEqual(['rec', 'keep']);
    expect(merged.activeId).toBe('rec');
  });

  it('builtin tab 不会被墓碑删除', () => {
    const local = configWith([]);
    const merged = mergeServerPanels(local, [
      { tab_id: 'all', panel_key: TAB_META_KEY, capability_id: TAB_META_KEY, args: { title: '全部', deleted: true } },
    ]);
    expect(merged.tabs.some((tab) => tab.id === 'all')).toBe(true);
  });
});
