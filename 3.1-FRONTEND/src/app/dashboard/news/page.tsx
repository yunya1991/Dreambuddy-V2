'use client';

import { ModuleDetail } from '@/components/features/fundamental/ModuleDetail';
import { HotNewsPanel } from '@/components/features/news/HotNewsPanel';

export default function NewsPage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">新闻监控</h1>
        <p className="text-xs text-slate-500">24h 热点影响力榜 · 语义蒸馏与情绪打分（非预测）</p>
      </div>
      <HotNewsPanel />
      <ModuleDetail module="news" title="新闻监控" />
    </div>
  );
}
