'use client';

import { useEffect, useState } from 'react';
import { marketApi } from '@/lib/v3/api';

interface AuditEntry {
  id: string;
  action: string;
  resource: string;
  actor: string;
  result: 'success' | 'failure' | 'pending';
  details: string;
  timestamp: string;
}

const RESULT_COLOR = { success: '#34d399', failure: '#f87171', pending: '#f59e0b' };

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    marketApi.getAudit()
      .then(data => setEntries((data as unknown as AuditEntry[]) ?? []))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="px-6 py-4">
      <h1 className="text-xl font-bold text-white mb-1">分发审计</h1>
      <p className="text-xs text-slate-400 mb-6">内容分发与系统操作审计日志</p>

      {error && (
        <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-3 mb-6 text-xs text-red-300">
          {error}
        </div>
      )}

      {loading && (
        <div className="space-y-2">
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="h-14 rounded bg-slate-800/50 animate-pulse" />
          ))}
        </div>
      )}

      {!loading && entries.length === 0 && (
        <p className="text-center text-slate-500 py-16">暂无审计记录</p>
      )}

      <div className="rounded-xl border border-slate-700/30 overflow-hidden">
        {entries.map((e, i) => (
          <div
            key={e.id}
            className={`flex items-center gap-3 px-4 py-3 text-sm ${
              i > 0 ? 'border-t border-slate-700/30' : ''
            }`}
          >
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ backgroundColor: RESULT_COLOR[e.result] }}
            />
            <span className="text-slate-300 font-medium w-24 shrink-0 truncate">{e.action}</span>
            <span className="text-slate-400 flex-1 truncate">{e.resource}</span>
            <span className="text-slate-500 text-xs">{e.actor}</span>
            <span className="text-slate-600 text-xs shrink-0">
              {new Date(e.timestamp).toLocaleString('zh-CN')}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
