'use client';

// 数据与图表工作台 — SPEC-54 图表能力展示位（独立页与「基本面」tab 共用）
// 静态资产池首屏 → 回测排行 Top 标的到达后细化（FAIL-OPEN，排行不可用则保持默认池）

import { useCallback, useEffect, useMemo, useState } from 'react';
import { V3Badge, V3Card, V3Empty, V3Spinner } from '@/components';
import { LightsView } from './LightsView';
import { VisualRenderer } from './VisualRenderer';
import type { VisualOverview } from './types';

const KIND_LABEL: Record<string, string> = {
  tree: '思维导图',
  graph: '关系网络',
  series: '曲线',
  table: '表格',
  matrix: '矩阵',
};

export function VisualWorkbench({ compact = false }: { compact?: boolean }) {
  const [data, setData] = useState<VisualOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState('');
  const [rankingSymbols, setRankingSymbols] = useState<string[]>([]);

  const load = useCallback(async (symbols: string[], keepActive: boolean) => {
    const query = symbols.length > 0 ? `?symbols=${encodeURIComponent(symbols.join(','))}` : '';
    const response = await fetch(`/api/visual/overview${query}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload: VisualOverview = await response.json();
    if (!payload?.ok) throw new Error(payload?.error || '后端未返回可用数据');
    setData(payload);
    if (!keepActive) {
      setActiveId(payload.recommended?.[0]?.id || payload.visuals?.[0]?.id || '');
    }
  }, []);

  // 首屏：默认资产池，不等待排行榜
  useEffect(() => {
    let alive = true;
    setLoading(true);
    load([], false)
      .catch(err => alive && setError(err?.message || String(err)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [load]);

  // 细化：回测排行 Top 标的驱动资产池；失败保持默认池
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const response = await fetch('/api/trading-ranking/today', { cache: 'no-store' });
        const ranking = await response.json();
        const symbols: string[] = Array.from(
          new Set(
            (ranking?.items ?? [])
              .map((item: { symbol?: string }) => String(item.symbol ?? '').toUpperCase())
              .filter(Boolean),
          ),
        ).slice(0, 6) as string[];
        if (!alive || symbols.length === 0) return;
        setRankingSymbols(symbols);
        await load(symbols, true);
      } catch {
        /* 排行不可用 → 保持默认资产池 */
      }
    })();
    return () => {
      alive = false;
    };
  }, [load]);

  const visuals = data?.visuals ?? [];
  const lightsPayload = data?.lights ?? null;
  const recommended = (data?.recommended ?? []).filter(item => item.id);
  const activeVisual = useMemo(
    () => visuals.find(visual => visual.id === activeId) ?? visuals[0],
    [visuals, activeId],
  );

  return (
    <div className="space-y-4">
      {compact ? (
        (data?.as_of || data?.degraded) && (
          <div className="flex items-center justify-end gap-2">
            {data?.as_of && <V3Badge variant="info" label={`数据截至 ${data.as_of}`} />}
            {data?.degraded && <V3Badge variant="warning" label="部分降级" />}
          </div>
        )
      ) : (
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-bold text-slate-200">数据与图表</h1>
            <p className="text-xs text-slate-500">统计图表能力总览 · 后端聚合，前端零统计</p>
          </div>
          <div className="flex items-center gap-2">
            {data?.as_of && <V3Badge variant="info" label={`数据截至 ${data.as_of}`} />}
            {data?.degraded && <V3Badge variant="warning" label="部分降级" />}
          </div>
        </div>
      )}

      {error && (
        <V3Card padding="md">
          <V3Empty
            title="图表服务暂不可用"
            description={`${error}。可稍后刷新重试，或先到「基本面」查看数据。`}
          />
        </V3Card>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center gap-2 py-16 text-xs text-slate-500">
          <V3Spinner size="sm" />
          正在聚合跨资产统计…
        </div>
      )}

      {recommended.length > 0 && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-400">动态推荐</h2>
            <p className="text-[10px] text-slate-600">
              {rankingSymbols.length > 0
                ? `资产池跟随回测排行：${rankingSymbols.join(' / ')}`
                : `资产池：${(data?.assets ?? []).join(' / ') || '—'}`}
            </p>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            {recommended.map(item => {
              const active = item.id === activeVisual?.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveId(item.id)}
                  className={`text-left p-3 rounded-xl border bg-slate-800/30 transition-colors ${
                    active
                      ? 'border-indigo-500/50 bg-indigo-500/5'
                      : 'border-slate-700/40 hover:border-slate-600/60'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-medium text-slate-200 truncate">{item.title}</span>
                    <V3Badge variant="default" label={KIND_LABEL[item.kind] ?? item.kind} />
                  </div>
                  <p className="text-[10px] text-slate-500 leading-relaxed">{item.reason}</p>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {lightsPayload && (lightsPayload.rows?.length ?? 0) > 0 && (
        <V3Card
          title="点亮投影"
          subtitle="D-E19 · 趋势 / 惯性 / 周期 / 前瞻 四轴五态（后端判定，前端零重算）"
          padding="md"
        >
          <LightsView payload={lightsPayload} />
        </V3Card>
      )}

      <V3Card
        title="全景观图"
        subtitle={
          activeVisual
            ? `${activeVisual.source_capability} · ${KIND_LABEL[activeVisual.kind] ?? activeVisual.kind}`
            : undefined
        }
        actions={
          visuals.length > 1 ? (
            <div className="flex flex-wrap gap-1">
              {visuals.map(visual => (
                <button
                  key={visual.id}
                  onClick={() => setActiveId(visual.id ?? '')}
                  className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                    visual.id === activeVisual?.id
                      ? 'bg-indigo-600/20 text-indigo-300'
                      : 'text-slate-500 hover:bg-slate-800 hover:text-slate-300'
                  }`}
                >
                  {KIND_LABEL[visual.kind] ?? visual.kind}
                </button>
              ))}
            </div>
          ) : undefined
        }
        padding="md"
      >
        {activeVisual ? (
          <VisualRenderer visual={activeVisual} />
        ) : (
          !loading && (
            <V3Empty
              title="暂无可用图表"
              description="当前资产池未达到统计门禁（样本不足或数据未采集），后端不做推算。"
            />
          )
        )}
      </V3Card>

      {(data?.unavailable?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-slate-700/40 bg-slate-800/20 p-3">
          <p className="text-[10px] font-medium text-slate-400 mb-1">未纳入资产</p>
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {(data?.unavailable ?? []).map(row => (
              <span key={`${row.asset}-${row.reason}`} className="text-[10px] text-slate-500">
                {row.asset}：{row.reason}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
