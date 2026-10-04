'use client';

import { useEffect, useState } from 'react';
import { marketApi } from '@/lib/v3/api';

interface EffectivenessRecord {
  id: string;
  name: string;
  totalTrades: number;
  winRate: number;
  pnl: number;
  appliedAt?: string;
}

export default function EffectivenessPage() {
  const [records, setRecords] = useState<EffectivenessRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    marketApi.getEffectiveness()
      .then(data => setRecords((data as unknown as EffectivenessRecord[]) ?? []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="px-6 py-4">
      <h1 className="text-xl font-bold text-white mb-1">效果反馈</h1>
      <p className="text-xs text-slate-400 mb-6">策略执行效果统计与绩效分析</p>

      {error && (
        <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-3 mb-6 text-xs text-red-300">
          {error}
        </div>
      )}

      {loading && (
        <div className="space-y-3">
          {[0, 1, 2].map(i => (
            <div key={i} className="h-24 rounded-lg bg-slate-800/50 animate-pulse" />
          ))}
        </div>
      )}

      {!loading && records.length === 0 && (
        <p className="text-center text-slate-500 py-16">暂无效果数据</p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {records.map(r => (
          <div key={r.id} className="rounded-xl border border-slate-700/30 bg-slate-800/40 p-5">
            <h3 className="text-sm font-medium text-white mb-3 truncate">{r.name}</h3>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <p className="text-xs text-slate-500 mb-1">交易次数</p>
                <p className="text-lg font-bold text-white">{r.totalTrades}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">胜率</p>
                <p
                  className="text-lg font-bold"
                  style={{ color: r.winRate >= 0.5 ? '#34d399' : '#f87171' }}
                >
                  {(r.winRate * 100).toFixed(1)}%
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">盈亏</p>
                <p
                  className="text-lg font-bold"
                  style={{ color: r.pnl >= 0 ? '#34d399' : '#f87171' }}
                >
                  {r.pnl >= 0 ? '+' : ''}
                  {r.pnl.toFixed(2)}
                </p>
              </div>
            </div>
            {r.appliedAt && (
              <p className="text-xs text-slate-600 mt-3">
                执行时间: {new Date(r.appliedAt).toLocaleString('zh-CN')}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
