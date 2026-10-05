'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';
import MVRVZoneChart from './MVRVZoneChart';

interface ValuationModule {
  metrics?: {
    core?: Record<string, number | string | null>;
    breakdown?: Record<string, number>;
  };
  market_price?: number;
  realized_price?: number;
  nupl?: number;
  price_distance_from_realized?: number;
  meta?: { last_update?: string; source?: string[]; data_quality?: string };
}

function fmt(n: number | string | null | undefined, digits = 2): string {
  if (n === null || n === undefined) return '--';
  if (typeof n === 'string') return n;
  if (typeof n !== 'number' || !isFinite(n)) return '--';
  if (Math.abs(n) >= 10000) return n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return n.toFixed(digits);
}

const VALUATION_ITEMS: { key: string; label: string; digits?: number; suffix?: string }[] = [
  { key: 'mvrv_ratio', label: 'MVRV 比率', digits: 3 },
  { key: 'nvt_ratio', label: 'NVT 比率', digits: 2 },
  { key: 'nvt_z_score', label: 'NVT Z-Score', digits: 2 },
  { key: 'market_cap_usd', label: '市值', suffix: '$' },
  { key: 'valuation_zone', label: '估值区间' },
  { key: 'nupl', label: 'NUPL', digits: 3 },
  { key: 'puell_multiple', label: 'Puell Multiple', digits: 3 },
];

export function ValuationPanel() {
  const [mod, setMod] = useState<ValuationModule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [btcPrice, setBtcPrice] = useState<number | null>(null);
  const [btcChange24h, setBtcChange24h] = useState<number | null>(null);

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

  // BTC 实时价格（OKX 公开行情，非数据采集中心）
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
  const realizedPrice = Number(mod?.realized_price ?? core.realized_price ?? 0);

  const zScore = Number(core.nvt_z_score) ?? 0;
  const mvrvRatio = Number(core.mvrv_ratio) ?? undefined;
  const valuationRange = String(core.valuation_zone || '');

  const rangeSignal = /偏高|过热|热/.test(valuationRange) ? 'bearish' : /偏低|低估/.test(valuationRange) ? 'bullish' : 'neutral';

  const bottomHitCount = Number(bd.bottom_hit_count) || 0;
  const bottomTotalCount = Number(bd.bottom_total_count) || 0;
  const bottomHitRatio = Number(bd.bottom_hit_ratio_pct) || 0;
  const twoYearMa = Number(bd.two_year_ma) || 0;
  const reserveRisk = Number(bd.reserve_risk) || 0;

  return (
    <div className="space-y-4">
      <MVRVZoneChart zScore={zScore} mvrvRatio={mvrvRatio} />

      {(bottomTotalCount > 0 || twoYearMa > 0) && (
        <V3Card padding="md">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-200">抄底信号（12 项指标）</h3>
            <span className="text-[10px] text-slate-500">数据: 19-DAL · CryptoQuant</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">触底信号数</p>
              <p className="text-base font-semibold text-slate-200">{bottomHitCount} / {bottomTotalCount || '--'}</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">触底比例</p>
              <p className="text-base font-semibold text-amber-400">{fmt(bottomHitRatio, 1)}%</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">2年移动均线</p>
              <p className="text-base font-semibold text-slate-200">{fmt(twoYearMa, 3)}</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-1">储备风险</p>
              <p className="text-base font-semibold text-slate-200">{fmt(reserveRisk, 4)}</p>
            </V3Card>
          </div>
        </V3Card>
      )}

      <V3Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-200">估值核心指标</h3>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-emerald-500">MVRV/NUPL/Puell: CryptoQuant</span>
            {mod?.meta?.last_update && (
              <span className="text-[10px] text-slate-500">更新于 {mod.meta.last_update.slice(0, 16).replace('T', ' ')}</span>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {VALUATION_ITEMS.map(m => {
            const v = core[m.key];
            const sig = m.key === 'valuation_zone' ? rangeSignal : 'neutral';
            return (
              <V3Card key={m.key} padding="sm" hover>
                <p className="text-[10px] text-slate-500 mb-1">{m.label}</p>
                <div className="flex items-center justify-between">
                  <p className="text-base font-semibold text-slate-200">{fmt(v as number | string | null, m.digits)}{m.suffix ?? ''}</p>
                  {m.key === 'valuation_zone' && (
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
            <p className="text-base font-semibold text-slate-200">${fmt(realizedPrice, 0)}</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">市价偏离已实现价</p>
            <p className="text-base font-semibold text-amber-400">
              {btcPrice && realizedPrice
                ? `${((btcPrice / realizedPrice - 1) * 100).toFixed(1)}%`
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
            <p className="text-[10px] text-slate-500 mb-1">24h 交易笔数</p>
            <p className="text-base font-semibold text-slate-200">{fmt(bd.tx_count_24h, 0)}</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">输出量 (BTC)</p>
            <p className="text-base font-semibold text-slate-200">{fmt(bd.output_volume_btc, 1)}</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">NVT Z-Score</p>
            <p className="text-base font-semibold text-amber-400">{fmt(core.nvt_z_score, 2)}</p>
          </V3Card>
        </div>
      </V3Card>
    </div>
  );
}

export default ValuationPanel;
