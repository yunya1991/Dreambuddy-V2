'use client';

import { useQuery } from '@tanstack/react-query';
import { V3Card, V3Badge } from '@/components';
import { fundamentalApi } from '@/lib/v3/api';
import { queryKey, queryStaleTime } from '@/lib/query-keys';

interface YahooQuote {
  symbol: string;
  price: number;
  change24h: number;
  currency: string;
}

interface IntermarketModule {
  metrics?: {
    core?: Record<string, number | string>;
    breakdown?: Record<string, number>;
  };
  meta?: { last_update?: string; source?: string[] };
}

const ASSET_MAP: { key: string; label: string; symbol: string; norm: string; isRisk?: boolean }[] = [
  { key: 'gold_price', label: '黄金', symbol: 'GC=F', norm: 'GC_F' },
  { key: 'spx_price', label: '标普500', symbol: '^GSPC', norm: '__GSPC', isRisk: true },
  { key: 'ndx', label: '纳斯达克', symbol: '^IXIC', norm: '__IXIC', isRisk: true },
  { key: 'vix', label: 'VIX恐慌', symbol: '^VIX', norm: '__VIX' },
  { key: 'wti', label: 'WTI原油', symbol: 'CL=F', norm: 'CL_F', isRisk: true },
  { key: 'dxy', label: '美元指数', symbol: 'DX-Y.NYB', norm: 'DX-Y.NYB' },
];

function fmt(n: number, digits = 2): string {
  if (!isFinite(n)) return '--';
  if (n >= 1000) return n.toLocaleString('en-US', { maximumFractionDigits: digits });
  return n.toFixed(digits);
}

async function fetchYahooQuotes(symbols: string): Promise<Record<string, YahooQuote>> {
  const r = await fetch(`/api/market/yahoo?symbols=${symbols}`, { cache: 'no-store' });
  const d = await r.json();
  if (!d?.ok || !Array.isArray(d.data)) return {};
  const map: Record<string, YahooQuote> = {};
  d.data.forEach((q: YahooQuote & { ok?: boolean }) => {
    if (q.ok) map[q.symbol] = q;
  });
  return map;
}

export function IntermarketPanel() {
  const snapshotQuery = useQuery({
    queryKey: queryKey('fundamental', 'snapshot'),
    queryFn: () => fundamentalApi.getSnapshot(),
    staleTime: queryStaleTime('fundamental'),
  });

  const symbols = ASSET_MAP.map(a => a.norm).join(',');
  const quotesQuery = useQuery({
    queryKey: queryKey('market', 'yahoo', { symbols }),
    queryFn: () => fetchYahooQuotes(symbols),
    staleTime: queryStaleTime('market'),
    retry: false, // FAIL-OPEN：失败保留旧数据
  });

  const mod = (snapshotQuery.data as { modules?: Record<string, IntermarketModule> } | null)?.modules?.intermarket ?? null;
  const quotes = quotesQuery.data ?? {};
  const loading = snapshotQuery.isLoading;
  const error = snapshotQuery.isError
    ? ((snapshotQuery.error as Error | null)?.message ?? '获取跨市场数据失败')
    : null;

  if (loading) return <div className="h-48 rounded-xl bg-slate-800/50 animate-pulse" />;
  if (error) return <div className="rounded-lg bg-red-950/30 border border-red-800/30 p-4 text-xs text-red-300">跨市场数据加载失败：{error}</div>;

  const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };

  return (
    <div className="space-y-4">
      <V3Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-200">跨市场资产价格（实时）</h3>
          <span className="text-[10px] text-slate-500">数据来源: Yahoo Finance</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {ASSET_MAP.map(a => {
            const q = quotes[a.symbol];
            const snapshotVal = (mod?.metrics?.core?.[a.key] as number) ?? null;
            const price = q?.price ?? snapshotVal;
            const change = q?.change24h;
            // 信号：风险资产上涨=利多，避险资产/美元/VIX上涨=利空
            let signal: 'bullish' | 'bearish' | 'neutral' = 'neutral';
            if (change !== undefined) {
              const positive = change >= 0;
              if (a.isRisk) signal = positive ? 'bullish' : 'bearish';
              else signal = positive ? 'bearish' : 'bullish';
            }
            return (
              <V3Card key={a.key} padding="sm" hover>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-slate-500">{a.label}</span>
                  {q ? (
                    <V3Badge variant={signalVariant[signal]} label={signal === 'bullish' ? '利多' : signal === 'bearish' ? '利空' : '中性'} />
                  ) : snapshotVal ? (
                    <V3Badge variant="default" label="快照" />
                  ) : null}
                </div>
                <p className="text-base font-semibold text-slate-200">${fmt(price ?? 0, a.key === 'vix' || a.key === 'dxy' ? 2 : 2)}</p>
                {change !== undefined && (
                  <p className={`text-[10px] ${change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {change >= 0 ? '+' : ''}{change.toFixed(2)}%
                  </p>
                )}
              </V3Card>
            );
          })}
        </div>
      </V3Card>

      <V3Card padding="md">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">BTC 跨市场相关性与宏观利率（快照）</h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">BTC-美元相关性</p>
            <p className="text-base font-semibold text-slate-200">{fmt(Number(mod?.metrics?.core?.dxy_correlation ?? 0), 3)}</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">BTC 价格</p>
            <p className="text-base font-semibold text-slate-200">${fmt(Number(mod?.metrics?.core?.btc_price ?? 0), 0)}</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">美债10Y收益率</p>
            <p className="text-base font-semibold text-slate-200">{fmt(Number(mod?.metrics?.core?.us10y_yield ?? 0), 3)}%</p>
          </V3Card>
          <V3Card padding="sm">
            <p className="text-[10px] text-slate-500 mb-1">风险周期</p>
            <p className="text-base font-semibold text-slate-200">{String(mod?.metrics?.core?.risk_regime ?? '--')}</p>
          </V3Card>
        </div>
        <p className="text-[10px] text-slate-600 mt-2">注：相关性指标为快照数据，资产价格为实时数据。</p>
      </V3Card>
    </div>
  );
}

export default IntermarketPanel;
