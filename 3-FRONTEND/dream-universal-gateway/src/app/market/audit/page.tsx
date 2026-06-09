"use client";

import { useEffect, useState } from "react";

interface AuditEntry {
  id: string;
  action: string;
  resource: string;
  actor: string;
  result: "success" | "failure" | "pending";
  details: string;
  timestamp: string;
}

const RESULT_COLOR = { success:"#4ade80", failure:"#f87171", pending:"#f59e0b" };

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/market/audit").then(r=>r.json())
      .then(j=>{ if(j.success) setEntries(j.data??[]); else setError(j.error); })
      .catch(e=>setError(e.message)).finally(()=>setLoading(false));
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-5xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">分发审计</h1>
        <p className="text-gray-400 text-sm mb-6">内容分发与系统操作审计日志</p>
        {error && <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">{error}</div>}
        {loading && <div className="space-y-2">{[0,1,2,3].map(i=><div key={i} className="h-14 rounded bg-gray-900 animate-pulse"/>)}</div>}
        {!loading && entries.length===0 && <p className="text-center text-gray-500 py-16">暂无审计记录</p>}
        <div className="rounded-xl border border-gray-800 overflow-hidden">
          {entries.map((e,i) => (
            <div key={e.id} className={`flex items-center gap-3 px-4 py-3 text-sm ${i>0?"border-t border-gray-800":""}`}>
              <span className="w-2 h-2 rounded-full shrink-0" style={{backgroundColor:RESULT_COLOR[e.result]}}/>
              <span className="text-gray-300 font-medium w-24 shrink-0 truncate">{e.action}</span>
              <span className="text-gray-400 flex-1 truncate">{e.resource}</span>
              <span className="text-gray-500 text-xs">{e.actor}</span>
              <span className="text-gray-600 text-xs shrink-0">{new Date(e.timestamp).toLocaleString("zh-CN")}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}