'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { V3StatusDot } from '@/components';

const navItems = [
  { label: '概览', href: '/dashboard', icon: '◉' },
  { label: 'AI 交易', href: '/dashboard/trade', icon: '⚡' },
  { label: '经典系统', href: '/dashboard/classic', icon: '📊' },
  { label: '基本面', href: '/dashboard/fundamental', icon: '📈' },
  { label: '三屏系统', href: '/dashboard/three-screens', icon: '🖥' },
  { label: 'SACG 监控', href: '/dashboard/monitor', icon: '🔍' },
  { label: '记忆管理', href: '/dashboard/memory', icon: '🧠' },
  { label: '设置', href: '/dashboard/settings', icon: '⚙' },
  { label: '治理', href: '/dashboard/governance', icon: '🏛' },
  { label: '报告', href: '/dashboard/reports', icon: '📋' },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

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
            return (
              <Link key={item.href} href={item.href}
                className={`flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs transition-colors ${isActive ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-300'}`}>
                <span>{item.icon}</span>
                {!collapsed && <span>{item.label}</span>}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-slate-800">
          <V3StatusDot status="success" size="sm" label="SACG 在线" />
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-[var(--color-bg-primary)]">
        {children}
      </main>
    </div>
  );
}
