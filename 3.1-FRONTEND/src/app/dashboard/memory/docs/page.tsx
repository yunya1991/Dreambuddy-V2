'use client';

import { MemoryTabNav } from '@/components/features/memory/MemoryTabNav';
import { DocIndexView } from '@/components/features/memory/DocIndexView';

export default function DocsPage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">文档索引</h1>
        <p className="text-xs text-slate-500">0-系统文档管理 + 2-KNOWLEDGE 文档索引 + 认知链接状态 + 手动同步</p>
      </div>
      <MemoryTabNav />
      <DocIndexView />
    </div>
  );
}
