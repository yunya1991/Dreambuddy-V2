'use client';

import { useEffect, useState, useCallback } from 'react';

interface FeedItem {
  id: string;
  title: string;
  department: string;
  type: string;
  chain_phase: string;
  workflow_type: 'legacy_chain' | 'trading_v2';
  status: string;
  date: string;
  excerpt?: string;
  url: string;
}

const WORKFLOW_BADGE: Record<string, { label: string; color: string }> = {
  legacy_chain: { label: 'Legacy', color: '#6366f1' },
  trading_v2: { label: 'V2', color: '#f59e0b' },
};

const STATUS_COLOR: Record<string, string> = {
  completed: '#4ade80',
  processing: '#60a5fa',
  failed: '#f87171',
  unknown: '#9ca3af',
};

const STATUS_LABEL: Record<string, string> = {
  completed: '已完成',
  processing: '进行中',
  failed: '失败',
  unknown: '未知',
};

export default function FeedPage() {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [workflowFilter, setWorkflowFilter] = useState<string | null>(null);

  const fetchFeed = useCallback(async () => {
    setLoading(true);
    setError(null);
    const qs = workflowFilter ? `?workflow_type=${workflowFilter}` : '';
    try {
      // TODO: migrate to domain client — optional query param ?workflow_type= not supported by feedApi.get()
      const res = await fetch(`/api/feed${qs}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error ?? 'fetch_failed');
      setItems(json.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'unknown');
    } finally {
      setLoading(false);
    }
  }, [workflowFilter]);

  useEffect(() => {
    fetchFeed();
  }, [fetchFeed]);

  return (
    <div className="px-6 py-4">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-white mb-1">信息流</h1>
          <p className="text-xs text-slate-400">Artifact Hub 内容产物实时流</p>
        </div>
        <button
          onClick={fetchFeed}
          disabled={loading}
          className="px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-medium text-white disabled:opacity-50 transition-colors"
        >
          {loading ? '加载中…' : '刷新'}
        </button>
      </div>

      {/* Workflow filter */}
      <div className="flex gap-2 mb-4">
        {[null, 'legacy_chain', 'trading_v2'].map((wt) => (
          <button
            key={wt ?? 'all'}
            onClick={() => setWorkflowFilter(wt as string | null)}
            className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
              workflowFilter === wt
                ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/40'
                : 'bg-slate-800/50 text-slate-400 border border-slate-700/30 hover:bg-slate-800'
            }`}
          >
            {wt ? WORKFLOW_BADGE[wt]?.label : '全部'}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-3 mb-4 text-xs text-red-300">
          连接 Artifact Hub 失败: {error}
        </div>
      )}

      {loading && !items.length && (
        <div className="space-y-3">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 rounded-lg bg-slate-800/50 animate-pulse" />
          ))}
        </div>
      )}

      {!loading && items.length === 0 && (
        <p className="text-center text-slate-500 py-16 text-sm">暂无产物数据</p>
      )}

      <div className="space-y-3">
        {items.map((item) => {
          const wb = WORKFLOW_BADGE[item.workflow_type] ?? {
            label: item.workflow_type,
            color: '#9ca3af',
          };
          return (
            <div
              key={item.id}
              className="rounded-lg border border-slate-700/30 bg-slate-800/40 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span
                      className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: wb.color + '22',
                        color: wb.color,
                      }}
                    >
                      {wb.label}
                    </span>
                    <span className="text-[10px] text-slate-500">
                      {item.chain_phase}
                    </span>
                    <span
                      className="text-[10px]"
                      style={{
                        color: STATUS_COLOR[item.status] || '#9ca3af',
                      }}
                    >
                      {STATUS_LABEL[item.status] || item.status}
                    </span>
                  </div>
                  <h3 className="text-sm font-medium text-slate-200 truncate">
                    {item.title}
                  </h3>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {item.department} · {item.type}
                  </p>
                  {item.excerpt && (
                    <p className="text-xs text-slate-500 mt-1 line-clamp-2">
                      {item.excerpt}
                    </p>
                  )}
                </div>
                <span className="text-[10px] text-slate-600 shrink-0">
                  {item.date}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
