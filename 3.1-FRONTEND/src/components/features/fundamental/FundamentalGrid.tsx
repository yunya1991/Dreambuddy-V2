'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';

interface CoreMap {
  [k: string]: number | string;
}

interface SnapshotModules {
  onchain?: { metrics?: { core?: CoreMap } };
  valuation?: { metrics?: { core?: CoreMap } };
  flow?: { metrics?: { core?: CoreMap } };
  sentiment?: { metrics?: { core?: CoreMap } };
  macro?: { metrics?: { core?: CoreMap } };
  breadth?: { metrics?: { core?: CoreMap } };
}

function fmt(n: number | string, digits = 2): string {
  if (typeof n === 'string') return n;
  if (typeof n !== 'number' || !isFinite(n)) return '--';
  if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(digits);
}

type Signal = 'bullish' | 'bearish' | 'neutral';

const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
const signalLabel = { bullish: '看多', bearish: '看空', neutral: '中性' };

export function FundamentalGrid() {
  const [mods, setMods] = useState<SnapshotModules | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fundamentalApi
      .getSnapshot()
      .then(data => {
        const snap = data as { modules?: SnapshotModules } | null;
        setMods(snap?.modules ?? null);
      })
      .catch(e => setError(e?.message ?? '获取基本面数据失败'))
      .finally(() => setLoading(false));
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
    return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">基本面数据加载失败：{error}</div>;
  }

  const onchain = mods?.onchain?.metrics?.core ?? {};
  const val = mods?.valuation?.metrics?.core ?? {};
  const flow = mods?.flow?.metrics?.core ?? {};
  const sen = mods?.sentiment?.metrics?.core ?? {};
  const macro = mods?.macro?.metrics?.core ?? {};
  const breadth = mods?.breadth?.metrics?.core ?? {};

  const metrics: { name: string; value: string; signal: Signal; desc: string }[] = [
    {
      name: 'NVT 比率',
      value: fmt(val.nvt_ratio),
      signal: (Number(val.nvt_ratio) ?? 0) > 100 ? 'bearish' : 'bullish',
      desc: '网络价值/交易量',
    },
    {
      name: 'MVRV',
      value: fmt(val.mvrv_ratio, 3),
      signal: (Number(val.mvrv_ratio) ?? 0) > 2 ? 'bearish' : 'bullish',
      desc: '市值/已实现市值',
    },
    {
      name: 'NVT Z-Score',
      value: fmt(val.nvt_z_score),
      signal: (Number(val.nvt_z_score) ?? 0) > 1 ? 'bearish' : 'bullish',
      desc: 'NVT 偏离均值',
    },
    {
      name: '估值区间',
      value: String(val.valuation_zone || '--'),
      signal: /偏高|过热/.test(String(val.valuation_zone)) ? 'bearish' : 'bullish',
      desc: '当前估值位置',
    },
    {
      name: '活跃地址',
      value: fmt(onchain.active_addresses, 0),
      signal: 'neutral',
      desc: '日活跃地址数',
    },
    {
      name: '24h 交易笔数',
      value: fmt(onchain.tx_count_24h, 0),
      signal: 'neutral',
      desc: '链上交易活跃度',
    },
    {
      name: '交易所净流',
      value: `${fmt(onchain.exchange_net_flow)} BTC`,
      signal: (Number(onchain.exchange_net_flow) ?? 0) < 0 ? 'bullish' : 'bearish',
      desc: '负=提币积累',
    },
    {
      name: '哈希率',
      value: `${fmt(onchain.hash_rate, 1)} EH/s`,
      signal: 'neutral',
      desc: '网络算力',
    },
    {
      name: 'ETF 净流入',
      value: `${fmt(flow.etf_total_flow)}M`,
      signal: (Number(flow.etf_total_flow) ?? 0) >= 0 ? 'bullish' : 'bearish',
      desc: '机构资金流向',
    },
    {
      name: '资金流评分',
      value: fmt(flow.fund_flow_score, 1),
      signal: (Number(flow.fund_flow_score) ?? 50) >= 50 ? 'bullish' : 'bearish',
      desc: '综合资金面评分',
    },
    {
      name: '情绪指数',
      value: fmt(sen.sentiment_index, 0),
      signal: (Number(sen.sentiment_index) ?? 50) >= 55 ? 'bullish' : 'bearish',
      desc: String(sen.sentiment_classification || '市场情绪'),
    },
    {
      name: 'BTC 主导率',
      value: `${fmt(breadth.btc_dominance, 1)}%`,
      signal: 'neutral',
      desc: 'BTC 市值占比',
    },
    {
      name: '政策得分',
      value: fmt(macro.policy_score, 1),
      signal: (Number(macro.policy_score) ?? 50) >= 50 ? 'bullish' : 'bearish',
      desc: '宏观政策面',
    },
    {
      name: '利率周期',
      value: String(macro.rate_cycle || '--'),
      signal: /cut|降息/.test(String(macro.rate_cycle)) ? 'bullish' : 'bearish',
      desc: '美联储政策方向',
    },
    {
      name: '市场参与指数',
      value: fmt(breadth.market_participation_index, 1),
      signal: 'neutral',
      desc: '市场广度参与度',
    },
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {metrics.map(m => (
        <V3Card key={m.name} padding="sm" hover>
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-slate-500">{m.name}</span>
            <V3Badge variant={signalVariant[m.signal]} label={signalLabel[m.signal]} />
          </div>
          <p className="text-lg font-semibold text-slate-200 mb-0.5">{m.value}</p>
          <p className="text-[10px] text-slate-500">{m.desc}</p>
        </V3Card>
      ))}
    </div>
  );
}

export default FundamentalGrid;
