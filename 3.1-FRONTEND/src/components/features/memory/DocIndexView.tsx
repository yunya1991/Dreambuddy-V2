'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Button } from '@/components';

interface DocItem {
  path: string;
  root: string;
  category: string;
  last_synced: string;
  cognitive_linked: boolean;
  size_bytes: number;
}

interface SyncResult {
  action: string;
  recorded: boolean;
  memory_id: string | null;
  reason: string;
  synced_at: string;
  files_scanned: number;
  changes_count?: number;
}

export function DocIndexView() {
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [degraded, setDegraded] = useState(false);
  const [filterRoot, setFilterRoot] = useState<string>('');
  const [filterCategory, setFilterCategory] = useState<string>('');
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);

  useEffect(() => {
    fetch('/api/docs/index')
      .then(r => r.ok ? r.json() : null)
      .catch(() => null)
      .then(data => {
        if (!data || !data.docs) {
          setDegraded(true);
          setLoading(false);
          return;
        }
        setDocs(data.docs);
        setDegraded(false);
        setLoading(false);
      });
  }, []);

  const filtered = docs.filter(d => {
    if (filterRoot && d.root !== filterRoot) return false;
    if (filterCategory && d.category !== filterCategory) return false;
    return true;
  });

  const roots = Array.from(new Set(docs.map(d => d.root)));
  const categories = Array.from(new Set(filtered.map(d => d.category))).sort();

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const res = await fetch('/api/docs/sync', { method: 'POST' });
      const data = res.ok ? await res.json() : null;
      if (!data || data.degraded) {
        setSyncResult({
          action: 'failed',
          recorded: false,
          memory_id: null,
          reason: data?.error || 'sync failed',
          synced_at: new Date().toISOString(),
          files_scanned: 0,
        });
      } else {
        setSyncResult(data);
        // sync 成功后刷新列表（标记 cognitive_linked）
        if (data.memory_id) {
          setDocs(prev => prev.map(d => ({ ...d, cognitive_linked: true })));
        }
      }
    } catch (e) {
      setSyncResult({
        action: 'failed',
        recorded: false,
        memory_id: null,
        reason: e instanceof Error ? e.message : String(e),
        synced_at: new Date().toISOString(),
        files_scanned: 0,
      });
    }
    setSyncing(false);
  };

  return (
    <div className="space-y-4">
      {degraded && (
        <V3Card padding="sm" className="border-amber-500/40 bg-amber-900/10">
          <div className="flex items-center gap-2 text-xs text-amber-300">
            <span>⚠</span>
            <span className="flex-1">文档索引后端不可达。请检查 <code className="text-amber-200">scripts/doc_index_adapter.py</code></span>
          </div>
        </V3Card>
      )}

      <V3Card title="文档索引统计" padding="sm">
        <div className="grid grid-cols-4 gap-3 text-center">
          <div>
            <p className="text-lg font-semibold text-blue-400">{docs.length}</p>
            <p className="text-[10px] text-slate-500">总文档数</p>
          </div>
          <div>
            <p className="text-lg font-semibold text-emerald-400">{docs.filter(d => d.cognitive_linked).length}</p>
            <p className="text-[10px] text-slate-500">已链接认知</p>
          </div>
          <div>
            <p className="text-lg font-semibold text-purple-400">{roots.length}</p>
            <p className="text-[10px] text-slate-500">根目录数</p>
          </div>
          <div>
            <p className="text-lg font-semibold text-amber-400">{categories.length}</p>
            <p className="text-[10px] text-slate-500">分类数</p>
          </div>
        </div>
        {roots.length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-700/30">
            <p className="text-[10px] text-slate-500 mb-1.5">根目录</p>
            <div className="flex flex-wrap gap-1">
              {roots.map(r => (
                <span key={r} className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800/40 text-slate-300 border border-slate-700/40">
                  {r}: {docs.filter(d => d.root === r).length}
                </span>
              ))}
            </div>
          </div>
        )}
      </V3Card>

      <V3Card title="手动触发文档同步" padding="sm">
        <div className="flex items-center gap-3">
          <V3Button
            size="sm"
            variant="primary"
            onClick={handleSync}
            disabled={syncing}
          >
            {syncing ? '同步中...' : '触发 doc-sync'}
          </V3Button>
          <p className="text-[10px] text-slate-500">
            手动触发 DocSyncTrigger.sync → 认知库 record（写入新 VM）
          </p>
        </div>
        {syncResult && (
          <div className={`mt-3 p-2 rounded text-xs ${syncResult.recorded ? 'bg-emerald-900/20 border border-emerald-700/40 text-emerald-300' : 'bg-rose-900/20 border border-rose-700/40 text-rose-300'}`}>
            <div className="flex items-center gap-2 mb-1">
              <span>{syncResult.recorded ? '✓' : '✗'}</span>
              <span className="font-medium">{syncResult.action}</span>
              {syncResult.memory_id && (
                <span className="px-1.5 py-0.5 rounded bg-slate-800/60 text-[10px]">{syncResult.memory_id}</span>
              )}
            </div>
            <p className="text-[10px] text-slate-400">{syncResult.reason}</p>
            <p className="text-[10px] text-slate-500 mt-0.5">
              扫描 {syncResult.files_scanned} 文件
              {syncResult.changes_count !== undefined && ` · ${syncResult.changes_count} 变更`}
              {' · '}{new Date(syncResult.synced_at).toLocaleString('zh-CN')}
            </p>
          </div>
        )}
      </V3Card>

      <V3Card title={`文档列表（${filtered.length} / ${docs.length}）`} padding="sm">
        <div className="flex gap-2 mb-3 text-xs">
          <select
            value={filterRoot}
            onChange={(e) => setFilterRoot(e.target.value)}
            className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200"
          >
            <option value="">所有根目录</option>
            {roots.map(r => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200"
          >
            <option value="">所有分类</option>
            {categories.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        {loading ? (
          <p className="text-xs text-slate-500 text-center py-6">加载中...</p>
        ) : filtered.length === 0 ? (
          <p className="text-xs text-slate-500 text-center py-6">无匹配文档</p>
        ) : (
          <div className="space-y-1 max-h-[400px] overflow-y-auto">
            {filtered.slice(0, 100).map(doc => (
              <div key={doc.path} className="flex items-start gap-2 p-2 rounded-lg bg-slate-900/30 border border-slate-700/20">
                <span className={`px-1.5 py-0.5 rounded text-[9px] border font-bold ${doc.cognitive_linked ? 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40' : 'bg-slate-700/40 text-slate-400 border-slate-600/40'}`}>
                  {doc.cognitive_linked ? '已链接' : '未链接'}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-slate-200 truncate">{doc.path}</p>
                  <p className="text-[10px] text-slate-500">
                    {doc.root} / {doc.category}
                    {doc.last_synced && ` · ${new Date(doc.last_synced).toLocaleString('zh-CN')}`}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-0.5 shrink-0">
                  <span className="text-[9px] text-slate-600">{(doc.size_bytes / 1024).toFixed(1)}KB</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </V3Card>
    </div>
  );
}
