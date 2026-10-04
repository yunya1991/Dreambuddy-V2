'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { GovernanceFlow } from '@/components/features/classic/GovernanceFlow';
import { IndicatorPanel } from '@/components/features/classic/IndicatorPanel';

/**
 * 经典交易系统子 Tab 布局
 *
 * 4 个子 Tab 对应后端模块 25/26/27/28：
 * - 策略生成（M25）
 * - 策略管理（M26）
 * - 治理审批（M27）— 内嵌 C0-C8 阶段条
 * - 信号触发（M28）
 *
 * 侧边栏不改，仅页面内子 Tab 路由驱动。
 */

const SUB_TABS = [
  { id: 'generation', label: '策略生成', module: 'M25' },
  { id: 'management', label: '策略管理', module: 'M26' },
  { id: 'governance', label: '治理审批', module: 'M27' },
  { id: 'signals', label: '信号触发', module: 'M28' },
] as const;

export default function ClassicLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const activeSubTab = pathname?.split('/').pop() || 'generation';

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">经典交易系统</h1>
        <p className="text-xs text-slate-500">
          策略生成 → 策略管理 → 治理审批 → 信号触发（对应模块 25/26/27/28）
        </p>
      </div>

      {/* 子 Tab 导航栏（路由驱动） */}
      <div className="flex items-center gap-1 p-1.5 rounded-xl bg-slate-800/50 border border-slate-700/50 overflow-x-auto">
        {SUB_TABS.map((tab) => {
          const isActive = activeSubTab === tab.id;
          return (
            <Link
              key={tab.id}
              href={`/dashboard/classic/${tab.id}`}
              className={`flex-shrink-0 flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-300 border border-transparent'
              }`}
            >
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                isActive ? 'bg-indigo-500 text-white' : 'bg-slate-700 text-slate-400'
              }`}>
                {tab.module}
              </span>
              {tab.label}
            </Link>
          );
        })}
      </div>

      {/* 主内容区：模块面板 + 侧栏 */}
      <div className="grid grid-cols-5 gap-4">
        <div className="col-span-3">{children}</div>
        <div className="col-span-2 space-y-4">
          <GovernanceFlow />
          <IndicatorPanel />
        </div>
      </div>
    </div>
  );
}
