// 导航单一事实源（SPEC-20261111-A §3.1 / SPEC-52 F1）
// 所有一级导航入口必须留在 dashboard 壳内；新增入口只改这里，不在 layout 内联。
// SPEC-52：三层结构 = 平台（工作台/通用能力）｜产品（AI 交易）｜运营（概览/监控/治理）。

/** 一级导航模块（按侧栏展示顺序排列） */
export type NavSection = 'platform' | 'product' | 'operations' | 'settings';

export interface NavItem {
  id: string;
  label: string;
  href: string;
  icon: string;
  section: NavSection;
  badgeKey?: 'approval_pending';
}

/** 多条目模块的分组标题；单条目模块（通用设置）不显示标题 */
export const SECTION_LABELS: Partial<Record<NavSection, string>> = {
  platform: '平台',
  product: '产品',
  operations: '运营',
};

// 模块顺序：平台（工作台置顶）→ 产品（AI 交易）→ 运营 → 通用设置（单独置底）
export const NAV_ITEMS: NavItem[] = [
  { id: 'agent', label: 'Agent 工作台', href: '/dashboard/agent', icon: '🤖', section: 'platform' },
  { id: 'fundamental', label: '基本面', href: '/dashboard/fundamental', icon: '📈', section: 'platform' },
  { id: 'ranking', label: '今日热门资产', href: '/dashboard/ranking', icon: '🔥', section: 'platform' },
  { id: 'three-screens', label: '三屏系统', href: '/dashboard/three-screens', icon: '🖥', section: 'platform' },
  { id: 'plugins', label: '插件', href: '/dashboard/plugins', icon: '🧩', section: 'platform' },

  { id: 'trade', label: 'AI 交易', href: '/dashboard/trade', icon: '⚡', section: 'product' },
  { id: 'classic', label: '策略构建', href: '/dashboard/classic', icon: '📊', section: 'product' },
  { id: 'governance', label: '策略管理', href: '/dashboard/governance', icon: '🏛', section: 'product' },

  { id: 'overview', label: '概览', href: '/dashboard', icon: '◉', section: 'operations' },
  { id: 'monitor', label: 'Agent工作监控', href: '/dashboard/monitor', icon: '🔍', section: 'operations' },
  { id: 'memory', label: '记忆管理', href: '/dashboard/memory', icon: '🧠', section: 'operations' },
  { id: 'approval', label: '人工审批', href: '/dashboard/board/approval', icon: '🛡️', section: 'operations', badgeKey: 'approval_pending' },
  { id: 'reports', label: '报告', href: '/dashboard/reports', icon: '📋', section: 'operations' },
  { id: 'usage', label: '用量与审计', href: '/dashboard/usage', icon: '🧾', section: 'operations' },

  { id: 'settings', label: '通用设置', href: '/dashboard/settings', icon: '⚙', section: 'settings' },
];
