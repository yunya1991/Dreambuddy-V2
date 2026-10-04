'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';

interface SnapshotModules {
  flow?: { metrics?: { core?: Record<string, number | string>; breakdown?: Record<string, number> } };
  valuation?: { metrics?: { core?: Record<string, number | string> }; market_price?: number };
  sentiment?: { metrics?: { core?: Record<string, number | string>; breakdown?: Record<string, number> } };
  onchain?: { metrics?: { core?: Record<string, number | string> } };
  macro?: { metrics?: { core?: Record<string, number | string> } };
  breadth?: { metrics?: { core?: Record<string, number | string> } };
}

function fmt(n: number | string, digits = 2): string {
  if (typeof n === 'string') return n;
  if (typeof n !== 'number' || !isFinite(n)) return '--';
  if (Math.abs(n) >= 1000000000) return `${(n / 1000000000).toFixed(2)}B`;
  if (Math.abs(n) >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toFixed(digits);
}

interface Highlight {
  label: string;
  value: string;
  signal: 'bullish' | 'bearish' | 'neutral';
  group: string;
}

export function OverviewPanel() {
  const [mods, setMods] = useState<SnapshotModules | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [btcPrice, setBtcPrice] = useState<number | null>(null);
  const [btcChange24h, setBtcChange24h] = useState<number | null>(null);
  const [btcDominance, setBtcDominance] = useState<number | null>(null);

  useEffect(() => {
    fundamentalApi
      .getSnapshot()
      .then(data => {
        const snap = data as { modules?: SnapshotModules } | null;
        setMods(snap?.modules ?? null);
      })
      .catch(e => setError(e?.message ?? '获取总览数据失败'))
      .finally(() => setLoading(false));
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

  useEffect(() => {
    fetch('/api/market/global', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => { if (d?.ok) setBtcDominance(Number(d.btc_dominance)); })
      .catch(() => {});
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-3 gap-3">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="h-20 rounded-xl bg-slate-800/50 animate-pulse" />
        ))}
      </div>
    );
  }
  if (error) {
    return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">总览数据加载失败：{error}</div>;
  }

  const flowCore = mods?.flow?.metrics?.core ?? {};
  const valCore = mods?.valuation?.metrics?.core ?? {};
  const senCore = mods?.sentiment?.metrics?.core ?? {};
  const senBd = mods?.sentiment?.metrics?.breakdown ?? {};
  const onchainCore = mods?.onchain?.metrics?.core ?? {};
  const macroCore = mods?.macro?.metrics?.core ?? {};
  const breadthCore = mods?.breadth?.metrics?.core ?? {};

  const highlights: Highlight[] = [
    {
      label: 'BTC 价格',
      value: btcPrice ? `$${fmt(btcPrice, 0)}${btcChange24h !== null ? ` (${btcChange24h >= 0 ? '+' : ''}${btcChange24h.toFixed(2)}%)` : ''}` : '--',
      signal: btcChange24h !== null ? (btcChange24h >= 0 ? 'bullish' : 'bearish') : 'neutral',
      group: '估值',
    },
    { label: 'MVRV-Z', value: fmt(valCore.mvrv_z_score), signal: (Number(valCore.mvrv_z_score) ?? 0) > 1 ? 'bearish' : 'bullish', group: '估值' },
    { label: '估值区间', value: String(valCore.valuation_range || '--'), signal: /偏高|过热/.test(String(valCore.valuation_range)) ? 'bearish' : 'bullish', group: '估值' },
    { label: 'AHR999', value: fmt(valCore.ahr999_index), signal: (Number(valCore.ahr999_index) ?? 0) > 1.2 ? 'bearish' : 'bullish', group: '估值' },

    { label: 'ETF 净流入', value: `${fmt(flowCore.etf_net_flow)}M`, signal: (Number(flowCore.etf_net_flow) ?? 0) >= 0 ? 'bullish' : 'bearish', group: '资金流' },
    { label: '聪明钱方向', value: String(flowCore.smart_money_direction || '--'), signal: /流入/.test(String(flowCore.smart_money_direction)) ? 'bullish' : 'bearish', group: '资金流' },
    { label: '资金费率', value: `${fmt(flowCore.funding_rate, 4)}%`, signal: (Number(flowCore.funding_rate) ?? 0) >= 0 ? 'bullish' : 'bearish', group: '资金流' },
    { label: '多空比', value: fmt(flowCore.long_short_ratio, 2), signal: (Number(flowCore.long_short_ratio) ?? 1) >= 1 ? 'bullish' : 'bearish', group: '资金流' },

    { label: '恐惧贪婪', value: fmt(senCore.fear_greed_index, 0), signal: (Number(senCore.fear_greed_index) ?? 50) >= 55 ? 'bullish' : 'bearish', group: '情绪' },
    { label: '市场心理', value: String(senCore.market_psychology || '--'), signal: /贪婪|乐观/.test(String(senCore.market_psychology)) ? 'bullish' : 'bearish', group: '情绪' },
    { label: '看多比例', value: `${fmt(senBd.bullish_ratio, 1)}%`, signal: 'bullish', group: '情绪' },
    { label: '社交声量', value: fmt(senCore.social_volume), signal: 'neutral', group: '情绪' },

    { label: '链上趋势', value: String(onchainCore.onchain_trend || '--'), signal: /流入|积累/.test(String(onchainCore.onchain_trend)) ? 'bullish' : 'bearish', group: '链上' },
    { label: '积累信号', value: String(onchainCore.accumulation_signal || '--'), signal: /积累/.test(String(onchainCore.accumulation_signal)) ? 'bullish' : 'bearish', group: '链上' },
    { label: '交易所净流', value: `${fmt(onchainCore.exchange_net_flow)} BTC`, signal: (Number(onchainCore.exchange_net_flow) ?? 0) < 0 ? 'bullish' : 'bearish', group: '链上' },
    { label: '网络健康', value: String(onchainCore.network_health || '--'), signal: /优秀|良好/.test(String(onchainCore.network_health)) ? 'bullish' : 'neutral', group: '链上' },

    { label: '流动性时钟', value: String(macroCore.liquidity_clock || '--'), signal: /扩张|转向/.test(String(macroCore.liquidity_clock)) ? 'bullish' : 'bearish', group: '宏观' },
    { label: '宏观风险', value: fmt(macroCore.macro_risk_score, 1), signal: (Number(macroCore.macro_risk_score) ?? 50) < 50 ? 'bullish' : 'bearish', group: '宏观' },
    { label: '通胀压力', value: fmt(macroCore.inflation_pressure, 1), signal: (Number(macroCore.inflation_pressure) ?? 50) < 50 ? 'bullish' : 'bearish', group: '宏观' },
    { label: '美元指数', value: fmt(macroCore.dxy_strength), signal: (Number(macroCore.dxy_strength) ?? 100) < 100 ? 'bullish' : 'bearish', group: '宏观' },

    { label: 'BTC 主导率', value: `${fmt(btcDominance ?? Number(breadthCore.btc_dominance ?? 0), 1)}%`, signal: 'neutral', group: '广度' },
    { label: '广度确认', value: String(breadthCore.breadth_confirmation || '--'), signal: /改善|健康/.test(String(breadthCore.breadth_confirmation)) ? 'bullish' : 'bearish', group: '广度' },
    { label: '涨跌线', value: fmt(breadthCore.advance_decline_line, 2), signal: (Number(breadthCore.advance_decline_line) ?? 0) >= 0 ? 'bullish' : 'bearish', group: '广度' },
    { label: '参与指数', value: fmt(breadthCore.market_participation_index, 1), signal: 'neutral', group: '广度' },
  ];

  const groups = Array.from(new Set(highlights.map(h => h.group)));
  const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
  const signalLabel = { bullish: '利多', bearish: '利空', neutral: '中性' };

  return (
    <div className="space-y-4">
      {groups.map(g => (
        <div key={g}>
          <h3 className="text-xs font-semibold text-slate-400 mb-2">{g}</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {highlights.filter(h => h.group === g).map(h => (
              <V3Card key={h.label} padding="sm" hover>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-slate-500">{h.label}</span>
                  <V3Badge variant={signalVariant[h.signal]} label={signalLabel[h.signal]} />
                </div>
                <p className="text-base font-semibold text-slate-200 truncate">{h.value}</p>
              </V3Card>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default OverviewPanel;
