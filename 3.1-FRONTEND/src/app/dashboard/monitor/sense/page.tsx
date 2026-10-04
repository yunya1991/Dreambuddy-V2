'use client';

import Link from 'next/link';
import { SenseConfidenceGauge } from '@/components/features/monitor/SenseConfidenceGauge';

/**
 * S 层感知子页 — 对应 SPEC §C /dashboard/monitor/sense
 */

export default function SensePage() {
  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Link href="/dashboard/monitor" className="text-xs text-slate-500 hover:text-slate-300">
          ← SACG 监控
        </Link>
      </div>
      <div>
        <h1 className="text-lg font-bold text-slate-200">S 层 · 感知层</h1>
        <p className="text-xs text-slate-500">意图识别 · 市场感知 · 多源数据融合</p>
      </div>
      <SenseConfidenceGauge />
    </div>
  );
}
