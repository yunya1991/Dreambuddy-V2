'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';
import UTXOAgeDistribution from './UTXOAgeDistribution';

interface OnchainModule {
  metrics?: {
    core?: Record<string, number | string>;
    breakdown?: Record<string, number>;
  };
  meta?: { last_update?: string; source?: string[]; data_quality?: string };
}

function fmt(n: number | string, digits = 2): string {
  if (typeof n === 'string') return n;
  if (typeof n !== 'number' || !isFinite(n)) return '--';
  if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toFixed(digits);
}

const ONCHAIN_LABELS: Record<string, string> = {
  active_addresses: '活跃地址',
  hash_rate: '哈希率(EH/s)',
  n_tx_24h: '24h交易笔数',
  exchange_net_flow: '交易所净流(BTC)',
  exchange_reserve: '交易所储备',
  accumulation_signal: '积累信号',
  network_health: '网络健康',
  onchain_trend: '链上趋势',
  transaction_volume: '交易量',
};

function signalOf(v: number | string): 'bullish' | 'bearish' | 'neutral' {
  if (typeof v === 'string') {
    if (/流出|卖出|恶化|下降/.test(v)) return 'bearish';
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
  const [realOnchain, setRealOnchain] = useState<{ active_addresses?: number; hash_rate_ehs?: number; tx_24h?: number } | null>(null);
  const [panewslab, setPanewslab] = useState<{ exchange?: any } | null>(null);

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

  useEffect(() => {
    fetch('/api/onchain/btc', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => { if (d?.ok) setRealOnchain(d); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch('/api/onchain/panewslab', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => { if (d?.ok) setPanewslab({ exchange: d.exchange }); })
      .catch(() => {});
  }, []);

  if (loading) {
    return <div className="h-64 rounded-xl bg-slate-800/50 animate-pulse" />;
  }
  if (error) {
    return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">链上数据加载失败：{error}</div>;
  }

  const core = { ...(mod?.metrics?.core ?? {}) };
  const bd = mod?.metrics?.breakdown ?? {};

  // 用 blockchain.info 真实数据覆盖 mock 值
  if (realOnchain) {
    if (realOnchain.active_addresses) core.active_addresses = realOnchain.active_addresses;
    if (realOnchain.hash_rate_ehs) core.hash_rate = realOnchain.hash_rate_ehs;
    if (realOnchain.tx_24h) core.n_tx_24h = realOnchain.tx_24h;
  }

  // 用 panewslab (CryptoQuant) 真实交易所数据覆盖
  if (panewslab?.exchange) {
    const ex = panewslab.exchange;
    if (ex.whale_netflow_to_ex_usd !== undefined) {
      // 巨鲸净流向交易所：负值=流出交易所(积累)，正值=流入交易所(抛售)
      const netBtc = ex.whale_netflow_to_ex_usd / 85000; // 按 ~8.5万 USD/BTC 估算
      core.exchange_net_flow = Number(netBtc.toFixed(2));
      core.onchain_trend = ex.whale_netflow_to_ex_usd < 0 ? '流出(积累)' : '流入(抛售)';
      core.accumulation_signal = ex.whale_netflow_to_ex_usd < 0 ? '巨鲸积累' : '巨鲸抛售';
    }
    if (ex.btc_balance !== undefined) {
      core.exchange_reserve = Number((ex.btc_balance / 10000).toFixed(2)); // 万枚
    }
  }

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
