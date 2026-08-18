"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface Proposal {
  id: string;
  title: string;
  status: "DRAFT" | "APPROVED" | "APPLIED" | "PAUSED" | "EXPIRED";
  type: string;
  department: string;
  direction: string;
  symbol: string;
  confidence: number | null;
  edgeScore: number | null;
  createdAt: string;
}

const STATUS_COLOR: Record<string, string> = {
  DRAFT: "#9ca3af", APPROVED: "#60a5fa", APPLIED: "#4ade80", PAUSED: "#f59e0b", EXPIRED: "#6b7280"
};
const STATUS_LABEL: Record<string, string> = {
  DRAFT:"草稿", APPROVED:"已批准", APPLIED:"执行中", PAUSED:"已暂停", EXPIRED:"已过期"
};

export default function ProposalListPage() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/board/proposals").then(r=>r.json())
      .then(j=>{ if(j.success) setProposals(j.data??[]); else setError(j.error); })
      .catch(e=>setError(e.message)).finally(()=>setLoading(false));
  }, []);

  const filtered = filterStatus ? proposals.filter(p=>p.status===filterStatus) : proposals;

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">提案列表</h1>
        <p className="text-gray-400 text-sm mb-6">管委会提案 — 策略提案内容与证据展示</p>
        {error && <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-4 text-sm text-red-300">{error}</div>}
        <div className="flex gap-2 flex-wrap mb-4">
          {[null, "DRAFT","APPROVED","APPLIED","PAUSED","EXPIRED"].map(s => (
            <button key={s??"all"} onClick={()=>setFilterStatus(s as string|null)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${filterStatus===s?"bg-indigo-600 text-white":"bg-gray-800 text-gray-400 hover:bg-gray-700"}`}>
              {s ? STATUS_LABEL[s] : "全部"}
            </button>
          ))}
        </div>
        {loading && <div className="space-y-3">{[0,1,2,3].map(i=><div key={i} className="h-24 rounded-lg bg-gray-900 animate-pulse"/>)}</div>}
        {!loading && filtered.length===0 && <p className="text-center text-gray-500 py-16">暂无提案</p>}
        <div className="space-y-3">
          {filtered.map(p => (
            <Link key={p.id} href={`/board/proposals/${p.id}`}
              className="block rounded-lg border border-gray-800 bg-gray-900 p-4 hover:border-gray-600 transition-colors">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="text-xs px-1.5 py-0.5 rounded font-medium"
                      style={{backgroundColor:(STATUS_COLOR[p.status]||"#9ca3af")+"22",color:STATUS_COLOR[p.status]||"#9ca3af"}}>
                      {STATUS_LABEL[p.status]||p.status}</span>
                    <span className="text-xs text-gray-500">{p.type}</span>
                  </div>
                  <h3 className="text-sm font-medium text-white truncate">{p.title}</h3>
                  <p className="text-xs text-gray-500 mt-1">
                    {p.symbol} · {p.direction}
                    {p.confidence!=null ? ` · 置信度 ${(p.confidence*100).toFixed(0)}%` : ""}
                    {p.edgeScore!=null ? ` · 边际评分 ${p.edgeScore.toFixed(2)}` : ""}
                  </p>
                </div>
                <span className="text-xs text-gray-600 shrink-0">{new Date(p.createdAt).toLocaleDateString("zh-CN")}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}