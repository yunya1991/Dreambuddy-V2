"use client";

import { useEffect, useState } from "react";

interface ApprovalItem {
  id: string;
  title: string;
  direction: string;
  symbol: string;
  type: string;
  confidence: number | null;
  description: string | null;
  createdAt: string;
}

export default function ApprovalGatePage() {
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Record<string, "approved"|"rejected">>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch("/api/board/approval/pending").then(r=>r.json())
      .then(j=>{ if(j.success) setItems(j.data??[]); else setError(j.error); })
      .catch(e=>setError(e.message)).finally(()=>setLoading(false));
  }, []);

  async function handleDecision(id: string, verdict: "approved"|"rejected") {
    setProcessing(id);
    try {
      const res = await fetch(`/api/board/approval/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict, notes: notes[id] ?? "" }),
      });
      const json = await res.json();
      if (json.success) {
        setDecisions(prev => ({ ...prev, [id]: verdict }));
      } else {
        setError(json.error ?? "操作失败");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "network_error");
    } finally {
      setProcessing(null);
    }
  }

  const pendingItems = items.filter(item => !decisions[item.id]);
  const decidedItems = items.filter(item => decisions[item.id]);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">ApprovalGate — L3 审批</h1>
        <p className="text-gray-400 text-sm mb-6">高风险决策人工审批门禁（L3 级别）</p>
        {error && <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-4 text-sm text-red-300">{error}</div>}

        {loading && <div className="space-y-4">{[0,1].map(i=><div key={i} className="h-40 rounded-xl bg-gray-900 animate-pulse"/>)}</div>}

        {!loading && pendingItems.length===0 && decidedItems.length===0 && (
          <div className="text-center py-16">
            <p className="text-4xl mb-4">✅</p>
            <p className="text-gray-400">暂无待审批项</p>
          </div>
        )}

        {pendingItems.length > 0 && (
          <div className="mb-8">
            <h2 className="text-sm font-medium text-gray-400 mb-3">待审批 ({pendingItems.length})</h2>
            <div className="space-y-4">
              {pendingItems.map(item => (
                <div key={item.id} className="rounded-xl border border-yellow-700/40 bg-gray-900 p-5">
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div>
                      <h3 className="text-sm font-medium text-white">{item.title}</h3>
                      <p className="text-xs text-gray-500 mt-1">
                        {item.symbol} · {item.direction} · {item.type}
                        {item.confidence!=null ? ` · 置信度 ${(item.confidence*100).toFixed(0)}%` : ""}
                      </p>
                    </div>
                    <span className="text-xs text-gray-600">{new Date(item.createdAt).toLocaleDateString("zh-CN")}</span>
                  </div>
                  {item.description && (
                    <p className="text-xs text-gray-400 mb-3 line-clamp-3">{item.description}</p>
                  )}
                  <textarea
                    placeholder="审批意见（可选）"
                    value={notes[item.id] ?? ""}
                    onChange={e => setNotes(prev => ({...prev, [item.id]: e.target.value}))}
                    className="w-full rounded bg-gray-800 border border-gray-700 px-3 py-2 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-indigo-500 mb-3 resize-none"
                    rows={2}
                  />
                  <div className="flex gap-3">
                    <button
                      onClick={() => handleDecision(item.id, "approved")}
                      disabled={processing===item.id}
                      className="px-4 py-2 rounded-md bg-green-700 hover:bg-green-600 text-xs font-medium disabled:opacity-50 transition-colors"
                    >
                      {processing===item.id ? "处理中…" : "✓ 批准"}
                    </button>
                    <button
                      onClick={() => handleDecision(item.id, "rejected")}
                      disabled={processing===item.id}
                      className="px-4 py-2 rounded-md bg-red-800 hover:bg-red-700 text-xs font-medium disabled:opacity-50 transition-colors"
                    >
                      ✗ 驳回
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {decidedItems.length > 0 && (
          <div>
            <h2 className="text-sm font-medium text-gray-400 mb-3">已决策 ({decidedItems.length})</h2>
            <div className="space-y-2">
              {decidedItems.map(item => (
                <div key={item.id} className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-3 flex items-center justify-between text-sm">
                  <span className="text-gray-300 truncate">{item.title}</span>
                  <span className={decisions[item.id]==="approved" ? "text-green-400 text-xs" : "text-red-400 text-xs"}>
                    {decisions[item.id]==="approved" ? "已批准" : "已驳回"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}