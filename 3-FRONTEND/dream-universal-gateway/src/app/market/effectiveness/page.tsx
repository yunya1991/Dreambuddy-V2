"use client";

import { useEffect, useState } from "react";

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
    fetch("/api/market/effectiveness").then(r=>r.json())
      .then(j=>{ if(j.success) setRecords(j.data??[]); else setError(j.error); })
      .catch(e=>setError(e.message)).finally(()=>setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">效果反馈</h1>
        <p className="text-gray-400 text-sm mb-6">策略执行效果统计与绩效分析</p>
        {error && <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">{error}</div>}
        {loading && <div className="space-y-3">{[0,1,2].map(i=><div key={i} className="h-24 rounded-lg bg-gray-900 animate-pulse"/>)}</div>}
        {!loading && records.length===0 && <p className="text-center text-gray-500 py-16">暂无效果数据</p>}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {records.map(r => (
            <div key={r.id} className="rounded-xl border border-gray-800 bg-gray-900 p-5">
              <h3 className="text-sm font-medium text-white mb-3 truncate">{r.name}</h3>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div><p className="text-xs text-gray-500 mb-1">交易次数</p><p className="text-lg font-bold text-white">{r.totalTrades}</p></div>
                <div><p className="text-xs text-gray-500 mb-1">胜率</p>
                  <p className="text-lg font-bold" style={{color:r.winRate>=0.5?"#4ade80":"#f87171"}}>{(r.winRate*100).toFixed(1)}%</p></div>
                <div><p className="text-xs text-gray-500 mb-1">盈亏</p>
                  <p className="text-lg font-bold" style={{color:r.pnl>=0?"#4ade80":"#f87171"}}>{r.pnl>=0?"+":""}{r.pnl.toFixed(2)}</p></div>
              </div>
              {r.appliedAt && <p className="text-xs text-gray-600 mt-3">执行时间: {new Date(r.appliedAt).toLocaleString("zh-CN")}</p>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}