'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';

interface MacroModule {
  metrics?: {
    core?: Record<string, number | string>;
    breakdown?: Record<string, number>;
  };
  meta?: { last_update?: string; source?: string[]; data_quality?: string };
}

const MACRO_ITEMS: { key: string; label: string; digits?: number; suffix?: string; invert?: boolean }[] = [
  { key: 'dxy_strength', label: '美元指数', digits: 2 },
  { key: 'us10y_yield', label: '美债10Y收益率', digits: 3, suffix: '%' },
  { key: 'inflation_pressure', label: '通胀压力', digits: 1, suffix: '', invert: true },
  { key: 'macro_risk_score', label: '宏观风险', digits: 1, invert: true },
  { key: 'crypto_friendly_score', label: '加密友好度', digits: 1 },
  { key: 'liquidity_clock', label: '流动性时钟' },
  { key: 'growth_expectation', label: '增长预期', digits: 2 },
  { key: 'policy_score', label: '政策得分', digits: 3 },
];

function fmt(v: number | string, digits = 2): string {
  if (typeof v === 'string') return v;
  if (typeof v !== 'number' || !isFinite(v)) return '--';
  return v.toFixed(digits);
}

function signalOf(v: number | string, invert?: boolean): 'bullish' | 'bearish' | 'neutral' {
  if (typeof v === 'string') return 'neutral';
  const val = invert ? -v : v;
  if (val > 0.1) return 'bullish';
  if (val < -0.1) return 'bearish';
  return 'neutral';
}

export function MacroPanel() {
  const [mod, setMod] = useState<MacroModule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fundamentalApi
      .getSnapshot()
      .then(data => {
        const snap = data as { modules?: Record<string, MacroModule> } | null;
        setMod(snap?.modules?.macro ?? null);
      })
      .catch(e => setError(e?.message ?? '获取宏观数据失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="h-48 rounded-xl bg-slate-800/50 animate-pulse" />;
  if (error) return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">宏观数据加载失败：{error}</div>;

  const core = mod?.metrics?.core ?? {};
  const bd = mod?.metrics?.breakdown ?? {};

  const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
  const signalLabel = { bullish: '利多', bearish: '利空', neutral: '中性' };
  type Sig = keyof typeof signalVariant;

  const extraItems: { label: string; value: string; signal: Sig }[] = [
    { label: '美联储鹰派度', value: fmt(bd.fed_policy_hawkishness, 1), signal: 'bearish' },
    { label: '欧央行鹰派度', value: fmt(bd.ecb_policy_hawkishness, 1), signal: 'bearish' },
    { label: '收益率曲线斜率', value: fmt(bd.yield_curve_slope, 2), signal: (bd.yield_curve_slope ?? 0) < 0 ? 'bearish' : 'bullish' },
    { label: '市场流动性', value: fmt(bd.market_liquidity, 1), signal: (bd.market_liquidity ?? 0) >= 50 ? 'bullish' : 'bearish' },
    { label: '避险需求', value: fmt(bd.safe_haven_demand, 1), signal: 'bearish' },
    { label: '风险偏好情绪', value: fmt(bd.risk_on_sentiment, 1), signal: (bd.risk_on_sentiment ?? 0) >= 50 ? 'bullish' : 'bearish' },
  ];

  return (
    <div className="space-y-4">
      <V3Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-200">宏观经济指标</h3>
          {mod?.meta?.last_update && (
            <span className="text-[10px] text-slate-500">更新于 {mod.meta.last_update.slice(0, 16).replace('T', ' ')}</span>
          )}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {MACRO_ITEMS.map(m => {
            const v = core[m.key];
            const sig = signalOf(v as number | string, m.invert);
            return (
              <V3Card key={m.key} padding="sm" hover>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-slate-500">{m.label}</span>
                  <V3Badge variant={signalVariant[sig]} label={signalLabel[sig]} />
                </div>
                <p className="text-base font-semibold text-slate-200">{fmt(v as number | string, m.digits)}{m.suffix ?? ''}</p>
              </V3Card>
            );
          })}
        </div>
      </V3Card>

      <V3Card padding="md">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">政策与流动性细分</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {extraItems.map(m => (
            <V3Card key={m.label} padding="sm">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-slate-500">{m.label}</span>
                <V3Badge variant={signalVariant[m.signal]} label={signalLabel[m.signal]} />
              </div>
              <p className="text-base font-semibold text-slate-200">{m.value}</p>
            </V3Card>
          ))}
        </div>
      </V3Card>
    </div>
  );
}

export default MacroPanel;
