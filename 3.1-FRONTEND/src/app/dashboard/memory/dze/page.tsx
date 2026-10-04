'use client';

import { MemoryTabNav } from '@/components/features/memory/MemoryTabNav';
import { DZEChainView } from '@/components/features/memory/DZEChainView';

export default function DZEPage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">DZE 工程链</h1>
        <p className="text-xs text-slate-500">设计链 D / 工程链 Z / 评估链 E 压缩视图（4-MEMORY 分类轴对齐）</p>
      </div>
      <MemoryTabNav />
      <DZEChainView />
    </div>
  );
}
