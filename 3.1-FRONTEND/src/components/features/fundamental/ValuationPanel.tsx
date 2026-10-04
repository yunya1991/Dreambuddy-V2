'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';
import MVRVZoneChart from './MVRVZoneChart';

interface ValuationModule {
  metrics?: {
    core?: Record<string, number | string>;
    breakdown?: Record<string, number>;
  };
  market_price?: number;
  realized_price?: number;
  nupl?: number;
  price_distance_from_realized?: number;
  meta?: { last_update?: string; source?: string[]; data_quality?: string };
}

function fmt(n: number | string, digits = 2): string {
  if (typeof n === 'string') return n;
  if (typeof n !== 'number' || !isFinite(n)) return '--';
  if (Math.abs(n) >= 10000) return n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return n.toFixed(digits);
}

const VALUATION_ITEMS: { key: string; label: string; digits?: number; suffix?: string }[] = [
  { key: 'mvrv_ratio', label: 'MVRV 比率', digits: 3 },
  { key: 'ahr999_index', label: 'AHR999 指数', digits: 2 },
  { key: 'mayer_multiple', label: '梅耶倍数', digits: 3 },
  { key: 'puell_multiple', label: '普尔倍数', digits: 3 },
  { key: 'sopr', label: 'SOPR', digits: 3 },
  { key: 'pi_cycle_top', label: '顶圆周', digits: 3 },
  { key: 'therm_index', label: '热度指数', digits: 1 },
  { key: 'valuation_range', label: '估值区间' },
];

