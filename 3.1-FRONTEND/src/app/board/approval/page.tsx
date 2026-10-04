'use client';

import { useEffect, useState, useCallback } from 'react';
import { V3Card, V3Badge, V3Empty, V3Spinner } from '@/components';
import { boardApi } from '@/lib/v3/api';

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

type Verdict = 'approved' | 'rejected';

export default function ApprovalGatePage() {
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Verdict>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [expandedNote, setExpandedNote] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const data = (await boardApi.getPendingApprovals()) as unknown as ApprovalItem[];
      setItems(Array.isArray(data) ? data : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const handleDecision = useCallback(async (id: string, verdict: Verdict) => {
    setProcessing(id);
    try {
      const res = await fetch(`/api/board/approval/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ verdict, notes: notes[id] ?? '' }),
      });
      const json = await res.json();
      if (json.success) {
        setDecisions(prev => ({ ...prev, [id]: verdict }));
      } else {
        setError(json.error ?? '操作失败');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'network_error');
    } finally {
      setProcessing(null);
    }
  }, [notes]);

  const pendingItems = items.filter(i => !decisions[i.id]);
  const decidedItems = items
    .filter(i => decisions[i.id])
    .map(i => ({ item: i, verdict: decisions[i.id] }));
  const approvedCount = decidedItems.filter(d => d.verdict === 'approved').length;
  const rejectedCount = decidedItems.filter(d => d.verdict === 'rejected').length;

  const dirVariant = (dir: string): 'success' | 'danger' | 'default' => {
    const d = (dir || '').toUpperCase();
    if (d.includes('LONG') || d.includes('BUY')) return 'success';
    if (d.includes('SHORT') || d.includes('SELL')) return 'danger';
    return 'default';
  };

  return (
    <div className="p-6 space-y-4">
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
            <span>🛡️</span>
            <span>ApprovalGate</span>
            <V3Badge variant="default" className="text-[9px]">L3</V3Badge>
          </h1>
          <p className="text-xs text-slate-500 mt-1">高风险决策人工审批门禁 · 30s 自动刷新</p>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-[10px] text-slate-600">
              最后刷新 {lastRefresh.toLocaleTimeString('zh-CN')}
            </span>
          )}
          <button
            onClick={load}
            className="px-2.5 py-1 rounded text-[11px] bg-slate-800/60 text-slate-300 hover:bg-slate-700/60 transition-colors"
          >
            ↻ 刷新
          </button>
        </div>
      </div>

      {/* 错误 */}
      {error && (
        <V3Card>
          <div className="text-xs text-red-400 flex items-center gap-2">
            <span>⚠</span>
            <span>{error}</span>
            <button onClick={() => setError(null)} className="ml-auto text-slate-500 hover:text-slate-300">×</button>
          </div>
        </V3Card>
      )}

      {/* 统计概览 */}
      {!loading && (
        <div className="grid grid-cols-4 gap-2">
          <V3Card padding="sm">
            <div className="text-center">
              <p className="text-[10px] text-slate-500">待审批</p>
              <p className="text-xl font-bold text-amber-400">{pendingItems.length}</p>
            </div>
          </V3Card>
          <V3Card padding="sm">
            <div className="text-center">
              <p className="text-[10px] text-slate-500">已批准</p>
              <p className="text-xl font-bold text-emerald-400">{approvedCount}</p>
            </div>
          </V3Card>
          <V3Card padding="sm">
            <div className="text-center">
              <p className="text-[10px] text-slate-500">已驳回</p>
              <p className="text-xl font-bold text-red-400">{rejectedCount}</p>
            </div>
          </V3Card>
          <V3Card padding="sm">
            <div className="text-center">
              <p className="text-[10px] text-slate-500">总计</p>
              <p className="text-xl font-bold text-slate-200">{items.length}</p>
            </div>
          </V3Card>
        </div>
      )}

      {/* 加载中 */}
      {loading && (
        <V3Card>
          <div className="flex items-center justify-center py-12">
            <V3Spinner size="md" />
            <span className="ml-3 text-sm text-slate-400">加载审批列表...</span>
          </div>
        </V3Card>
      )}

      {/* 空状态 */}
      {!loading && pendingItems.length === 0 && decidedItems.length === 0 && (
        <V3Card>
          <V3Empty
            title="暂无待审批项"
            description="所有高风险决策已通过审批门禁，新事件将自动出现在此"
            icon={<span className="text-3xl">✅</span>}
          />
        </V3Card>
      )}

      {/* 待审批列表 */}
      {!loading && pendingItems.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-medium text-slate-400">待审批</h2>
            <V3Badge variant="warning" className="text-[9px]">{pendingItems.length}</V3Badge>
          </div>
          {pendingItems.map(item => (
            <V3Card key={item.id} padding="md">
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-medium text-slate-100 truncate">{item.title}</h3>
                  <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
                    <V3Badge variant={dirVariant(item.direction)} className="text-[9px]">{item.direction || '—'}</V3Badge>
                    <V3Badge variant="default" className="text-[9px]">{item.symbol || '—'}</V3Badge>
                    <V3Badge variant="default" className="text-[9px]">{item.type || 'CUSTOM'}</V3Badge>
                    {item.confidence != null && (
                      <span className={`text-[10px] ${item.confidence >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}`}>
                        置信 {(item.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
                <span className="text-[10px] text-slate-600 whitespace-nowrap">
                  {new Date(item.createdAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>

              {item.description && (
                <p className="text-xs text-slate-400 mb-3 line-clamp-3 leading-relaxed">{item.description}</p>
              )}

              {/* 折叠式审批意见 */}
              <div className="mb-3">
                <button
                  onClick={() => setExpandedNote(expandedNote === item.id ? null : item.id)}
                  className="text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
                >
                  {expandedNote === item.id ? '− 隐藏审批意见' : '+ 添加审批意见（可选）'}
                </button>
                {expandedNote === item.id && (
                  <textarea
                    placeholder="审批意见（可选）"
                    value={notes[item.id] ?? ''}
                    onChange={e => setNotes(prev => ({ ...prev, [item.id]: e.target.value }))}
                    className="w-full mt-2 rounded bg-slate-900/50 border border-slate-700/50 px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50 resize-none"
                    rows={2}
                  />
                )}
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => handleDecision(item.id, 'approved')}
                  disabled={processing === item.id}
                  className="px-3 py-1.5 rounded text-xs font-medium bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
                >
                  {processing === item.id ? <V3Spinner size="sm" /> : '✓'}
                  批准
                </button>
                <button
                  onClick={() => handleDecision(item.id, 'rejected')}
                  disabled={processing === item.id}
                  className="px-3 py-1.5 rounded text-xs font-medium bg-red-600/20 text-red-400 hover:bg-red-600/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
                >
                  {processing === item.id ? <V3Spinner size="sm" /> : '✗'}
                  驳回
                </button>
              </div>
            </V3Card>
          ))}
        </div>
      )}

      {/* 已决策列表（折叠） */}
      {!loading && decidedItems.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-medium text-slate-500">已决策</h2>
            <V3Badge variant="default" className="text-[9px]">{decidedItems.length}</V3Badge>
          </div>
          {decidedItems.map(({ item, verdict }) => (
            <div
              key={item.id}
              className="rounded-lg border border-slate-800 bg-slate-900/30 px-3 py-2 flex items-center justify-between gap-2"
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <span className={verdict === 'approved' ? 'text-emerald-400' : 'text-red-400'}>
                  {verdict === 'approved' ? '✓' : '✗'}
                </span>
                <span className="text-xs text-slate-300 truncate">{item.title}</span>
                <V3Badge variant="default" className="text-[9px]">{item.symbol}</V3Badge>
              </div>
              <V3Badge variant={verdict === 'approved' ? 'success' : 'danger'} className="text-[9px]">
                {verdict === 'approved' ? '已批准' : '已驳回'}
              </V3Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
