'use client';

import { DZEChainView } from '@/components/features/memory/DZEChainView';
import { MemoryTimeline } from '@/components/features/memory/MemoryTimeline';

export default function MemoryPage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">记忆管理</h1>
        <p className="text-xs text-slate-500">D-Z-E 工程链 / BAC 三层压缩</p>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <DZEChainView />
        <MemoryTimeline />
      </div>
    </div>
  );
}
