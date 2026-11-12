// 导航单一事实源（SPEC-20261111-A §3.1）
// 所有一级导航入口必须留在 dashboard 壳内；新增入口只改这里，不在 layout 内联。

export interface NavItem {
  id: string;
  label: string;
  href: string;
  icon: string;
  section: 'core' | 'collab' | 'governance';
  badgeKey?: 'approval_pending';
}

// 顺序：核心交易在前，协作/治理/报告在底部
export const NAV_ITEMS: NavItem[] = [
  { id: 'overview', label: '概览', href: '/dashboard', icon: '◉', section: 'core' },
  { id: 'trade', label: 'AI 交易', href: '/dashboard/trade', icon: '⚡', section: 'core' },
  { id: 'ranking', label: '交易榜单', href: '/dashboard/ranking', icon: '🏆', section: 'core' },
  { id: 'classic', label: '经典系统', href: '/dashboard/classic', icon: '📊', section: 'core' },
  { id: 'fundamental', label: '基本面', href: '/dashboard/fundamental', icon: '📈', section: 'core' },
  { id: 'three-screens', label: '三屏系统', href: '/dashboard/three-screens', icon: '🖥', section: 'core' },
  { id: 'monitor', label: 'SACG 监控', href: '/dashboard/monitor', icon: '🔍', section: 'core' },
  { id: 'memory', label: '记忆管理', href: '/dashboard/memory', icon: '🧠', section: 'core' },
  { id: 'settings', label: '设置', href: '/dashboard/settings', icon: '⚙', section: 'core' },
  { id: 'governance', label: '治理', href: '/dashboard/governance', icon: '🏛', section: 'governance' },
  { id: 'agent', label: 'Agent 工作台', href: '/dashboard/agent', icon: '🤖', section: 'collab' },
  { id: 'approval', label: '人工审批', href: '/dashboard/board/approval', icon: '🛡️', section: 'governance', badgeKey: 'approval_pending' },
  { id: 'reports', label: '报告', href: '/dashboard/reports', icon: '📋', section: 'governance' },
];
