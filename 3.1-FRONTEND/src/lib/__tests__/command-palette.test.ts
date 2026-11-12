import { buildCommandItems, COMMAND_LIMIT } from '@/lib/command-palette';
import { NAV_ITEMS } from '@/lib/navigation';

describe('command-palette (T-B10)', () => {
  it('空查询返回分组：动作 + 全部导航项 + 最近会话', () => {
    const items = buildCommandItems({
      sessions: [{ id: 's1', title: 'BTC 复盘' }],
    });
    expect(items.filter((i) => i.group === 'action')).toHaveLength(3);
    expect(items.filter((i) => i.group === 'nav')).toHaveLength(NAV_ITEMS.length);
    expect(items.filter((i) => i.group === 'session')).toHaveLength(1);
  });

  it('每个导航项都带可跳转 href', () => {
    const items = buildCommandItems({});
    for (const nav of NAV_ITEMS) {
      const item = items.find((i) => i.id === `nav:${nav.id}`);
      expect(item?.href).toBe(nav.href);
    }
  });

  it('大小写不敏感子串匹配标签与提示', () => {
    expect(buildCommandItems({ query: '报告' }).some((i) => i.id === 'nav:reports')).toBe(true);
    expect(buildCommandItems({ query: 'AGENT' }).some((i) => i.id === 'nav:agent')).toBe(true);
    // hint 命中：/dashboard/board/approval
    expect(buildCommandItems({ query: 'board' }).some((i) => i.id === 'nav:approval')).toBe(true);
  });

  it('最多返回 20 条', () => {
    const sessions = Array.from({ length: 40 }, (_, i) => ({ id: `s${i}`, title: `会话 ${i}` }));
    expect(buildCommandItems({ sessions }).length).toBe(COMMAND_LIMIT);
  });

  it('最近会话命令生成 T-B7 深链', () => {
    const [item] = buildCommandItems({ query: '复盘', sessions: [{ id: 'abc', title: '复盘会话' }] });
    expect(item.group).toBe('session');
    expect(item.href).toBe('/dashboard/agent?session=abc');
  });

  it('无匹配返回空数组', () => {
    expect(buildCommandItems({ query: 'zzz-不存在' })).toHaveLength(0);
  });
});
