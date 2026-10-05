'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';
import UTXOAgeDistribution from './UTXOAgeDistribution';

interface OnchainModule {
  metrics?: {
    core?: Record<string, number | string | null>;
    breakdown?: Record<string, number>;
  };
  meta?: { last_update?: string; source?: string[]; data_quality?: string };
}

function fmt(n: number | string | null | undefined, digits = 2): string {
  if (n === null || n === undefined) return '--';
  if (typeof n === 'string') return n;
  if (typeof n !== 'number' || !isFinite(n)) return '--';
  if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(digits);
}

const ONCHAIN_LABELS: Record<string, string> = {
  active_addresses: '活跃地址',
  hash_rate: '哈希率(EH/s)',
  tx_count_24h: '24h交易笔数',
  exchange_net_flow: '交易所净流(BTC)',
  exchange_reserve_btc: '交易所储备(BTC)',
  whale_netflow_btc: '巨鲸净流(BTC)',
  accumulation_signal: '积累信号',
  network_health: '网络健康',
  onchain_trend: '链上趋势',
  market_cap_usd: '市值(USD)',
};

function signalOf(v: number | string | null | undefined): 'bullish' | 'bearish' | 'neutral' {
  if (v === null || v === undefined) return 'neutral';
  if (typeof v === 'string') {
    if (/流出|卖出|恶化|下降|提币/.test(v)) return 'bearish';
    if (/流入|买入|积累|优秀|上升/.test(v)) return 'bullish';
    return 'neutral';
  }
  if (v > 0) return 'bullish';
  if (v < 0) return 'bearish';
  return 'neutral';
}

export function OnchainPanel() {
  const [mod, setMod] = useState<OnchainModule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fundamentalApi
      .getSnapshot()
      .then(data => {
        const snap = data as { modules?: Record<string, OnchainModule> } | null;
        setMod(snap?.modules?.onchain ?? null);
      })
      .catch(e => setError(e?.message ?? '获取链上数据失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="h-64 rounded-xl bg-slate-800/50 animate-pulse" />;
  }
  if (error) {
    return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">链上数据加载失败：{error}</div>;
  }

  const core = { ...(mod?.metrics?.core ?? {}) };
  const bd = mod?.metrics?.breakdown ?? {};

  const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
  const signalLabel = { bullish: '利多', bearish: '利空', neutral: '中性' };

  const items = Object.entries(core)
    .filter(([k]) => ONCHAIN_LABELS[k])
    .map(([k, v]) => {
      const sig = signalOf(v);
      return { label: ONCHAIN_LABELS[k], value: fmt(v), signal: sig };
    });

  // UTXO 年龄分布：用 hodl_waves_1y_plus / short_term_holder_supply 构造
  const longTerm = Number(bd.hodl_waves_1y_plus) || 0;
  const shortTerm = Number(bd.short_term_holder_supply) || 0;
  const midTerm = Math.max(0, 100 - longTerm - shortTerm);
  const buckets = [
    { age_range: '<1天', percentage: shortTerm * 0.3 },
    { age_range: '1-7天', percentage: shortTerm * 0.3 },
    { age_range: '7-30天', percentage: shortTerm * 0.4 },
    { age_range: '30-90天', percentage: midTerm * 0.4 },
    { age_range: '90-365天', percentage: midTerm * 0.6 },
    { age_range: '1-2年', percentage: longTerm * 0.3 },
    { age_range: '2-3年', percentage: longTerm * 0.3 },
    { age_range: '3-5年', percentage: longTerm * 0.2 },
    { age_range: '>5年', percentage: longTerm * 0.2 },
  ];

  return (
    <div className="space-y-4">
      <V3Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-200">链上核心指标</h3>
          {mod?.meta?.last_update && (
            <span className="text-[10px] text-slate-500">更新于 {mod.meta.last_update.slice(0, 16).replace('T', ' ')}</span>
          )}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {items.map(m => (
            <V3Card key={m.label} padding="sm" hover>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-slate-500">{m.label}</span>
                <V3Badge variant={signalVariant[m.signal]} label={signalLabel[m.signal]} />
              </div>
              <p className="text-base font-semibold text-slate-200">{m.value}</p>
            </V3Card>
          ))}
        </div>
      </V3Card>

      <UTXOAgeDistribution buckets={buckets} />
    </div>
  );
}

export default OnchainPanel;
