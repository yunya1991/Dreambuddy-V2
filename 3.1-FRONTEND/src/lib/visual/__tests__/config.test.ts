import {
  CONFIG_KEY,
  DEFAULT_ACTIVE_TAB,
  DEFAULT_PANELS,
  defaultConfig,
  loadConfig,
  normalizeConfig,
  panelCount,
  parseConfig,
  saveConfig,
  serializeConfig,
  type ConfigStorage,
} from '../config';
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
