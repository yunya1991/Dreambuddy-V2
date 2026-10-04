'use client';

import Link from 'next/link';
import { ReflectorPanel } from '@/components/features/monitor/ReflectorPanel';
import { CrossValidationPanel } from '@/components/features/monitor/CrossValidationPanel';

/**
 * C 层执行子页 — 对应 SPEC §C /dashboard/monitor/compute
 * 反思决策 + 交叉验证
 */

export default function ComputePage() {
  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Link href="/dashboard/monitor" className="text-xs text-slate-500 hover:text-slate-300">
          ← SACG 监控
        </Link>
      </div>
      <div>
        <h1 className="text-lg font-bold text-slate-200">C 层 · 执行层</h1>
        <p className="text-xs text-slate-500">交易执行 · 风控守卫 · 订单管理 · 反思决策</p>
      </div>
      <ReflectorPanel />
      <CrossValidationPanel />
    </div>
  );
}
