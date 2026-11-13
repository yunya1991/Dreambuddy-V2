'use client';

import { Fragment, useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { V3StatusDot } from '@/components';
import api from '@/lib/api-client';
import GlobalSearchDialog from '@/components/features/search/GlobalSearchDialog';
import { NAV_ITEMS, SECTION_LABELS, type NavItem } from '@/lib/navigation';
import { ToastProvider } from '@/components/feedback/ToastProvider';
import { QueryProvider } from '@/components/providers/QueryProvider';
import {
  TokenMonitorProvider,
  DEFAULT_TOKEN_MONITOR_CONFIG,
  fetchTokenBalance,
  useTokenMonitorContext,
} from '@/lib/token-monitor-provider';
import { getLevelBgColor, getLevelLabel } from '@/lib/token-monitor';
import { TokenMonitorBadge } from '@/components/features/token-monitor/TokenMonitorBadge';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [searchOpen, setSearchOpen] = useState(false);
  // ⌘K / Ctrl+K 全局搜索快捷键
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

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
    <TokenMonitorProvider fetchBalance={fetchTokenBalance} config={DEFAULT_TOKEN_MONITOR_CONFIG}>
      <div className="flex h-screen">
        <aside className={`${collapsed ? 'w-14' : 'w-48'} flex-shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col transition-all duration-200`}>
          <div className="p-3 border-b border-slate-800 flex items-center justify-between">
            {!collapsed && <span className="text-sm font-bold text-indigo-400">DreamBuddy v3</span>}
            <button onClick={() => setCollapsed(!collapsed)} className="text-slate-500 hover:text-slate-300 text-xs">{collapsed ? '›' : '‹'}</button>
          </div>
          <div className="px-2 pb-2">
            <button
              onClick={() => setSearchOpen(true)}
              className="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs text-slate-400 bg-slate-800/60 hover:bg-slate-800 hover:text-slate-300 transition-colors"
            >
              <span>🔍</span>
              {!collapsed && <span className="flex-1 text-left">全局搜索</span>}
              {!collapsed && <kbd className="text-[9px] text-slate-600 border border-slate-700 rounded px-1">⌘K</kbd>}
            </button>
          </div>
          <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
            {NAV_ITEMS.map((item, index) => {
              const prev = NAV_ITEMS[index - 1];
              const isNewSection = item.section !== prev?.section;
              const groupLabel = SECTION_LABELS[item.section];
              const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href));
              const badge = badgeFor(item);
              return (
                <Fragment key={item.href}>
                  {isNewSection && groupLabel && !collapsed && (
                    <p className="px-2.5 pt-3 pb-1 text-[10px] font-semibold tracking-wider text-slate-600">
                      {groupLabel}
                    </p>
                  )}
                  {item.section === 'settings' && (
                    <div className="my-2 border-t border-slate-800" />
                  )}
                  <Link
                    href={item.href}
                    title={item.label}
                    className={`flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs whitespace-nowrap transition-colors ${isActive ? 'bg-indigo-600/20 text-indigo-400' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-300'}`}
                  >
                    <span className="relative inline-flex">
                      {item.icon}
                      {badge > 0 && (
                        <span className="absolute -top-1.5 -right-2 min-w-[14px] h-[14px] px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center leading-none ring-2 ring-slate-900">
                          {badge > 99 ? '99+' : badge}
                        </span>
                      )}
                    </span>
                    {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
                    {!collapsed && badge > 0 && (
                      <span className="text-[9px] text-red-400 font-bold">{badge}</span>
                    )}
                  </Link>
                </Fragment>
              );
            })}
          </nav>
          <div className="p-3 border-t border-slate-800 space-y-2">
            <SidebarTokenMonitor collapsed={collapsed} />
            <div className="flex items-center gap-2">
              <V3StatusDot status="success" size="sm" pulse />
              {!collapsed && <span className="text-[10px] text-slate-500">SACG 在线</span>}
            </div>
          </div>
        </aside>
        <main className="flex-1 overflow-y-auto bg-[var(--color-bg-primary)]">
          <QueryProvider>
            <ToastProvider>{children}</ToastProvider>
          </QueryProvider>
        </main>
        <GlobalSearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} />
      </div>
    </TokenMonitorProvider>
  );
}

/** 侧栏 Token 余额徽标：消费全局监控器，点击进入 /dashboard/token-monitor */
function SidebarTokenMonitor({ collapsed }: { collapsed: boolean }) {
  const { state, isLowBalance, isCritical } = useTokenMonitorContext();

  // 首次成功取数前不渲染，避免展示误导性的 0
  if (!state.lastChecked) return null;

  const needsRecharge = isLowBalance || isCritical || state.isDowngraded;

  if (collapsed) {
    return (
      <Link
        href={needsRecharge ? '/recharge' : '/dashboard/token-monitor'}
        title={
          needsRecharge
            ? `积分不足（${getLevelLabel(state.level)}），点击去充值`
            : `Token：${getLevelLabel(state.level)}`
        }
        className="flex items-center justify-center py-1"
      >
        <span className={`w-2 h-2 rounded-full ${getLevelBgColor(state.level)}`} />
      </Link>
    );
  }

  return (
    <div className="space-y-1">
      <Link href="/dashboard/token-monitor" className="block py-1">
        <TokenMonitorBadge state={state} size="sm" />
      </Link>
      {needsRecharge && (
        <Link
          href="/recharge"
          className="block text-center text-[10px] font-medium text-amber-400 hover:text-amber-300 bg-amber-500/10 rounded px-2 py-1 transition-colors"
        >
          积分不足 · 去充值
        </Link>
      )}
    </div>
  );
}
