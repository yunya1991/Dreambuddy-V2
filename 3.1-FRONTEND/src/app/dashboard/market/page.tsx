'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { marketApi } from '@/lib/v3/api';

interface RouteDecision {
  id: string;
  traceId: string;
  selectedRoute: string;
  reason: string;
  department: string;
  policyVersion: string;
  decisionLevel: string;
  createdAt: string;
}

interface ContentItem {
  id: string;
  title: string;
  tags: string[];
  department: string;
  type: string;
  date: string;
  status: 'completed' | 'processing' | 'failed' | 'unknown';
  excerpt?: string;
  url: string;
}

const LEVEL_COLOR: Record<string, string> = {
  L1: '#4ade80',
  L2: '#f59e0b',
  L3: '#f87171',
};

const STATUS_LABEL: Record<string, string> = {
  completed: '已完成',
  processing: '进行中',
  failed: '失败',
  unknown: '未知',
};

export default function MarketPage() {
  const [tab, setTab] = useState<'route' | 'content'>('route');
  const [decisions, setDecisions] = useState<RouteDecision[]>([]);
  const [contents, setContents] = useState<ContentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (tab === 'route') {
      setLoading(true);
      setError(null);
      marketApi.getRoute()
        .then(data => setDecisions((data as unknown as RouteDecision[]) ?? []))
        .catch(e => setError(e.message))
        .finally(() => setLoading(false));
    } else {
      setLoading(true);
      setError(null);
      marketApi.getContent()
        .then(data => setContents((data as unknown as ContentItem[]) ?? []))
        .catch(e => setError(e.message))
        .finally(() => setLoading(false));
    }
  }, [tab]);

  return (
    <div className="px-6 py-4">
      <h1 className="text-xl font-bold text-white mb-1">市场行情</h1>
      <p className="text-xs text-slate-400 mb-4">内容路由决策与策略内容池</p>

      {/* Sub-navigation */}
      <div className="flex flex-wrap gap-2 mb-4">
        <Link
          href="/dashboard/market/segments"
          className="px-3 py-1.5 text-xs rounded-full border border-slate-700/30 bg-slate-800/50 text-slate-300 hover:bg-slate-700/60 hover:text-white transition-colors"
        >
          细分
        </Link>
        <Link
          href="/dashboard/market/effectiveness"
          className="px-3 py-1.5 text-xs rounded-full border border-slate-700/30 bg-slate-800/50 text-slate-300 hover:bg-slate-700/60 hover:text-white transition-colors"
        >
          效能
        </Link>
        <Link
          href="/dashboard/market/distribution"
          className="px-3 py-1.5 text-xs rounded-full border border-slate-700/30 bg-slate-800/50 text-slate-300 hover:bg-slate-700/60 hover:text-white transition-colors"
        >
          分发
        </Link>
        <Link
          href="/dashboard/market/campaigns"
          className="px-3 py-1.5 text-xs rounded-full border border-slate-700/30 bg-slate-800/50 text-slate-300 hover:bg-slate-700/60 hover:text-white transition-colors"
        >
          活动
        </Link>
        <Link
          href="/dashboard/market/audit"
          className="px-3 py-1.5 text-xs rounded-full border border-slate-700/30 bg-slate-800/50 text-slate-300 hover:bg-slate-700/60 hover:text-white transition-colors"
        >
          审计
        </Link>
      </div>

      {/* Tab */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setTab('route')}
          className={`px-3 py-1.5 text-xs rounded-lg transition ${
            tab === 'route'
              ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
              : 'bg-slate-800/50 text-slate-400 border border-slate-700/30'
          }`}
        >
          路由决策
        </button>
        <button
          onClick={() => setTab('content')}
          className={`px-3 py-1.5 text-xs rounded-lg transition ${
            tab === 'content'
              ? 'bg-purple-500/20 text-purple-300 border border-purple-500/40'
              : 'bg-slate-800/50 text-slate-400 border border-slate-700/30'
          }`}
        >
          内容池
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-3 mb-4 text-xs text-red-300">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-3">
          {[0, 1, 2].map(i => (
            <div key={i} className="h-20 rounded-lg bg-slate-800/50 animate-pulse" />
          ))}
        </div>
      )}

      {/* Route decisions */}
      {!loading && tab === 'route' && (
        <div className="space-y-3">
          {decisions.length === 0 && (
            <p className="text-center text-slate-500 py-16 text-sm">暂无路由决策记录</p>
          )}
          {decisions.map(d => (
            <div key={d.id} className="rounded-lg border border-slate-700/30 bg-slate-800/40 p-4">
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex items-center gap-2">
                  <span
                    className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                    style={{
                      backgroundColor: (LEVEL_COLOR[d.decisionLevel] ?? '#9ca3af') + '22',
                      color: LEVEL_COLOR[d.decisionLevel] ?? '#9ca3af',
                    }}
                  >
                    {d.decisionLevel}
                  </span>
                  <span className="text-sm font-medium text-slate-200">{d.selectedRoute}</span>
                </div>
                <span className="text-[10px] text-slate-500">
                  {new Date(d.createdAt).toLocaleString('zh-CN')}
                </span>
              </div>
              <p className="text-xs text-slate-400 mb-1">{d.reason}</p>
              <div className="flex gap-3 text-[10px] text-slate-600">
                <span>部门: {d.department}</span>
                <span>版本: {d.policyVersion}</span>
                <span>trace: {d.traceId.slice(0, 8)}…</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Content pool */}
      {!loading && tab === 'content' && (
        <div className="space-y-3">
          {contents.length === 0 && (
            <p className="text-center text-slate-500 py-16 text-sm">暂无内容</p>
          )}
          {contents.map(item => (
            <div key={item.id} className="rounded-lg border border-slate-700/30 bg-slate-800/40 p-4">
              <div className="flex items-center justify-between gap-3 mb-2">
                <span className="text-sm font-medium text-slate-200">{item.title}</span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                  item.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                  item.status === 'processing' ? 'bg-amber-500/20 text-amber-400' :
                  'bg-slate-500/20 text-slate-400'
                }`}>
                  {STATUS_LABEL[item.status] || item.status}
                </span>
              </div>
              {item.excerpt && (
                <p className="text-xs text-slate-400 mb-2 line-clamp-2">{item.excerpt}</p>
              )}
              <div className="flex items-center gap-2 flex-wrap">
                {item.tags.map((tag, i) => (
                  <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/30 text-slate-500">
                    {tag}
                  </span>
                ))}
                <span className="text-[10px] text-slate-600 ml-auto">{item.date}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
