'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { useMemoryStore, type VmRecord, type QualityLevel } from '@/stores';

// S→success / A→info / B→warning / C→default / D→danger
function qualityVariant(q?: QualityLevel): 'success' | 'info' | 'warning' | 'danger' | 'default' {
  switch (q) {
    case 'S': return 'success';
    case 'A': return 'info';
    case 'B': return 'warning';
    case 'C': return 'default';
    case 'D': return 'danger';
    default: return 'default';
  }
}

function parseTags(tags: VmRecord['tags']): string[] {
  if (Array.isArray(tags)) return tags.filter(Boolean) as string[];
  if (typeof tags === 'string' && tags) return tags.split(',').map(t => t.trim()).filter(Boolean);
  return [];
}

export function MemoryTimeline() {
  const { vmRecords, compressionStats, degraded, loading, fetchRecall, verifyMemory } = useMemoryStore();
  const [verifyingId, setVerifyingId] = useState<string | null>(null);

  useEffect(() => {
    fetchRecall('recent', 20, 'C');
  }, [fetchRecall]);

  const handleVerify = async (id: string, success: boolean) => {
    setVerifyingId(id);
    await verifyMemory(id, success);
    setVerifyingId(null);
  };

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

      {degraded && (
        <V3Card padding="sm" className="border-amber-500/40 bg-amber-900/10">
          <div className="flex items-center gap-2 text-xs text-amber-300">
            <span>⚠</span>
            <span>认知后端降级 — 检查 /api/cognitive/health</span>
          </div>
        </V3Card>
      )}

      <V3Card
        title={`VM 记录（真实 ${vmRecords.length}）`}
        padding="sm"
        actions={
          <button
            onClick={() => fetchRecall('recent', 20, 'C')}
            className="text-[10px] text-slate-400 hover:text-slate-200"
          >
            ↻ 刷新
          </button>
        }
      >
        {loading ? (
          <p className="text-xs text-slate-500 text-center py-6">加载中…</p>
        ) : vmRecords.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-6">暂无 VM 记录</p>
        ) : (
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
            {vmRecords.map((vm: VmRecord) => {
              const q = vm.quality_level;
              const tags = parseTags(vm.tags);
              const isVerifying = verifyingId === vm.id;
              return (
                <div key={vm.id} className="p-2 rounded-lg bg-slate-900/30 border border-slate-700/20">
                  <div className="flex items-start gap-2">
                    {q && <V3Badge variant={qualityVariant(q)} label={q} />}
                    <div className="flex-1 min-w-0">
                      <p className="text-[10px] text-slate-500 font-mono">{vm.id}</p>
                      <p className="text-xs text-slate-300 mt-0.5 line-clamp-2">{vm.content}</p>
                      {tags.length > 0 && (
                        <div className="mt-0.5 flex flex-wrap gap-1">
                          {tags.slice(0, 4).map((t, i) => (
                            <span key={i} className="text-[9px] text-slate-500">#{t}</span>
                          ))}
                        </div>
                      )}
                      <div className="mt-0.5 flex gap-2 text-[9px] text-slate-600">
                        {typeof vm.confidence === 'number' && <span>conf={vm.confidence.toFixed(2)}</span>}
                        {typeof vm.verify_count === 'number' && <span>verify={vm.verify_count}</span>}
                        {typeof vm.score === 'number' && <span>score={vm.score.toFixed(2)}</span>}
                      </div>
                    </div>
                    <div className="flex flex-col gap-1 shrink-0">
                      <button
                        onClick={() => handleVerify(vm.id, true)}
                        disabled={isVerifying}
                        className="text-[10px] px-2 py-0.5 rounded bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300 disabled:opacity-50"
                        title="verify success"
                      >
                        {isVerifying ? '…' : '✅'}
                      </button>
                      <button
                        onClick={() => handleVerify(vm.id, false)}
                        disabled={isVerifying}
                        className="text-[10px] px-2 py-0.5 rounded bg-rose-600/20 hover:bg-rose-600/40 text-rose-300 disabled:opacity-50"
                        title="verify failure"
                      >
                        {isVerifying ? '…' : '❌'}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </V3Card>
    </div>
  );
}
