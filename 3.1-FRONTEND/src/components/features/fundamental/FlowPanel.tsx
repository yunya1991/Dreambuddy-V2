'use client';

import { useEffect, useState } from 'react';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';
import NetFlowTrendChart from './NetFlowTrendChart';
import WhaleTracker from './WhaleTracker';

interface FlowTimeseriesPoint {
  timestamp?: string;
  value?: number;
  direction_score?: number;
  velocity?: number;
}

interface FlowMetrics {
  core?: {
    etf_total_flow?: number;
    fund_flow_score?: number;
    funding_rate?: number | null;
    liquidation_pressure?: number;
    long_short_ratio?: number | null;
    smart_money_direction?: string;
    stablecoin_dominance_usdt?: number;
    stablecoin_dominance_usdc?: number;
    flow_regime?: string;
    whale_activity?: number;
  };
  breakdown?: {
    etf_inflow_24h?: number;
    etf_outflow_24h?: number;
    institutional_exposure?: number;
    long_pressure?: number;
    retail_exposure?: number;
    short_pressure?: number;
    usdc_supply_change?: number;
    usdt_supply_change?: number;
    whale_buying?: number;
    whale_selling?: number;
    whale_netflow_to_ex_usd?: number;
    liquidations_24h_usd?: number;
    [ticker: string]: number | undefined;
  };
}

interface FlowModule {
  metrics?: FlowMetrics;
  timeseries?: FlowTimeseriesPoint[];
  meta?: { last_update?: string; source?: string[]; data_quality?: string };
}

interface SnapshotResponse {
  modules?: Record<string, FlowModule>;
}

function formatMillion(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1000) return `${(v / 1000).toFixed(2)}B`;
  return `${v.toFixed(0)}M`;
}

function formatPct(v: number, digits = 2): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

export function FlowPanel() {
  const [flow, setFlow] = useState<FlowModule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fundamentalApi
      .getSnapshot()
      .then(data => {
        const snap = data as SnapshotResponse | null;
        const mod = snap?.modules?.flow ?? null;
        setFlow(mod);
      })
      .catch(e => setError(e?.message ?? '获取资金流向数据失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-10 rounded-lg bg-slate-800/50 animate-pulse" />
        <div className="h-72 rounded-xl bg-slate-800/50 animate-pulse" />
        <div className="h-64 rounded-xl bg-slate-800/50 animate-pulse" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">
        资金流向数据加载失败：{error}
      </div>
    );
  }

  const core = { ...(flow?.metrics?.core ?? {}) };
  const breakdown = { ...(flow?.metrics?.breakdown ?? {}) };
  const rawTs = flow?.timeseries ?? [];

  // 将 fund_flow_score 归一化序列映射到以最新 ETF 净流入为锚点的美元（百万）净流入
  const latestValue = rawTs.length > 0 ? Number(rawTs[rawTs.length - 1]?.value) || 0 : 0;
  const etfNetFlow = Number(core.etf_total_flow) || 0;
  const scaleFactor = latestValue !== 0 ? etfNetFlow / latestValue : 0;

  const etf24hNet = (Number(breakdown.etf_inflow_24h) || 0) - (Number(breakdown.etf_outflow_24h) || 0);

  const timeseries = rawTs.map(p => ({
    ts: p.timestamp ?? new Date().toISOString(),
    net_flow: Number(p.value) * scaleFactor,
    etf_flow: etf24hNet,
  }));

  // 巨鲸买卖：基于巨鲸净流向交易所（负值=提币=买入积累，正值=充值=卖出）
  const whaleNetflowUsd = Number(breakdown.whale_netflow_to_ex_usd) || 0;
  const baseWhale = Math.max(50, Math.abs(whaleNetflowUsd) / 1e8);
  let whaleBuying = baseWhale;
  let whaleSelling = baseWhale;
  if (whaleNetflowUsd < 0) {
    whaleBuying = baseWhale;
    whaleSelling = Math.max(5, baseWhale - Math.abs(whaleNetflowUsd) / 1e8);
  } else if (whaleNetflowUsd > 0) {
    whaleSelling = baseWhale;
    whaleBuying = Math.max(5, baseWhale - whaleNetflowUsd / 1e8);
  }

  const whaleTransactions = [
    {
      wallet_label: '鲸鱼买入',
      amount: whaleBuying,
      direction: 'in' as const,
      exchange: '综合',
      timestamp: flow?.meta?.last_update,
    },
    {
      wallet_label: '鲸鱼卖出',
      amount: whaleSelling,
      direction: 'out' as const,
      exchange: '综合',
      timestamp: flow?.meta?.last_update,
    },
  ];

  const direction = String(core.smart_money_direction || core.flow_regime || '');
  const directionVariant = direction.includes('流入') || direction.includes('显著流入') || direction.includes('inflow') || direction.includes('accumulation')
    ? 'success' as const
    : direction.includes('流出') || direction.includes('显著流出') || direction.includes('outflow') || direction.includes('distribution')
      ? 'danger' as const
      : 'default' as const;

  const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
  const signalLabel = { bullish: '利多', bearish: '利空', neutral: '中性' };
  type SignalKey = keyof typeof signalVariant;

  const summaryItems: { label: string; value: string; signal: SignalKey }[] = [
    { label: 'ETF 净流入', value: `${formatMillion(etfNetFlow)} USD`, signal: etfNetFlow >= 0 ? 'bullish' : 'bearish' },
    { label: '资金流评分', value: `${(Number(core.fund_flow_score) || 0).toFixed(1)}`, signal: (Number(core.fund_flow_score) || 0) >= 0 ? 'bullish' : 'bearish' },
    { label: 'USDT 占比', value: `${(Number(core.stablecoin_dominance_usdt) || 0).toFixed(1)}%`, signal: 'neutral' },
    { label: 'USDC 占比', value: `${(Number(core.stablecoin_dominance_usdc) || 0).toFixed(1)}%`, signal: 'neutral' },
    { label: '资金费率', value: core.funding_rate != null ? `${(Number(core.funding_rate) * 100).toFixed(4)}%` : '--', signal: Number(core.funding_rate) <= 0.01 && Number(core.funding_rate) >= -0.01 ? 'neutral' : Number(core.funding_rate) > 0 ? 'bearish' : 'bullish' },
    { label: '多空比', value: core.long_short_ratio != null ? Number(core.long_short_ratio).toFixed(2) : '--', signal: 'neutral' },
    { label: '鲸鱼活跃度', value: `${(Number(core.whale_activity) || 0).toFixed(1)}`, signal: 'neutral' },
    { label: '清算压力', value: `${(Number(core.liquidation_pressure) || 0).toFixed(1)}`, signal: Number(core.liquidation_pressure) > 50 ? 'bearish' : 'neutral' },
  ];

  return (
    <div className="space-y-4">
      <V3Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-200">资金流向核心指标</h3>
            <p className="text-[10px] text-slate-500 mt-0.5">
              聪明钱方向：
              <span className="ml-1">
                <V3Badge variant={directionVariant} label={direction || '未知'} />
              </span>
              {flow?.meta?.last_update && (
                <span className="ml-3">更新于 {flow.meta.last_update.slice(0, 16).replace('T', ' ')}</span>
              )}
            </p>
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {summaryItems.map(m => (
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

      <NetFlowTrendChart timeseries={timeseries} />
      <WhaleTracker transactions={whaleTransactions} />
    </div>
  );
}

export default FlowPanel;
