'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';

interface HeatmapCell {
  category: string;
  score: number;
}

interface SentimentModule {
  heatmap_data?: HeatmapCell[];
  metrics?: {
    core?: Record<string, number | string | null>;
    breakdown?: Record<string, number>;
  };
  meta?: { last_update?: string; source?: string[]; data_quality?: string };
}

function getHeatColor(score: number): string {
  if (score >= 65) return 'bg-emerald-500/60';
  if (score >= 50) return 'bg-emerald-500/30';
  if (score >= 40) return 'bg-slate-500/30';
  return 'bg-red-500/30';
}

function fmt(n: number | string | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return '--';
  if (typeof n === 'string') return n;
  if (typeof n !== 'number' || !isFinite(n)) return '--';
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toFixed(digits);
}

export function SentimentPanel() {
  const [mod, setMod] = useState<SentimentModule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fundamentalApi
      .getSnapshot()
      .then(data => {
        const snap = data as { modules?: Record<string, SentimentModule> } | null;
        setMod(snap?.modules?.sentiment ?? null);
      })
      .catch(e => setError(e?.message ?? '获取情绪数据失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="h-64 rounded-xl bg-slate-800/50 animate-pulse" />;
  if (error) return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">情绪数据加载失败：{error}</div>;

  const heatmap = mod?.heatmap_data ?? [];
  const core = { ...(mod?.metrics?.core ?? {}) };

  const fgIndex = Number(core.sentiment_index ?? core.fear_greed_index ?? 0);
  const marketPsych = String(core.sentiment_classification || core.market_psychology || '');
  const regime = String(core.sentiment_regime || '');

  const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
  type Sig = keyof typeof signalVariant;

  const summaryItems: { label: string; value: string; signal: Sig }[] = [
    { label: '情绪指数', value: `${fmt(fgIndex, 0)}`, signal: fgIndex >= 55 ? 'bullish' : fgIndex <= 45 ? 'bearish' : 'neutral' },
    { label: '情绪分类', value: marketPsych || '--', signal: /贪婪|乐观/.test(marketPsych) ? 'bullish' : /恐惧|悲观/.test(marketPsych) ? 'bearish' : 'neutral' },
    { label: '情绪周期', value: regime || '--', signal: /贪婪|乐观/.test(regime) ? 'bullish' : /恐惧|悲观/.test(regime) ? 'bearish' : 'neutral' },
    { label: '社交声量', value: fmt(core.social_volume), signal: 'neutral' },
  ];

  return (
    <div className="space-y-4">
      <V3Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-200">市场情绪热力图</h3>
          {mod?.meta?.last_update && (
            <span className="text-[10px] text-slate-500">更新于 {mod.meta.last_update.slice(0, 16).replace('T', ' ')}</span>
          )}
        </div>
        {heatmap.length > 0 ? (
          <div className="grid grid-cols-4 gap-2">
            {heatmap.map((c, i) => (
              <div key={i} className={`p-3 rounded-lg ${getHeatColor(c.score)} border border-slate-700/30 text-center`}>
                <p className="text-xs font-medium text-slate-300 truncate">{c.category}</p>
                <p className="text-lg font-bold text-slate-200">{c.score.toFixed(0)}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500 py-8 text-center">暂无热力图数据</p>
        )}
        <div className="flex items-center justify-center gap-4 text-[10px] text-slate-500 mt-3">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-500/30" /> 恐惧</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-slate-500/30" /> 中性</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-emerald-500/60" /> 贪婪</span>
        </div>
      </V3Card>

      <V3Card padding="md">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">情绪核心指标</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {summaryItems.map(m => (
            <V3Card key={m.label} padding="sm" hover>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-slate-500">{m.label}</span>
                <V3Badge variant={signalVariant[m.signal]} label={m.signal === 'bullish' ? '利多' : m.signal === 'bearish' ? '利空' : '中性'} />
              </div>
              <p className="text-base font-semibold text-slate-200">{m.value}</p>
            </V3Card>
          ))}
        </div>
      </V3Card>
    </div>
  );
}

export default SentimentPanel;
