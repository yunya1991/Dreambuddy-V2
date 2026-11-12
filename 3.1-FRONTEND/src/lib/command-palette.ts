// ============================================
// 命令面板条目构建（SPEC-20261111-B §3.10 / T-B10）
// ============================================
// 纯函数：导航项（NAV_ITEMS 单一事实源）+ 最近会话 + 固定动作 → 命令列表。
// 不引入 cmdk 等依赖；大小写不敏感子串匹配，最多 20 条。

import { NAV_ITEMS, type NavItem } from '@/lib/navigation';

export type CommandGroup = 'action' | 'nav' | 'session';

export interface CommandItem {
  id: string;
  label: string;
  hint?: string;
  group: CommandGroup;
  href?: string;
  action?: 'new-session' | 'open-reports' | 'toggle-trade-mode';
}

export const COMMAND_GROUP_LABELS: Record<CommandGroup, string> = {
  action: '动作',
  nav: '导航',
  session: '最近会话',
};

export const COMMAND_LIMIT = 20;

const FIXED_ACTIONS: CommandItem[] = [
  { id: 'action:new-session', label: '新建会话', hint: 'Agent 工作台', group: 'action', action: 'new-session' },
  { id: 'action:open-reports', label: '打开报告', hint: '/dashboard/reports', group: 'action', href: '/dashboard/reports' },
  { id: 'action:toggle-trade-mode', label: '切换交易模式', hint: '/dashboard/trade', group: 'action', href: '/dashboard/trade' },
];

export interface CommandSessionInput {
  id: string;
  title: string;
}

export interface BuildCommandItemsInput {
  query?: string;
  sessions?: CommandSessionInput[];
  navItems?: NavItem[];
  limit?: number;
}

/** 导航项 → 命令项（href 由 NAV_ITEMS 提供，禁止在对话框内联路由） */
export function navItemsToCommands(navItems: NavItem[] = NAV_ITEMS): CommandItem[] {
  return navItems.map((item) => ({
    id: `nav:${item.id}`,
    label: item.label,
    hint: item.href,
    group: 'nav' as const,
    href: item.href,
  }));
}

/** 最近会话 → 命令项（深链格式与 T-B7 一致） */
export function sessionsToCommands(sessions: CommandSessionInput[] = []): CommandItem[] {
  return sessions.slice(0, 10).map((session) => ({
    id: `session:${session.id}`,
    label: session.title,
    hint: '最近会话',
    group: 'session' as const,
    href: `/dashboard/agent?session=${encodeURIComponent(session.id)}`,
  }));
}

export function buildCommandItems({
  query = '',
  sessions = [],
  navItems = NAV_ITEMS,
  limit = COMMAND_LIMIT,
}: BuildCommandItemsInput = {}): CommandItem[] {
  const all = [...FIXED_ACTIONS, ...navItemsToCommands(navItems), ...sessionsToCommands(sessions)];
  const needle = query.trim().toLowerCase();
  const matched = needle
    ? all.filter(
        (item) =>
          item.label.toLowerCase().includes(needle) ||
          (item.hint ? item.hint.toLowerCase().includes(needle) : false),
      )
    : all;
  return matched.slice(0, limit);
}