export function ValuationPanel() {
  const [mod, setMod] = useState<ValuationModule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [btcPrice, setBtcPrice] = useState<number | null>(null);
  const [btcChange24h, setBtcChange24h] = useState<number | null>(null);
  const [bgeo, setBgeo] = useState<Record<string, { value: number; date: string }> | null>(null);
  const [panewslab, setPanewslab] = useState<{ cycle?: any; exchange?: any } | null>(null);

  useEffect(() => {
    fundamentalApi
      .getSnapshot()
      .then(data => {
        const snap = data as { modules?: Record<string, ValuationModule> } | null;
        setMod(snap?.modules?.valuation ?? null);
      })
      .catch(e => setError(e?.message ?? '获取估值数据失败'))
      .finally(() => setLoading(false));
  }, []);

  // panewslab (PAData) 聚合 CryptoQuant/CoinGlass 数据，优先级最高
  useEffect(() => {
    fetch('/api/onchain/panewslab', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => { if (d?.ok) setPanewslab({ cycle: d.cycle, exchange: d.exchange }); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch('/api/onchain/bgeometrics?metrics=mvrv,sopr,nupl,puell_multiple,realized_price', { cache: 'force-cache' })
      .then(r => r.json())
      .then(d => { if (d?.ok) setBgeo(d.metrics); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch('/api/price/btc', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => {
        if (d?.ok) {
          setBtcPrice(Number(d.price));
          setBtcChange24h(Number(d.change24h));
        }
      })
      .catch(() => {});
  }, []);

  if (loading) return <div className="h-72 rounded-xl bg-slate-800/50 animate-pulse" />;
  if (error) return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">估值数据加载失败：{error}</div>;

  const core = { ...(mod?.metrics?.core ?? {}) };
  const bd = mod?.metrics?.breakdown ?? {};

  // 用真实链上数据覆盖 mock 值：panewslab(CryptoQuant) 优先，bgeometrics 次之
  if (panewslab?.cycle) {
    const c = panewslab.cycle;
    if (c.mvrv !== undefined) core.mvrv_ratio = c.mvrv;
    if (c.puell_multiple !== undefined) core.puell_multiple = c.puell_multiple;
    if (c.nupl !== undefined) core.nupl = c.nupl;
  }
  if (bgeo) {
    if (bgeo.mvrv && core.mvrv_ratio === undefined) core.mvrv_ratio = bgeo.mvrv.value;
    if (bgeo.sopr) core.sopr = bgeo.sopr.value;
    if (bgeo.nupl && core.nupl === undefined) core.nupl = bgeo.nupl.value;
    if (bgeo.puell_multiple && core.puell_multiple === undefined) core.puell_multiple = bgeo.puell_multiple.value;
    if (bgeo.realized_price && mod) mod.realized_price = bgeo.realized_price.value;
  }

  const zScore = Number(core.mvrv_z_score) ?? 0;
  const mvrvRatio = Number(core.mvrv_ratio) ?? undefined;
  const valuationRange = String(core.valuation_range || '');

  const rangeSignal = /偏高|过热|热/.test(valuationRange) ? 'bearish' : /偏低|低估/.test(valuationRange) ? 'bullish' : 'neutral';

  return (
    <div className="space-y-4">
      <MVRVZoneChart zScore={zScore} mvrvRatio={mvrvRatio} />

      {panewslab?.cycle && (
        <V3Card padding="md">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-200">抄底信号（12 项指标）</h3>
            <span className="text-[10px] text-slate-500">数据: CryptoQuant · {panewslab.cycle.as_of?.slice(0, 10)}</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">触底信号数</p>
              <p className="text-base font-semibold text-slate-200">{panewslab.cycle.bottom_hit_count} / {panewslab.cycle.bottom_total_count}</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">触底比例</p>
              <p className="text-base font-semibold text-amber-400">{fmt(panewslab.cycle.bottom_hit_ratio_pct, 1)}%</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">2年移动均线</p>
              <p className="text-base font-semibold text-slate-200">{fmt(panewslab.cycle.two_year_ma, 3)}</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">储备风险</p>
              <p className="text-base font-semibold text-slate-200">{fmt(panewslab.cycle.reserve_risk, 4)}</p>
            </V3Card>
          </div>
        </V3Card>
      )}

      <V3Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-200">估值核心指标</h3>
          <div className="flex items-center gap-2">
            {panewslab?.cycle && <span className="text-[10px] text-emerald-500">MVRV/PUEL/NUPL: CryptoQuant</span>}
            {!panewslab?.cycle && bgeo && <span className="text-[10px] text-emerald-500">bgeometrics 真实</span>}
            {mod?.meta?.last_update && (
              <span className="text-[10px] text-slate-500">更新于 {mod.meta.last_update.slice(0, 16).replace('T', ' ')}</span>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {VALUATION_ITEMS.map(m => {
            const v = core[m.key];
            const sig = m.key === 'valuation_range' ? rangeSignal : 'neutral';
            return (
              <V3Card key={m.key} padding="sm" hover>
                <p className="text-[10px] text-slate-500 mb-1">{m.label}</p>
                <div className="flex items-center justify-between">
                  <p className="text-base font-semibold text-slate-200">{fmt(v as number | string, m.digits)}{m.suffix ?? ''}</p>
                  {m.key === 'valuation_range' && (
                    <V3Badge variant={sig === 'bearish' ? 'danger' : sig === 'bullish' ? 'success' : 'default'} label={sig === 'bearish' ? '利空' : sig === 'bullish' ? '利多' : '中性'} />
                  )}
                </div>
              </V3Card>
            );
          })}
        </div>
      </V3Card>

      <V3Card padding="md">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">价格与已实现价值</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">市场价格 (OKX)</p>
            <p className="text-base font-semibold text-slate-200">
              ${btcPrice ? fmt(btcPrice, 0) : '--'}
              {btcChange24h !== null && (
                <span className={`ml-1 text-[10px] ${btcChange24h >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                  {btcChange24h >= 0 ? '+' : ''}{btcChange24h.toFixed(2)}%
                </span>
              )}
            </p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">已实现价格</p>
            <p className="text-base font-semibold text-slate-200">${fmt(mod?.realized_price ?? 0, 0)}</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">市价偏离已实现价</p>
            <p className="text-base font-semibold text-amber-400">
              {btcPrice && mod?.realized_price
                ? `${((btcPrice / mod.realized_price - 1) * 100).toFixed(1)}%`
                : '--'}
            </p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">NUPL</p>
            <p className="text-base font-semibold text-emerald-400">{fmt(Number(core.nupl ?? mod?.nupl ?? 0), 3)}</p>
          </V3Card>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-3">
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">长期持有者盈亏</p>
            <p className="text-base font-semibold text-emerald-400">+{fmt(bd.long_term_holder_pnl, 1)}%</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">短期持有者盈亏</p>
            <p className="text-base font-semibold text-emerald-400">+{fmt(bd.short_term_holder_pnl, 1)}%</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">长期 SOPR</p>
            <p className="text-base font-semibold text-slate-200">{fmt(bd.sopr_long_term, 3)}</p>
          </V3Card>
        </div>
      </V3Card>
    </div>
  );
}

export default ValuationPanel;
