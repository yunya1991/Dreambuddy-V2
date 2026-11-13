// 导航单一事实源（SPEC-20261111-A §3.1）
// 所有一级导航入口必须留在 dashboard 壳内；新增入口只改这里，不在 layout 内联。

/** 一级导航模块（按侧栏展示顺序排列） */
export type NavSection = 'overview' | 'agent' | 'trade' | 'system' | 'settings';

export interface NavItem {
  id: string;
  label: string;
  href: string;
  icon: string;
  section: NavSection;
  badgeKey?: 'approval_pending';
}

/** 多条目模块的分组标题；单条目模块（概览 / Agent 工作台 / 通用设置）不显示标题 */
export const SECTION_LABELS: Partial<Record<NavSection, string>> = {
  trade: '交易与研究',
  system: '系统与治理',
};

// 模块顺序：概览 → Agent 工作台 → 交易与研究 → 系统与治理 → 通用设置（单独置底）
export const NAV_ITEMS: NavItem[] = [
  { id: 'overview', label: '概览', href: '/dashboard', icon: '◉', section: 'overview' },
  { id: 'agent', label: 'Agent 工作台', href: '/dashboard/agent', icon: '🤖', section: 'agent' },

  { id: 'fundamental', label: '基本面', href: '/dashboard/fundamental', icon: '📈', section: 'trade' },
  { id: 'ranking', label: '今日热门资产', href: '/dashboard/ranking', icon: '🔥', section: 'trade' },
  { id: 'three-screens', label: '三屏系统', href: '/dashboard/three-screens', icon: '🖥', section: 'trade' },
  { id: 'trade', label: 'AI 交易', href: '/dashboard/trade', icon: '⚡', section: 'trade' },
  { id: 'classic', label: '策略构建', href: '/dashboard/classic', icon: '📊', section: 'trade' },
  { id: 'governance', label: '策略管理', href: '/dashboard/governance', icon: '🏛', section: 'trade' },

  { id: 'monitor', label: 'Agent工作监控', href: '/dashboard/monitor', icon: '🔍', section: 'system' },
  { id: 'memory', label: '记忆管理', href: '/dashboard/memory', icon: '🧠', section: 'system' },
  { id: 'approval', label: '人工审批', href: '/dashboard/board/approval', icon: '🛡️', section: 'system', badgeKey: 'approval_pending' },
  { id: 'reports', label: '报告', href: '/dashboard/reports', icon: '📋', section: 'system' },

  { id: 'settings', label: '通用设置', href: '/dashboard/settings', icon: '⚙', section: 'settings' },
];
