'use client';

import Link from 'next/link';
import { DAGGraphView } from '@/components/features/monitor/DAGGraphView';

/**
 * A 层编排子页 — 对应 SPEC §C /dashboard/monitor/arrange
 */

export default function ArrangePage() {
  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Link href="/dashboard/monitor" className="text-xs text-slate-500 hover:text-slate-300">
          ← SACG 监控
        </Link>
      </div>
      <div>
        <h1 className="text-lg font-bold text-slate-200">A 层 · 编排层</h1>
        <p className="text-xs text-slate-500">Chain 编排 · DAG 调度 · 并行执行</p>
      </div>
      <DAGGraphView />
    </div>
  );
}
