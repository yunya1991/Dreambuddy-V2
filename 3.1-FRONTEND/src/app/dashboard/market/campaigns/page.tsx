'use client';

import { useEffect, useState } from 'react';
import { marketApi } from '@/lib/v3/api';

interface Campaign {
  id: string;
  name: string;
  type: string;
  status: 'DRAFT' | 'APPROVED' | 'APPLIED' | 'PAUSED' | 'EXPIRED';
  direction: string;
  symbol: string;
  confidence: number | null;
  createdAt: string;
}

const STATUS_COLOR: Record<string, string> = {
  DRAFT: '#9ca3af',
  APPROVED: '#60a5fa',
  APPLIED: '#34d399',
  PAUSED: '#f59e0b',
  EXPIRED: '#6b7280',
};
const STATUS_LABEL: Record<string, string> = {
  DRAFT: '草稿',
  APPROVED: '已批准',
  APPLIED: '执行中',
  PAUSED: '已暂停',
  EXPIRED: '已过期',
};

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<string | null>(null);

  useEffect(() => {
    marketApi.getCampaigns()
      .then(data => setCampaigns((data as unknown as Campaign[]) ?? []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered = filterStatus ? campaigns.filter(c => c.status === filterStatus) : campaigns;

  return (
    <div className="px-6 py-4">
      <h1 className="text-xl font-bold text-white mb-1">投放管理</h1>
      <p className="text-xs text-slate-400 mb-6">策略投放活动管理与状态跟踪</p>

      {error && (
        <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-3 mb-4 text-xs text-red-300">
          {error}
        </div>
      )}

      <div className="flex gap-2 flex-wrap mb-4">
        {[null, ...(['DRAFT', 'APPROVED', 'APPLIED', 'PAUSED', 'EXPIRED'] as const)].map(s => (
          <button
            key={s ?? 'all'}
            onClick={() => setFilterStatus(s)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              filterStatus === s
                ? 'bg-indigo-600 text-white'
                : 'bg-slate-800/50 text-slate-400 hover:bg-slate-700/60'
            }`}
          >
            {s ? STATUS_LABEL[s] : '全部'}
          </button>
        ))}
      </div>

      {loading && (
        <div className="space-y-3">
          {[0, 1, 2].map(i => (
            <div key={i} className="h-20 rounded-lg bg-slate-800/50 animate-pulse" />
          ))}
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <p className="text-center text-slate-500 py-16">暂无投放记录</p>
      )}

      <div className="space-y-3">
        {filtered.map(c => (
          <div key={c.id} className="rounded-lg border border-slate-700/30 bg-slate-800/40 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="text-xs px-1.5 py-0.5 rounded font-medium"
                    style={{
                      backgroundColor: (STATUS_COLOR[c.status] || '#9ca3af') + '22',
                      color: STATUS_COLOR[c.status] || '#9ca3af',
                    }}
                  >
                    {STATUS_LABEL[c.status] || c.status}
                  </span>
                  <span className="text-xs text-slate-500">{c.type}</span>
                </div>
                <p className="text-sm font-medium text-white">{c.name}</p>
                <p className="text-xs text-slate-500 mt-1">
                  {c.symbol} · {c.direction}
                  {c.confidence != null ? ` · 置信度 ${(c.confidence * 100).toFixed(0)}%` : ''}
                </p>
              </div>
              <span className="text-xs text-slate-600">
                {new Date(c.createdAt).toLocaleDateString('zh-CN')}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
