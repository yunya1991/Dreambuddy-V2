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

const MACRO_ITEMS: { key: string; label: string; digits?: number; suffix?: string; invert?: boolean; percent?: boolean; fixedSignal?: 'bullish' | 'bearish' | 'neutral' }[] = [
  { key: 'policy_score', label: '政策得分', digits: 1 },
  { key: 'cpi_yoy', label: 'CPI同比', digits: 2, suffix: '%' },
  { key: 'fed_funds_rate', label: '联邦基金利率', digits: 2, suffix: '%' },
  { key: 'rate_cycle', label: '利率周期' },
  { key: 'cut_probability', label: '降息概率', digits: 1, suffix: '%', percent: true, fixedSignal: 'bullish' },
  { key: 'hold_probability', label: '维持概率', digits: 1, suffix: '%', percent: true, fixedSignal: 'neutral' },
  { key: 'hike_probability', label: '加息概率', digits: 1, suffix: '%', percent: true, fixedSignal: 'bearish' },
];

function fmt(v: number | string, digits = 2, percent = false): string {
  if (typeof v === 'string') return v;
  if (typeof v !== 'number' || !isFinite(v)) return '--';
  return (percent ? v * 100 : v).toFixed(digits);
}

function signalOf(v: number | string, invert?: boolean, fixedSignal?: 'bullish' | 'bearish' | 'neutral'): 'bullish' | 'bearish' | 'neutral' {
  if (fixedSignal) return fixedSignal;
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
    { label: 'M2 供应', value: fmt(bd.m2_supply, 1), signal: (bd.m2_supply ?? 0) >= 0 ? 'bullish' : 'bearish' },
    { label: 'PPI', value: fmt(bd.ppi, 2), signal: (bd.ppi ?? 0) < 0 ? 'bullish' : 'bearish' },
    { label: '工业产出', value: fmt(bd.industrial_production, 2), signal: (bd.industrial_production ?? 0) >= 0 ? 'bullish' : 'bearish' },
    { label: '点阵图中位数', value: fmt(bd.dot_plot_median, 2), signal: 'neutral' },
    { label: '资产负债表', value: fmt(bd.balance_sheet, 1), signal: (bd.balance_sheet ?? 0) >= 0 ? 'bullish' : 'bearish' },
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
            const sig = signalOf(v as number | string, m.invert, m.fixedSignal);
            return (
              <V3Card key={m.key} padding="sm" hover>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-slate-500">{m.label}</span>
                  <V3Badge variant={signalVariant[sig]} label={signalLabel[sig]} />
                </div>
                <p className="text-base font-semibold text-slate-200">{fmt(v as number | string, m.digits, m.percent)}{m.suffix ?? ''}</p>
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
