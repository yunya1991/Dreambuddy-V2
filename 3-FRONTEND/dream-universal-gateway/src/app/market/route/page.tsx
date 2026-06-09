"use client";

import { useEffect, useState } from "react";

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

const LEVEL_COLOR: Record<string, string> = { L1: "#4ade80", L2: "#f59e0b", L3: "#f87171" };

export default function RouteDecisionPage() {
  const [decisions, setDecisions] = useState<RouteDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/market/route")
      .then(r => r.json())
      .then(json => { if (json.success) setDecisions(json.data ?? []); else setError(json.error); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">内容路由决策</h1>
        <p className="text-gray-400 text-sm mb-6">可视化展示路由决策记录与决策等级分布</p>

        {error && <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">{error}</div>}
        {loading && <div className="space-y-3">{[0,1,2].map(i=><div key={i} className="h-20 rounded-lg bg-gray-900 animate-pulse"/>)}</div>}
        {!loading && decisions.length === 0 && <p className="text-center text-gray-500 py-16">暂无路由决策记录</p>}

        <div className="space-y-3">
          {decisions.map(d => (
            <div key={d.id} className="rounded-lg border border-gray-800 bg-gray-900 p-4">
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="flex items-center gap-2">
                  <span
                    className="text-xs font-bold px-1.5 py-0.5 rounded"
                    style={{ backgroundColor: (LEVEL_COLOR[d.decisionLevel] ?? "#9ca3af") + "22", color: LEVEL_COLOR[d.decisionLevel] ?? "#9ca3af" }}
                  >{d.decisionLevel}</span>
                  <span className="text-sm font-medium text-white">{d.selectedRoute}</span>
                </div>
                <span className="text-xs text-gray-500">{new Date(d.createdAt).toLocaleString("zh-CN")}</span>
              </div>
              <p className="text-xs text-gray-400 mb-1">{d.reason}</p>
              <div className="flex gap-3 text-xs text-gray-600">
                <span>部门: {d.department}</span>
                <span>策略版本: {d.policyVersion}</span>
                <span>trace: {d.traceId.slice(0, 8)}…</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}