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
    etf_net_flow?: number;
    fund_flow_score?: number;
    funding_rate?: number;
    liquidation_pressure?: number;
    long_short_ratio?: number;
    smart_money_direction?: string;
    stablecoin_supply_change?: number;
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
  const [panewslab, setPanewslab] = useState<{ exchange?: any } | null>(null);
  const [dc, setDc] = useState<{ flow?: any; stablecoin?: any } | null>(null);

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

  // 用 CryptoQuant (panewslab) 真实巨鲸流向覆盖 mock 鲸鱼数据
  useEffect(() => {
    fetch('/api/onchain/panewslab', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => { if (d?.ok) setPanewslab({ exchange: d.exchange }); })
      .catch(() => {});
  }, []);

  // 用数据中心真实数据(coinglass/etf_flow/stablecoin)覆盖 mock
  useEffect(() => {
    fetch('/api/onchain/datacenter', { cache: 'no-store' })
      .then(r => r.json())
      .then(d => { if (d?.ok) setDc({ flow: d.flow, stablecoin: d.stablecoin }); })
      .catch(() => {});
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

  // 用数据中心真实数据覆盖 mock
  if (dc?.flow) {
    const f = dc.flow;
    if (f.funding_rate != null) core.funding_rate = f.funding_rate;
    if (f.long_short_ratio != null) core.long_short_ratio = f.long_short_ratio;
    if (f.etf_net_flow_usd != null) core.etf_net_flow = Number(f.etf_net_flow_usd) / 1e6; // USD -> M USD
    if (f.etf_inflow_24h != null) breakdown.etf_inflow_24h = Number(f.etf_inflow_24h) / 1e6;
    if (f.etf_outflow_24h != null) breakdown.etf_outflow_24h = Number(f.etf_outflow_24h) / 1e6;
    if (f.liquidations_24h_usd != null) {
      // 清算压力：清算额归一化到 0-100
      const liqBn = Number(f.liquidations_24h_usd) / 1e9;
      core.liquidation_pressure = Math.min(100, liqBn * 20);
    }
  }
  if (dc?.stablecoin) {
    const s = dc.stablecoin;
    if (s.usdt_change_7d_pct != null) {
      const usdtChg = Number(s.usdt_change_7d_pct);
      const usdcChg = s.usdc_change_7d_pct != null ? Number(s.usdc_change_7d_pct) : usdtChg;
      core.stablecoin_supply_change = Number(((usdtChg + usdcChg) / 2).toFixed(3));
      breakdown.usdt_supply_change = Number(usdtChg.toFixed(3));
      breakdown.usdc_supply_change = Number(usdcChg.toFixed(3));
    }
    // 机构/散户敞口：基于稳定币变化方向推导
    if (core.stablecoin_supply_change != null) {
      const sc = core.stablecoin_supply_change;
      breakdown.institutional_exposure = Math.max(0, Math.min(100, 50 + sc * 15));
      breakdown.retail_exposure = Math.max(0, Math.min(100, 50 - sc * 10));
    }
  }

  // 将 fund_flow_score 归一化序列映射到以最新 ETF 净流入为锚点的美元（百万）净流入
  const latestValue = rawTs.length > 0 ? Number(rawTs[rawTs.length - 1]?.value) || 0 : 0;
  const etfNetFlow = Number(core.etf_net_flow) || 0;
  const scaleFactor = latestValue !== 0 ? etfNetFlow / latestValue : 0;

  const etf24hNet = (Number(breakdown.etf_inflow_24h) || 0) - (Number(breakdown.etf_outflow_24h) || 0);

  const timeseries = rawTs.map(p => ({
    ts: p.timestamp ?? new Date().toISOString(),
    net_flow: Number(p.value) * scaleFactor,
    etf_flow: etf24hNet,
  }));

  const whaleBuyingRaw = Number(breakdown.whale_buying) || 0;
  const whaleSellingRaw = Number(breakdown.whale_selling) || 0;

  // 用 CryptoQuant 真实巨鲸流向覆盖 mock
  let whaleBuying = whaleBuyingRaw;
  let whaleSelling = whaleSellingRaw;
  if (panewslab?.exchange?.whale_netflow_to_ex_usd !== undefined) {
    const netUsd = panewslab.exchange.whale_netflow_to_ex_usd;
    // 净流向交易所为负 = 巨鲸从交易所提币(积累/买入)，为正 = 巨鲸充值交易所(抛售)
    const base = Math.max(whaleBuyingRaw, whaleSellingRaw, 50);
    if (netUsd < 0) {
      whaleBuying = base;
      whaleSelling = Math.max(5, base - Math.abs(netUsd) / 1e8);
    } else {
      whaleSelling = base;
      whaleBuying = Math.max(5, base - netUsd / 1e8);
    }
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

  const direction = String(core.smart_money_direction || '');
  const directionVariant = direction.includes('流入') || direction.includes('显著流入')
    ? 'success' as const
    : direction.includes('流出')
      ? 'danger' as const
      : 'default' as const;

  const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
  const signalLabel = { bullish: '利多', bearish: '利空', neutral: '中性' };
  type SignalKey = keyof typeof signalVariant;

  const summaryItems: { label: string; value: string; signal: SignalKey }[] = [
    { label: 'ETF 净流入', value: `${formatMillion(etfNetFlow)} USD`, signal: etfNetFlow >= 0 ? 'bullish' : 'bearish' },
    { label: '24h ETF 流入', value: `${formatMillion(Number(breakdown.etf_inflow_24h) || 0)}`, signal: 'bullish' },
    { label: '24h ETF 流出', value: `${formatMillion(Number(breakdown.etf_outflow_24h) || 0)}`, signal: 'bearish' },
    { label: '资金费率', value: formatPct(Number(core.funding_rate) || 0, 4), signal: Number(core.funding_rate) >= 0 ? 'bullish' : 'bearish' },
    { label: '多空比', value: (Number(core.long_short_ratio) || 0).toFixed(2), signal: Number(core.long_short_ratio) >= 1 ? 'bullish' : 'bearish' },
    { label: '鲸鱼活跃度', value: `${(Number(core.whale_activity) || 0).toFixed(1)}`, signal: 'neutral' },
    { label: '稳定币供给变化', value: formatPct(Number(core.stablecoin_supply_change) || 0), signal: Number(core.stablecoin_supply_change) >= 0 ? 'bullish' : 'bearish' },
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
