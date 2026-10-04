'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';

interface BreadthModule {
  metrics?: {
    core?: Record<string, number | string>;
    breakdown?: Record<string, number>;
  };
  meta?: { last_update?: string; source?: string[] };
}

const BREADTH_LABELS: Record<string, string> = {
  btc_dominance: 'BTC 主导率',
  advance_decline_line: '涨跌线',
  breadth_confirmation: '广度确认',
  breadth_divergence_score: '广度背离分',
  market_participation_index: '市场参与指数',
  new_high_low_ratio: '新高新低比',
  divergence_signal: '背离信号',
};

function fmt(n: number | string, digits = 2): string {
  if (typeof n === 'string') return n;
  if (typeof n !== 'number' || !isFinite(n)) return '--';
  return n.toFixed(digits);
}

export function BreadthPanel() {
  const [mod, setMod] = useState<BreadthModule | null>(null);
  const [btcDominance, setBtcDominance] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fundamentalApi
      .getSnapshot()
      .then(data => {
        const snap = data as { modules?: Record<string, BreadthModule> } | null;
        setMod(snap?.modules?.breadth ?? null);
      })
      .catch(e => setError(e?.message ?? '获取广度数据失败'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetch('/api/market/global', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => { if (d?.ok) setBtcDominance(Number(d.btc_dominance)); })
      .catch(() => {});
  }, []);

  if (loading) return <div className="h-48 rounded-xl bg-slate-800/50 animate-pulse" />;
  if (error) return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">广度数据加载失败：{error}</div>;

  const core = { ...(mod?.metrics?.core ?? {}) };
  const bd = mod?.metrics?.breakdown ?? {};
  if (btcDominance !== null) core.btc_dominance = btcDominance;

  const items = Object.entries(core)
    .filter(([k]) => BREADTH_LABELS[k])
    .map(([k, v]) => ({
      label: BREADTH_LABELS[k],
      value: k === 'btc_dominance' ? `${fmt(v as number, 1)}%` : fmt(v as number | string),
    }));

  const sectorItems = [
    { label: 'DeFi 广度', value: fmt(bd.defi_breadth, 1) },
    { label: 'L1 广度', value: fmt(bd.l1_breadth, 1) },
    { label: 'L2 广度', value: fmt(bd.l2_breadth, 1) },
    { label: 'Meme 广度', value: fmt(bd.meme_breadth, 1) },
    { label: '新高数', value: String(bd.new_highs_count ?? '--') },
    { label: '新低数', value: String(bd.new_lows_count ?? '--') },
    { label: '上涨板块', value: String(bd.sector_count_up ?? '--') },
    { label: '下跌板块', value: String(bd.sector_count_down ?? '--') },
  ];

  return (
    <div className="space-y-4">
      <V3Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-200">市场广度核心指标</h3>
          {btcDominance !== null && <span className="text-[10px] text-emerald-500">BTC 主导率: Coingecko 实时</span>}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {items.map(m => (
            <V3Card key={m.label} padding="sm" hover>
              <p className="text-[10px] text-slate-500 mb-1">{m.label}</p>
              <p className="text-base font-semibold text-slate-200">{m.value}</p>
            </V3Card>
          ))}
        </div>
      </V3Card>

      <V3Card padding="md">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">板块广度细分</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {sectorItems.map(m => (
            <V3Card key={m.label} padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">{m.label}</p>
              <p className="text-base font-semibold text-slate-200">{m.value}</p>
            </V3Card>
          ))}
        </div>
        <p className="text-[10px] text-slate-600 mt-2">注：板块广度为快照数据，BTC 主导率为 Coingecko 实时数据。</p>
      </V3Card>
    </div>
  );
}

export default BreadthPanel;
