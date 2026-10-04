'use client';

import Link from 'next/link';
import { BACTimeline } from '@/components/features/sacg/BACTimeline';
import { HistoryPlayer } from '@/components/features/sacg/HistoryPlayer';

/**
 * G 层存储子页 — 对应 SPEC §C /dashboard/monitor/graph
 * BAC 压缩 + 历史回放
 */

export default function GraphPage() {
  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Link href="/dashboard/monitor" className="text-xs text-slate-500 hover:text-slate-300">
          ← SACG 监控
        </Link>
      </div>
      <div>
        <h1 className="text-lg font-bold text-slate-200">G 层 · 存储层</h1>
        <p className="text-xs text-slate-500">图记忆 · BAC 压缩 · 持久化</p>
      </div>
      <BACTimeline />
      <HistoryPlayer />
    </div>
  );
}
