"use client";

import { useEffect, useState, useCallback } from "react";

interface FeedItem {
  id: string;
  title: string;
  department: string;
  type: string;
  chain_phase: string;
  workflow_type: "legacy_chain" | "trading_v2";
  status: string;
  date: string;
  excerpt?: string;
  url: string;
}

const WORKFLOW_BADGE: Record<string, { label: string; color: string }> = {
  legacy_chain: { label: "Legacy", color: "#6366f1" },
  trading_v2:   { label: "V2",     color: "#f59e0b" },
};

const STATUS_COLOR: Record<string, string> = {
  completed:  "#4ade80",
  processing: "#60a5fa",
  failed:     "#f87171",
  unknown:    "#9ca3af",
};

export default function FeedPage() {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [workflowFilter, setWorkflowFilter] = useState<string | null>(null);

  const fetchFeed = useCallback(async () => {
    setLoading(true);
    setError(null);
    const qs = workflowFilter ? `?workflow_type=${workflowFilter}` : "";
    try {
      const res = await fetch(`/api/feed${qs}`);
      const json = await res.json();
      if (!json.success) throw new Error(json.error ?? "fetch_failed");
      setItems(json.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "unknown");
    } finally {
      setLoading(false);
    }
  }, [workflowFilter]);

  useEffect(() => { fetchFeed(); }, [fetchFeed]);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold">/feed — 产物流</h1>
            <p className="text-gray-400 text-sm mt-1">Artifact Hub 内容产物实时流</p>
          </div>
          <button onClick={fetchFeed} disabled={loading}
            className="px-4 py-2 rounded-md bg-indigo-600 hover:bg-indigo-500 text-sm font-medium disabled:opacity-50 transition-colors">
            {loading ? "加载中…" : "刷新"}
          </button>
        </div>

        {/* Workflow filter */}
        <div className="flex gap-2 mb-6">
          {[null, "legacy_chain", "trading_v2"].map(wt => (
            <button key={wt??"all"} onClick={()=>setWorkflowFilter(wt as string|null)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${workflowFilter===wt?"bg-indigo-600 text-white":"bg-gray-800 text-gray-400 hover:bg-gray-700"}`}>
              {wt ? WORKFLOW_BADGE[wt]?.label : "全部"}
            </button>
          ))}
        </div>

        {error && <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">连接 Artifact Hub 失败: {error}</div>}

        {loading && !items.length && (
          <div className="space-y-3">{[0,1,2,3,4].map(i=><div key={i} className="h-20 rounded-lg bg-gray-900 animate-pulse"/>)}</div>
        )}

        {!loading && items.length===0 && <p className="text-center text-gray-500 py-16">暂无产物数据</p>}

        <div className="space-y-3">
          {items.map(item => {
            const wb = WORKFLOW_BADGE[item.workflow_type] ?? { label: item.workflow_type, color: "#9ca3af" };
            return (
              <div key={item.id} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="text-xs font-semibold px-1.5 py-0.5 rounded"
                        style={{backgroundColor:wb.color+"22",color:wb.color}}>{wb.label}</span>
                      <span className="text-xs text-gray-500">{item.chain_phase}</span>
                      <span className="text-xs" style={{color:STATUS_COLOR[item.status]||"#9ca3af"}}>{item.status}</span>
                    </div>
                    <h3 className="text-sm font-medium text-white truncate">{item.title}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{item.department} · {item.type}</p>
                    {item.excerpt && <p className="text-xs text-gray-600 mt-1 line-clamp-2">{item.excerpt}</p>}
                  </div>
                  <span className="text-xs text-gray-600 shrink-0">{item.date}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}