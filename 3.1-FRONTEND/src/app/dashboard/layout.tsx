'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { V3StatusDot } from '@/components';
import api from '@/lib/api-client';

interface NavItem {
  label: string;
  href: string;
  icon: string;
  badgeKey?: 'approval_pending';
}

// 侧边栏顺序：核心交易在前，治理/审批/报告在底部
const navItems: NavItem[] = [
  { label: '概览', href: '/dashboard', icon: '◉' },
  { label: 'AI 交易', href: '/dashboard/trade', icon: '⚡' },
  { label: '交易榜单', href: '/dashboard/ranking', icon: '🏆' },
  { label: '经典系统', href: '/dashboard/classic', icon: '📊' },
  { label: '基本面', href: '/dashboard/fundamental', icon: '📈' },
  { label: '三屏系统', href: '/dashboard/three-screens', icon: '🖥' },
  { label: 'SACG 监控', href: '/dashboard/monitor', icon: '🔍' },
  { label: '记忆管理', href: '/dashboard/memory', icon: '🧠' },
  { label: '设置', href: '/dashboard/settings', icon: '⚙' },
  { label: '治理', href: '/dashboard/governance', icon: '🏛' },
  { label: '人工审批', href: '/board/approval', icon: '🛡️', badgeKey: 'approval_pending' },
  { label: '报告', href: '/dashboard/reports', icon: '📋' },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);

  // 轮询待审批数（30s 一次，badge 提醒）
  useEffect(() => {
    let active = true;
    const fetchPending = async () => {
      try {
        const items = await api.get<unknown[]>('/api/board/approval/pending');
        if (active && Array.isArray(items)) {
          setPendingCount(items.length);
        }
      } catch {
        // 静默：审批接口可能未启用 prisma，不报错
      }
    };
    fetchPending();
    const id = setInterval(fetchPending, 30000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const badgeFor = (item: NavItem): number => {
    if (item.badgeKey === 'approval_pending') return pendingCount;
    return 0;
  };

  return (
    <div className="flex h-screen">
      <aside className={`${collapsed ? 'w-14' : 'w-48'} flex-shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col transition-all duration-200`}>
        <div className="p-3 border-b border-slate-800 flex items-center justify-between">
          {!collapsed && <span className="text-sm font-bold text-indigo-400">DreamBuddy v3</span>}
          <button onClick={() => setCollapsed(!collapsed)} className="text-slate-500 hover:text-slate-300 text-xs">{collapsed ? '›' : '‹'}</button>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          {navItems.map(item => {
            const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href));
            const badge = badgeFor(item);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs transition-colors ${isActive ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-300'}`}
              >
                <span className="relative inline-flex">
                  {item.icon}
                  {badge > 0 && (
                    <span className="absolute -top-1.5 -right-2 min-w-[14px] h-[14px] px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center leading-none ring-2 ring-slate-900">
                      {badge > 99 ? '99+' : badge}
                    </span>
                  )}
                </span>
                {!collapsed && <span className="flex-1">{item.label}</span>}
                {!collapsed && badge > 0 && (
                  <span className="text-[9px] text-red-400 font-bold">{badge}</span>
                )}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-slate-800">
          <div className="flex items-center gap-2">
            <V3StatusDot status="success" size="sm" pulse />
            {!collapsed && <span className="text-[10px] text-slate-500">SACG 在线</span>}
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-[var(--color-bg-primary)]">
        {children}
      </main>
    </div>
  );
}
