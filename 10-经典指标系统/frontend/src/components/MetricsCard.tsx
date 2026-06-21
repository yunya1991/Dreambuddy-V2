
import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchMetrics, fetchTrackerStats } from '../lib/api';
import { Activity, ShoppingCart, Cpu, Shield } from 'lucide-react';
import { Card, CardContent } from './ui/card';

export const MetricsCard: React.FC = () => {
  const {
    data: metrics,
    isLoading: metricsLoading,
    error: metricsError,
    dataUpdatedAt: metricsUpdatedAt,
  } = useQuery({
    queryKey: ['metrics'],
    queryFn: fetchMetrics,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const {
    data: tracker,
    isLoading: trackerLoading,
    error: trackerError,
    dataUpdatedAt: trackerUpdatedAt,
  } = useQuery({
    queryKey: ['tracker', 'ui'],
    queryFn: () => fetchTrackerStats({ sync: false, view: 'ui' }),
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const today = new Date().toISOString().slice(0, 10);
  const daily = tracker?.daily_pnl?.[today];
  const weekKeys = Object.keys(tracker?.weekly_pnl ?? {}).sort();
  const weekKey = weekKeys.length ? weekKeys[weekKeys.length - 1] : '';
  const weekly = weekKey ? tracker?.weekly_pnl?.[weekKey] : undefined;
  const openPositions = tracker ? Object.keys(tracker.open_positions ?? {}).length : undefined;

  const showCachedBanner = (!metricsLoading && metricsError && metrics != null) || (!trackerLoading && trackerError && tracker != null);
  const lastOkMs = Math.max(Number(metricsUpdatedAt ?? 0), Number(trackerUpdatedAt ?? 0));
  const lastOkText = lastOkMs ? new Date(lastOkMs).toLocaleTimeString() : '';

  const signalsText = metricsLoading ? '…' : metrics != null ? String(metrics.signals ?? '-') : metricsError ? 'ERR' : '-';
  const ordersText = metricsLoading
    ? '…'
    : metrics != null
      ? String(metrics.orders_execute ?? metrics.orders_live ?? metrics.orders ?? '-')
      : metricsError
        ? 'ERR'
        : '-';
  const ordersMetaText = metricsLoading
    ? ''
    : metrics != null
      ? `total ${Number(metrics.orders_total ?? metrics.orders ?? 0)} · observed ${Number(metrics.orders_observed ?? 0)} · simulated ${Number(metrics.orders_simulated ?? metrics.orders_shadow ?? 0)}`
      : '';
  const modelText = metricsLoading
    ? '…'
    : metrics != null
      ? String(metrics.active_model || 'None')
      : metricsError
        ? 'ERR'
        : '-';
  const riskText = trackerLoading
    ? '…'
    : tracker != null
      ? `Open ${openPositions ?? 0} · D ${Number((daily ?? 0) * 100).toFixed(2)}% · W ${Number((weekly ?? 0) * 100).toFixed(2)}%`
      : trackerError
        ? 'ERR'
        : '-';

  return (
    <div className="mb-6">
      {showCachedBanner ? (
        <div className="mb-3 text-xs text-rose-700">
          Backend unreachable · showing cached data{lastOkText ? ` (last ok: ${lastOkText})` : ''}
        </div>
      ) : null}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
      <Card>
        <CardContent className="flex items-center p-6 space-x-4">
          <div className="p-3 bg-blue-100 text-blue-600 rounded-full">
            <Activity size={24} />
          </div>
          <div>
            <div className="text-sm font-medium text-muted-foreground">Signals</div>
            <div className="text-2xl font-bold text-slate-900">{signalsText}</div>
          </div>
        </CardContent>
      </Card>
      
      <Card>
        <CardContent className="flex items-center p-6 space-x-4">
          <div className="p-3 bg-purple-100 text-purple-600 rounded-full">
            <ShoppingCart size={24} />
          </div>
          <div>
            <div className="text-sm font-medium text-muted-foreground">Orders (live)</div>
            <div className="text-2xl font-bold text-slate-900">{ordersText}</div>
            {ordersMetaText ? <div className="text-xs text-slate-500">{ordersMetaText}</div> : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex items-center p-6 space-x-4">
          <div className="p-3 bg-green-100 text-green-600 rounded-full">
            <Cpu size={24} />
          </div>
          <div>
            <div className="text-sm font-medium text-muted-foreground">Active Model</div>
            <div className="text-xl font-bold text-slate-900 truncate max-w-[150px]" title={metrics?.active_model}>
              {modelText}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex items-center p-6 space-x-4">
          <div className="p-3 bg-amber-100 text-amber-700 rounded-full">
            <Shield size={24} />
          </div>
          <div>
            <div className="text-sm font-medium text-muted-foreground">Risk</div>
            <div className="text-sm font-semibold text-slate-900">{riskText}</div>
          </div>
        </CardContent>
      </Card>
      </div>
    </div>
  );
};
