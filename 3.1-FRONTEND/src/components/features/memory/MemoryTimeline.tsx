'use client';

import { V3Card, V3Badge } from '@/components';
import { useMemoryStore } from '@/stores';

const chainVariant = { D: 'sacg-a' as const, Z: 'sacg-s' as const, E: 'sacg-g' as const };

export function MemoryTimeline() {
  const { records, compressionStats } = useMemoryStore();

  return (
    <div className="space-y-4">
      <V3Card title="压缩统计" padding="sm">
        <div className="grid grid-cols-4 gap-3">
          <div className="text-center">
            <p className="text-lg font-semibold text-blue-400">{compressionStats.blueprintCount}</p>
            <p className="text-[10px] text-slate-500">Blueprint</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-purple-400">{compressionStats.architectureCount}</p>
            <p className="text-[10px] text-slate-500">Architecture</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-amber-400">{compressionStats.chronicleCount}</p>
            <p className="text-[10px] text-slate-500">Chronicle</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-slate-200">{(compressionStats.compressionRatio * 100).toFixed(0)}%</p>
            <p className="text-[10px] text-slate-500">压缩率</p>
          </div>
        </div>
      </V3Card>
      <V3Card title="记忆记录" padding="sm">
        {records.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-6">暂无记忆记录</p>
        ) : (
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
            {records.map(record => (
              <div key={record.id} className="flex items-center gap-2 p-2 rounded-lg bg-slate-900/30 border border-slate-700/20">
                <V3Badge variant={chainVariant[record.chain]} label={record.chain} />
                <span className="text-xs text-slate-300 flex-1 truncate">{record.content}</span>
                {record.compressed && <V3Badge variant="success" label="压缩" />}
                <span className="text-[10px] text-slate-600">{new Date(record.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
              </div>
            ))}
          </div>
        )}
      </V3Card>
    </div>
  );
}
