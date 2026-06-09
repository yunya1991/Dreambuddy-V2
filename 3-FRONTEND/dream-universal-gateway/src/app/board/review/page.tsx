"use client";

import { useEffect, useState } from "react";

interface ReviewRecord {
  id: string;
  strategyName: string;
  status: string;
  totalTrades: number;
  winRate: number;
  pnl: number;
  score: number | null;
  review: string | null;
  appliedAt: string | null;
}

interface ApprovalSummary {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
}

export default function ExecutionReviewPage() {
  const [records, setRecords] = useState<ReviewRecord[]>([]);
  const [summary, setSummary] = useState<ApprovalSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scores, setScores] = useState<Record<string, string>>({});

  useEffect(() => {
    Promise.all([
      fetch("/api/board/review").then(r=>r.json()),
      fetch("/api/board/approval/summary").then(r=>r.json()),
    ]).then(([rev, summ]) => {
      if(rev.success) setRecords(rev.data??[]);
      if(summ.success) setSummary(summ.data);
    }).catch(e=>setError(e.message)).finally(()=>setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">执行评审</h1>
        <p className="text-gray-400 text-sm mb-8">执行效果回顾 + 评分 + ApprovalGate 仪表盘</p>
        {error && <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">{error}</div>}

        {/* ApprovalGate dashboard */}
        {summary && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
            {[
              { label:"总审批项", value: summary.total, color:"#9ca3af" },
              { label:"待审批",   value: summary.pending,  color:"#f59e0b" },
              { label:"已批准",   value: summary.approved, color:"#4ade80" },
              { label:"已驳回",   value: summary.rejected, color:"#f87171" },
            ].map(item => (
              <div key={item.label} className="rounded-xl border border-gray-800 bg-gray-900 p-4 text-center">
                <p className="text-xs text-gray-500 mb-1">{item.label}</p>
                <p className="text-2xl font-bold" style={{color:item.color}}>{item.value}</p>
              </div>
            ))}
          </div>
        )}

        {loading && <div className="space-y-3">{[0,1,2].map(i=><div key={i} className="h-28 rounded-xl bg-gray-900 animate-pulse"/>)}</div>}
        {!loading && records.length===0 && <p className="text-center text-gray-500 py-12">暂无评审数据</p>}

        <div className="space-y-4">
          {records.map(rec => (
            <div key={rec.id} className="rounded-xl border border-gray-800 bg-gray-900 p-5">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="text-sm font-medium text-white">{rec.strategyName}</h3>
                  <p className="text-xs text-gray-500 mt-0.5">{rec.status}</p>
                </div>
                <div className="text-right text-xs text-gray-500">
                  {rec.appliedAt && new Date(rec.appliedAt).toLocaleDateString("zh-CN")}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4 mb-3 text-center">
                <div><p className="text-xs text-gray-500">交易次数</p><p className="text-lg font-bold text-white">{rec.totalTrades}</p></div>
                <div><p className="text-xs text-gray-500">胜率</p>
                  <p className="text-lg font-bold" style={{color:rec.winRate>=0.5?"#4ade80":"#f87171"}}>{(rec.winRate*100).toFixed(1)}%</p></div>
                <div><p className="text-xs text-gray-500">盈亏</p>
                  <p className="text-lg font-bold" style={{color:rec.pnl>=0?"#4ade80":"#f87171"}}>{rec.pnl>=0?"+":""}{rec.pnl.toFixed(2)}</p></div>
              </div>
              {rec.review && <p className="text-xs text-gray-400 mb-2 italic">{rec.review}</p>}
              <div className="flex items-center gap-2">
                <input type="number" min="0" max="100" placeholder="评分 (0-100)"
                  value={scores[rec.id]??rec.score?.toString()??""} onChange={e=>setScores(prev=>({...prev,[rec.id]:e.target.value}))}
                  className="w-32 rounded bg-gray-800 border border-gray-700 px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"/>
                <span className="text-xs text-gray-500">/ 100</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}