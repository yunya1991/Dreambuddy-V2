'use client';

// ============================================================
// /dashboard/memory 概览页 (P3 Step 4)
// - MemoryTabNav 子页导航
// - 平台 VM stats 卡 (从 /api/cognitive/stats 拉取)
// - RecordExperienceForm (P3 双向交互: 写入新 VM)
// - DZEChainView (P2 概念对齐: 4-MEMORY 7 类分类轴)
// - MemoryTimeline (P3: 真实 VM 列表 + verify 按钮)
// ============================================================

import { useEffect } from 'react';
import { V3Card } from '@/components';
import { DZEChainView } from '@/components/features/memory/DZEChainView';
import { MemoryTimeline } from '@/components/features/memory/MemoryTimeline';
import { RecordExperienceForm } from '@/components/features/memory/RecordExperienceForm';
import { MemoryTabNav } from '@/components/features/memory/MemoryTabNav';
import { useMemoryStore, useCognitiveAutoLoad, type QualityLevel } from '@/stores';

const QUALITY_ORDER: QualityLevel[] = ['S', 'A', 'B', 'C', 'D'];
const QUALITY_COLOR: Record<QualityLevel, string> = {
  S: 'text-emerald-400',
  A: 'text-blue-400',
  B: 'text-amber-400',
  C: 'text-slate-300',
  D: 'text-rose-400',
};

export default function MemoryPage() {
  const { stats, degraded, loading } = useMemoryStore();
  const autoLoad = useCognitiveAutoLoad();

  useEffect(() => {
    autoLoad();
  }, [autoLoad]);

  const totalCount = stats?.memory?.total_memories ?? stats?.memories_count ?? stats?.count ?? 0;
  const qDist = stats?.memory?.quality_distribution ?? stats?.quality_distribution ?? {};
  const healthStatus = stats?.memory?.status ?? stats?.distill?.status;

  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">记忆管理</h1>
        <p className="text-xs text-slate-500">D-Z-E 工程链 / BAC 三层压缩 / 平台 VM 双向交互</p>
      </div>
      <MemoryTabNav />

      {degraded && (
        <V3Card padding="sm" className="border-amber-500/40 bg-amber-900/10">
          <div className="flex items-center gap-2 text-xs text-amber-300">
            <span>⚠</span>
            <span>认知后端降级 — 检查 /api/cognitive/health</span>
          </div>
        </V3Card>
      )}

      <div className="grid grid-cols-2 gap-4">
        <V3Card title="平台 VM 统计" padding="sm">
          <div className="grid grid-cols-3 gap-3">
            <div className="text-center">
              <p className="text-lg font-semibold text-slate-200">{totalCount}</p>
              <p className="text-[10px] text-slate-500">总数</p>
            </div>
            <div className="text-center">
              <p className={`text-lg font-semibold ${healthStatus === 'healthy' ? 'text-emerald-400' : 'text-rose-400'}`}>
                {healthStatus ?? '-'}
              </p>
              <p className="text-[10px] text-slate-500">健康</p>
            </div>
            <div className="text-center">
              <p className="text-lg font-semibold text-blue-400">{loading ? '…' : 'ready'}</p>
              <p className="text-[10px] text-slate-500">状态</p>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-5 gap-2">
            {QUALITY_ORDER.map(q => (
              <div key={q} className="text-center">
                <p className={`text-sm font-semibold ${QUALITY_COLOR[q]}`}>{qDist[q] ?? 0}</p>
                <p className="text-[9px] text-slate-500">{q}</p>
              </div>
            ))}
          </div>
        </V3Card>
        <RecordExperienceForm />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <DZEChainView />
        <MemoryTimeline />
      </div>
    </div>
  );
}
