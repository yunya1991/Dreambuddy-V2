import {
  MAX_PANELS_PER_TAB,
  MAX_TABS,
  addPanelToTab,
  addTab,
  buildPanelKey,
  removePanelFromTab,
  removeTab,
  type PanelSpec,
  type PanelTab,
} from '../panelKey';

const tab = (panels: PanelSpec[] = [], builtin = false): PanelTab => ({
  id: 'tab-1',
  title: '跨资产',
  panels,
  builtin,
});

const panel = (args: Record<string, unknown> = {}): PanelSpec => ({
  capability_id: 'D-E17',
  title: '类别看板',
  args,
});

describe('buildPanelKey', () => {
  it('参数键顺序不影响 key', () => {
    expect(buildPanelKey({ capability_id: 'D-A01', args: { a: 1, b: 2 } })).toBe(
      buildPanelKey({ capability_id: 'D-A01', args: { b: 2, a: 1 } }),
    );
  });

  it('参数不同 / 能力不同 → key 不同', () => {
    expect(buildPanelKey({ capability_id: 'D-A01', args: { days: 30 } })).not.toBe(
      buildPanelKey({ capability_id: 'D-A01', args: { days: 60 } }),
    );
    expect(buildPanelKey({ capability_id: 'D-A01', args: {} })).not.toBe(
      buildPanelKey({ capability_id: 'D-E17', args: {} }),
    );
  });
});

describe('addPanelToTab', () => {
  it('同 key 重复添加 → duplicate，不新增', () => {
    const first = addPanelToTab(tab(), panel());
    expect(first.added).toBe(true);
    const second = addPanelToTab(first.tab, panel());
    expect(second.added).toBe(false);
    expect(second.reason).toBe('duplicate');
    expect(second.duplicateIndex).toBe(0);
    expect(second.tab.panels).toHaveLength(1);
  });

  it('到上限 → limit，不静默截断', () => {
    const full = tab(Array.from({ length: MAX_PANELS_PER_TAB }, () => panel({})));
    const result = addPanelToTab(full, { ...panel({ x: 1 }) });
    expect(result.added).toBe(false);
    expect(result.reason).toBe('limit');
    expect(result.tab.panels).toHaveLength(MAX_PANELS_PER_TAB);
  });
});

describe('removePanelFromTab', () => {
  it('只删该 key 的卡', () => {
    const a = addPanelToTab(tab(), panel({ days: 30 })).tab;
    const b = addPanelToTab(a, panel({ days: 60 })).tab;
    const after = removePanelFromTab(b, buildPanelKey({ capability_id: 'D-E17', args: { days: 30 } }));
    expect(after.panels).toHaveLength(1);
    expect(after.panels[0].args.days).toBe(60);
  });
});

describe('tab 增删', () => {
  it('超过 8 个 tab → limit', () => {
    let tabs: PanelTab[] = [];
    for (let index = 0; index < MAX_TABS; index += 1) {
      const result = addTab(tabs, `t${index}`);
      expect(result.added).toBe(true);
      tabs = result.tabs;
    }
    expect(addTab(tabs, 'overflow').added).toBe(false);
  });

  it('builtin tab 不可删，自建可删', () => {
    const tabs: PanelTab[] = [
      { id: 'rec', title: '推荐总览', panels: [], builtin: true },
      { id: 'macro', title: '宏观', panels: [] },
    ];
    expect(removeTab(tabs, 'rec')).toHaveLength(2);
    expect(removeTab(tabs, 'macro')).toHaveLength(1);
  });
});
