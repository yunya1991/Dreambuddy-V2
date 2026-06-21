import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AxiosError } from 'axios';
import { fetchAutomationStrategiesState, fetchConfig, fetchExitLatestFeatures, fetchExitMetrics, fetchExitMlMonitor, fetchMetrics, fetchRecentOrdersWithParams, fetchTrackerStats, fetchTrackerGateHistory, setStrategyFeederConfig, updateConfig } from '../lib/api';
import type { AutomationStrategiesConfig, AutomationStrategiesConfigResponse, ConfigPatch, ExitLatestFeaturesItem, ExitLatestFeaturesResponse, ExitMetricsResponse, ExitMlMonitorModel, ExitMlMonitorResponse, Metrics, TrackerStats, GateHistoryItem } from '../lib/api';
import { filterOrdersForUi, isOrderSimulatedLike } from '../lib/ordersUi';
import { useOrdersUiPrefs } from '../lib/ordersUiPrefs';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';

function _toNum(v: unknown, d = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

function _msToCompact(ms: number): string {
  const x = Math.max(0, Math.floor(ms));
  const sec = Math.floor(x / 1000);
  const m = Math.floor(sec / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d${h % 24}h`;
  if (h > 0) return `${h}h${m % 60}m`;
  if (m > 0) return `${m}m`;
  return `${sec}s`;
}

function _fmtTs(ts?: number): string {
  const x = typeof ts === 'number' ? ts : Number(ts ?? NaN);
  if (!Number.isFinite(x) || x <= 0) return '-';
  return new Date(x).toLocaleString();
}

function _fmtUsd(x: number, digits = 2): string {
  return `${x.toFixed(digits)}u`;
}

function _fmtPct(x: number, digits = 2): string {
  return `${(x * 100).toFixed(digits)}%`;
}

function _quantile(xs: number[], q: number): number | null {
  if (!xs.length) return null;
  const ys = [...xs].sort((a, b) => a - b);
  const qq = Math.max(0, Math.min(1, q));
  const idx = (ys.length - 1) * qq;
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return ys[lo];
  const w = idx - lo;
  return ys[lo] * (1 - w) + ys[hi] * w;
}

function _maxDrawdown(rets: { ts: number; r: number }[]): number {
  let peak = 0;
  let eq = 0;
  let maxdd = 0;
  const xs = [...rets].sort((a, b) => a.ts - b.ts);
  for (const it of xs) {
    eq += it.r;
    peak = Math.max(peak, eq);
    maxdd = Math.max(maxdd, peak - eq);
  }
  return maxdd;
}

function _maxConsecutive(xs: number[], pred: (x: number) => boolean): number {
  let cur = 0;
  let best = 0;
  for (const x of xs) {
    if (pred(x)) {
      cur += 1;
      best = Math.max(best, cur);
    } else {
      cur = 0;
    }
  }
  return best;
}

function _cvar(xs: number[], q: number): number | null {
  if (!xs.length) return null;
  const qq = Math.max(0, Math.min(1, q));
  const ys = [...xs].sort((a, b) => a - b);
  const cutIdx = Math.max(0, Math.min(ys.length, Math.ceil(ys.length * qq)));
  const tail = ys.slice(0, cutIdx);
  if (!tail.length) return null;
  return tail.reduce((s, x) => s + x, 0) / tail.length;
}

const ExitMlMonitorCard: React.FC<{
  data?: ExitMlMonitorResponse | null;
  loading: boolean;
  latestFeatures?: ExitLatestFeaturesItem[];
}> = ({ data, loading, latestFeatures }) => {
  const models = (data?.models ?? {}) as Record<string, ExitMlMonitorModel>;
  const fmtTs = (ts?: number) => {
    if (!ts || !Number.isFinite(ts) || ts <= 0) return '-';
    return new Date(ts).toLocaleString();
  };

  const metricNum = (m: ExitMlMonitorModel | undefined, key: string, digits: number = 4) => {
    const v = m?.metrics?.[key];
    const x = typeof v === 'number' ? v : Number(v ?? NaN);
    if (!Number.isFinite(x)) return '-';
    return x.toFixed(digits);
  };

  const builtField = (m: ExitMlMonitorModel | undefined, key: string) => {
    const built = (m?.built ?? {}) as Record<string, unknown>;
    const v = built[key];
    if (v == null) return '-';
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '-';
    return String(v);
  };

  const renderModelRow = (task: string, m: ExitMlMonitorModel | undefined) => {
    const rec = (m ?? {}) as unknown as Record<string, unknown>;
    const loaded = Boolean(m?.loaded);
    const fileExists = Boolean(rec['file_exists']);
    const err = String(rec['error'] ?? '');
    const wfA = metricNum(m, 'wf_auc', 3);
    const wfP = metricNum(m, 'wf_pr_auc', 3);
    const wfE = metricNum(m, 'wf_ece', 3);
    const wfB = metricNum(m, 'wf_brier', 4);
    const wfStr = wfA === '-' && wfP === '-' && wfE === '-' && wfB === '-' ? '-' : `${wfA}/${wfP}/${wfE}/${wfB}`;
    return (
      <tr key={task} className="border-t">
        <td className="px-2 py-2 font-medium text-slate-900">{task}</td>
        <td className="px-2 py-2 text-slate-700">{loaded ? 'true' : 'false'}</td>
        <td className="px-2 py-2 text-slate-700">{fileExists ? 'true' : 'false'}</td>
        <td className="px-2 py-2 text-slate-700 whitespace-nowrap">{fmtTs(m?.ts)}</td>
        <td className="px-2 py-2 text-slate-700">{String(m?.family ?? '-')}</td>
        <td className="px-2 py-2 text-slate-700 truncate max-w-[220px]" title={String(m?.filename ?? '')}>
          {String(m?.filename ?? '-')}
        </td>
        <td className="px-2 py-2 text-slate-700">{metricNum(m, 'auc', 3)}</td>
        <td className="px-2 py-2 text-slate-700">{metricNum(m, 'pr_auc', 3)}</td>
        <td className="px-2 py-2 text-slate-700">{metricNum(m, 'ece', 3)}</td>
        <td className="px-2 py-2 text-slate-700">{metricNum(m, 'brier', 4)}</td>
        <td className="px-2 py-2 text-slate-700 whitespace-nowrap">{wfStr}</td>
        <td className="px-2 py-2 text-slate-700">{builtField(m, 'n')}</td>
        <td className="px-2 py-2 text-slate-700 truncate max-w-[260px]" title={err}>
          {err || '-'}
        </td>
      </tr>
    );
  };

  const fmtCompact = (v: unknown, digits: number = 4) => {
    const x = typeof v === 'number' ? v : Number(v ?? NaN);
    if (!Number.isFinite(x)) return '-';
    return x.toFixed(digits);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Exit ML Monitor</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && (
          <div className="border border-slate-200 bg-slate-50 text-slate-900 rounded px-4 py-3 text-sm">Loading exit monitor...</div>
        )}
        {!loading && (!data || !data.ok) && (
          <div className="border border-rose-200 bg-rose-50 text-rose-900 rounded px-4 py-3 text-sm">Exit monitor API unavailable</div>
        )}
        {!loading && data && data.ok && (
          <div className="space-y-4">
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-600">
                    <th className="px-2 py-2">task</th>
                    <th className="px-2 py-2">loaded</th>
                    <th className="px-2 py-2">file</th>
                    <th className="px-2 py-2">ts</th>
                    <th className="px-2 py-2">family</th>
                    <th className="px-2 py-2">filename</th>
                    <th className="px-2 py-2">AUC</th>
                    <th className="px-2 py-2">PR</th>
                    <th className="px-2 py-2">ECE</th>
                    <th className="px-2 py-2">Brier</th>
                    <th className="px-2 py-2">WF(A/P/E/B)</th>
                    <th className="px-2 py-2">built_n</th>
                    <th className="px-2 py-2">error</th>
                  </tr>
                </thead>
                <tbody>
                  {renderModelRow('tail', models['tail'])}
                  {renderModelRow('move', models['move'])}
                  {renderModelRow('gate', models['gate'])}
                  {renderModelRow('feedback', models['feedback'])}
                </tbody>
              </table>
            </div>

            <div className="space-y-2">
              <div className="text-sm text-slate-700 font-semibold">Open positions (latest features)</div>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-600">
                      <th className="px-2 py-2">Time</th>
                      <th className="px-2 py-2">Pair</th>
                      <th className="px-2 py-2">Side</th>
                      <th className="px-2 py-2">Owner</th>
                      <th className="px-2 py-2">hold_risk</th>
                      <th className="px-2 py-2">hold_value</th>
                      <th className="px-2 py-2">model_conf</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(Array.isArray(latestFeatures) ? latestFeatures : []).slice(0, 12).map((it, i) => (
                      <tr key={i} className="border-t">
                        <td className="px-2 py-2 text-slate-700 whitespace-nowrap">{fmtTs(Number(it.ts))}</td>
                        <td className="px-2 py-2 text-slate-700">{String(it.pair)}</td>
                        <td className="px-2 py-2 text-slate-700">{String(it.side ?? '-')}</td>
                        <td className="px-2 py-2 text-slate-700">{String(it.exit_owner ?? '-')}</td>
                        <td className="px-2 py-2 text-slate-700">{fmtCompact(it.hold_risk, 4)}</td>
                        <td className="px-2 py-2 text-slate-700">{fmtCompact(it.hold_value, 4)}</td>
                        <td className="px-2 py-2 text-slate-700">{fmtCompact((it.features as Record<string, unknown>)?.['model_conf'], 3)}</td>
                      </tr>
                    ))}
                    {(!Array.isArray(latestFeatures) || latestFeatures.length === 0) && (
                      <tr className="border-t">
                        <td className="px-2 py-3 text-slate-500" colSpan={7}>
                          No open positions / no latest features
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export const ExitSystemPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [manualSyncMsg, setManualSyncMsg] = useState<string>('');
  const [showShadowExitEvents, setShowShadowExitEvents] = useState<boolean>(false);
  const { showShadow: carryOrdersShowShadow, setShowShadow: setCarryOrdersShowShadow, showSimulated: carryOrdersShowSimulated, setShowSimulated: setCarryOrdersShowSimulated } = useOrdersUiPrefs({ scope: 'exit_carry_orders' });
  const { showShadow: quantOrdersShowShadow, setShowShadow: setQuantOrdersShowShadow, showSimulated: quantOrdersShowSimulated, setShowSimulated: setQuantOrdersShowSimulated } = useOrdersUiPrefs({ scope: 'exit_quant_orders' });
  const [carryOrdersWindow, setCarryOrdersWindow] = useState<'24h' | '7d' | 'all'>('24h');

  type ExitSwitches = {
    exitExecEnabled: boolean;
    strategyExitEnabled: boolean;
    exitFeederEnabled: boolean;
    quantBtcEthExitEnabled: boolean;
    quantBtcAltExitEnabled: boolean;
    carrySoftNoExitReduceEnabled: boolean;
  };

  type ExitPreset = 'trend' | 'chop';

  const [draftSwitches, setDraftSwitches] = useState<ExitSwitches | null>(null);
  const [saveMsg, setSaveMsg] = useState<string>('');

  const getErrorMessage = (err: unknown) => {
    const axiosErr = err as AxiosError<{ error?: string }>;
    const msg = axiosErr.response?.data?.error;
    if (msg) return msg;
    if (axiosErr.message) return axiosErr.message;
    return String(err);
  };

  const buildExitPresetPatch = (preset: ExitPreset): ConfigPatch => {
    if (preset === 'trend') {
      return {
        exit_tb_enabled: true,
        exit_tstp_enabled: true,
        exit_apply_leverage_to_thresholds: true,
        exit_tb_sl_atr_mult: 5.0,
        exit_tb_tp_atr_mult: 9.0,
        exit_tb_sl_min_pct: 0.03,
        exit_tb_tp_min_pct: 0.03,
        exit_tstp_tp_min_pct: 0.03,
        exit_tb_time_barrier_sec: 86400,
        exit_tb_take_reduce_frac: 0.5,
        exit_tb_time_reduce_frac: 0.4,
        exit_l2_take_profit_pct: 0.03,
        exit_l2_trailing_retrace_pct: 0.35,
        exit_l2_reduce_frac: 0.45,
        exit_l1_hold_risk_reduce_threshold: 0.72,
        exit_l1_hold_risk_close_threshold: 0.88,
        exit_l1_reduce_min_profit_pct: 0.01,
        exit_l1_reduce_base_frac: 0.3,
        exit_l1_reduce_max_frac: 0.6,
        exit_risk_gate_enabled: true,
        exit_risk_gate_cooldown_min: 90,
        exit_risk_gate_confirm_n: 2,
        exit_l0_max_hold_sec: 86400,
        exit_feeder_max_open_age_sec: 86400,
      } as ConfigPatch;
    }
    return {
      exit_tb_enabled: true,
      exit_tstp_enabled: true,
      exit_apply_leverage_to_thresholds: true,
      exit_tb_sl_atr_mult: 2.5,
      exit_tb_tp_atr_mult: 4.0,
      exit_tb_sl_min_pct: 0.02,
      exit_tb_tp_min_pct: 0.015,
      exit_tstp_tp_min_pct: 0.015,
      exit_tb_time_barrier_sec: 21600,
      exit_tb_take_reduce_frac: 0.65,
      exit_tb_time_reduce_frac: 0.6,
      exit_l2_take_profit_pct: 0.015,
      exit_l2_trailing_retrace_pct: 0.25,
      exit_l2_reduce_frac: 0.6,
      exit_l1_hold_risk_reduce_threshold: 0.62,
      exit_l1_hold_risk_close_threshold: 0.78,
      exit_l1_reduce_min_profit_pct: 0.006,
      exit_l1_reduce_base_frac: 0.45,
      exit_l1_reduce_max_frac: 0.75,
      exit_risk_gate_enabled: true,
      exit_risk_gate_cooldown_min: 60,
      exit_risk_gate_confirm_n: 1,
      exit_l0_max_hold_sec: 43200,
      exit_feeder_max_open_age_sec: 43200,
    } as ConfigPatch;
  };
  const { data: cfg } = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  });

  const { data: automation } = useQuery({
    queryKey: ['automation', 'state'],
    queryFn: fetchAutomationStrategiesState,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  });

  const { data: metrics } = useQuery({
    queryKey: ['metrics'],
    queryFn: fetchMetrics,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  });

  const { data: exitMetrics } = useQuery({
    queryKey: ['exit', 'metrics'],
    queryFn: () => fetchExitMetrics({ limit: 5000 }),
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  });
  const nowMs = Number((metrics as Metrics | undefined)?.ts ?? 0);

  const derivedSwitches = useMemo<ExitSwitches>(() => {
    const c = (cfg ?? {}) as Record<string, unknown>;
    const a = ((automation as AutomationStrategiesConfigResponse | undefined)?.automation ?? {}) as Record<string, unknown>;
    const exec = c.exit_shadow_mode !== true;
    return {
      exitExecEnabled: Boolean(exec),
      strategyExitEnabled: Boolean(c.strategy_exit_enabled === true),
      exitFeederEnabled: Boolean(a.use_exit_feeder === true),
      quantBtcEthExitEnabled: Boolean((c.quant_pairs_btceth_exit_pnl_enabled ?? true) === true),
      quantBtcAltExitEnabled: Boolean((c.quant_pairs_btcalt_exit_pnl_enabled ?? true) === true),
      carrySoftNoExitReduceEnabled: Boolean(c.carry_trade_soft_no_exit_reduce_enabled === true),
    };
  }, [cfg, automation]);

  const switches = (draftSwitches ?? derivedSwitches);
  const setSwitchPatch = (p: Partial<ExitSwitches>) => {
    setDraftSwitches((prev) => ({ ...(prev ?? derivedSwitches), ...p }));
  };

  const saveConfigMutation = useMutation({
    mutationFn: updateConfig,
    onSuccess: (res) => {
      setSaveMsg(res?.ok ? 'config saved' : (res as unknown as { error?: string })?.error ?? 'config save failed');
      setDraftSwitches(null);
      queryClient.invalidateQueries({ queryKey: ['config'] });
    },
    onError: (e) => {
      setSaveMsg(getErrorMessage(e));
    },
  });

  const saveAutomationMutation = useMutation({
    mutationFn: setStrategyFeederConfig,
    onSuccess: (res) => {
      setSaveMsg(res?.ok ? 'automation saved' : 'automation save failed');
      setDraftSwitches(null);
      queryClient.invalidateQueries({ queryKey: ['automation'] });
      queryClient.invalidateQueries({ queryKey: ['automation', 'state'] });
    },
    onError: (e) => {
      setSaveMsg(getErrorMessage(e));
    },
  });

  const { data: tracker } = useQuery({
    queryKey: ['tracker', 'sync', false, 'exit'],
    queryFn: () => fetchTrackerStats({ sync: false, view: 'exit' }),
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  });

  const strategyPairsCsv = useMemo(() => {
    const op = (tracker as TrackerStats | undefined)?.open_positions ?? {};
    const pairs = Object.entries(op)
      .filter(([p, v]) => {
        if (!String(p || '').trim()) return false;
        const sysId = String((v as Record<string, unknown>)?.system_id ?? 'strategy').toLowerCase().trim();
        if (sysId && sysId !== 'strategy') return false;
        const owner = String((v as Record<string, unknown>)?.exit_owner ?? '').toLowerCase().trim();
        if (owner === 'carry_trade') return false;
        return true;
      })
      .map(([p]) => p);
    return pairs.length ? pairs.join(',') : '';
  }, [tracker]);

  const manualSyncMutation = useMutation({
    mutationFn: () => fetchTrackerStats({ sync: true, force: true, view: 'exit' }),
    onSuccess: (st) => {
      const build = (src: Record<string, unknown>) => {
        const ok = typeof src.sync_ok === 'boolean' ? src.sync_ok : null;
        const last = _toNum(src.last_sync_ts ?? src.ts, 0);
        const age = nowMs > 0 && last > 0 ? nowMs - last : null;
        const open = _toNum(src.open_position_count, NaN);
        const pruned = _toNum(src.pruned_open_positions, NaN);
        return {
          ok,
          age,
          open: Number.isFinite(open) ? open : null,
          pruned: Number.isFinite(pruned) ? pruned : null,
        };
      };

      const hl = build((((st as TrackerStats | undefined)?.hl ?? {}) as Record<string, unknown>));
      const aster = build((((st as TrackerStats | undefined)?.aster ?? {}) as Record<string, unknown>));
      setManualSyncMsg([
        `hl(ok=${hl.ok === null ? 'N/A' : (hl.ok ? 'OK' : 'FAIL')}, age=${hl.age === null ? 'N/A' : _msToCompact(hl.age)}, open=${hl.open === null ? 'N/A' : String(hl.open)}, pruned=${hl.pruned === null ? 'N/A' : String(hl.pruned)})`,
        `aster(ok=${aster.ok === null ? 'N/A' : (aster.ok ? 'OK' : 'FAIL')}, age=${aster.age === null ? 'N/A' : _msToCompact(aster.age)}, open=${aster.open === null ? 'N/A' : String(aster.open)}, pruned=${aster.pruned === null ? 'N/A' : String(aster.pruned)})`,
      ].join(' · '));
      queryClient.invalidateQueries({ queryKey: ['tracker'] });
    },
    onError: (e) => {
      setManualSyncMsg(String(e));
    },
  });

  const trackerSync = useMemo(() => {
    const build = (src: Record<string, unknown>) => {
      const okRaw = src.sync_ok;
      const ok = typeof okRaw === 'boolean' ? okRaw : null;
      const last = _toNum(src.last_sync_ts ?? src.ts, 0);
      const age = nowMs > 0 && last > 0 ? (nowMs - last) : null;
      const err = src.last_sync_error === null || src.last_sync_error === undefined ? '' : String(src.last_sync_error);
      const open = _toNum(src.open_position_count, NaN);
      const pruned = _toNum(src.pruned_open_positions, NaN);
      return {
        ok,
        last: last > 0 ? last : null,
        age,
        err,
        open: Number.isFinite(open) ? open : null,
        pruned: Number.isFinite(pruned) ? pruned : null,
      };
    };
    return {
      hl: build((((tracker as TrackerStats | undefined)?.hl ?? {}) as Record<string, unknown>)),
      aster: build((((tracker as TrackerStats | undefined)?.aster ?? {}) as Record<string, unknown>)),
    };
  }, [tracker, nowMs]);

  const { data: gateHistory } = useQuery({
    queryKey: ['tracker', 'gate_history'],
    queryFn: () => fetchTrackerGateHistory({ limit: 500, system_id: 'all' }),
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  });

  const exitMonitorQuery = useQuery({
    queryKey: ['exit', 'ml', 'monitor'],
    queryFn: () => fetchExitMlMonitor({ include_charts: false, auto_eval: true, limit: 200 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const exitLatestFeaturesQuery = useQuery({
    queryKey: ['exit', 'latest_features', strategyPairsCsv],
    queryFn: () => fetchExitLatestFeatures(strategyPairsCsv ? { pairs: strategyPairsCsv, include_macro: false } : { include_macro: false }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: carryRecentOrders } = useQuery({
    queryKey: ['orders', 'recent', 'CarryTrade'],
    queryFn: () => fetchRecentOrdersWithParams({ limit: 50, sort: 'ingest', include_shadow: 1, strategy_id: 'CarryTrade' }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const carryRecentOrdersRows = useMemo(() => {
    const xs = Array.isArray(carryRecentOrders) ? carryRecentOrders : [];
    if (carryOrdersWindow === 'all') return xs;
    if (!Number.isFinite(nowMs) || nowMs <= 0) return xs;
    const windowMs = carryOrdersWindow === '24h' ? 24 * 3600_000 : 7 * 24 * 3600_000;
    const lo = nowMs - windowMs;
    return xs.filter((o) => {
      const ts = Number((o as unknown as Record<string, unknown>)?.ts ?? NaN);
      return Number.isFinite(ts) && ts >= lo;
    });
  }, [carryRecentOrders, carryOrdersWindow, nowMs]);

  const carryRecentOrdersRowsView = useMemo(
    () => filterOrdersForUi(carryRecentOrdersRows, { showShadow: carryOrdersShowShadow, showSimulated: carryOrdersShowSimulated }),
    [carryRecentOrdersRows, carryOrdersShowShadow, carryOrdersShowSimulated]
  );

  const carryRouteStats = useMemo(() => {
    const xs = carryRecentOrdersRows;
    let bad = 0;
    let live = 0;
    let sim = 0;
    for (const o of xs) {
      const oAny = o as unknown as Record<string, unknown>;
      const isSimLike = isOrderSimulatedLike(oAny);
      if (isSimLike) {
        sim += 1;
        continue;
      }
      live += 1;
      const ex = String(oAny.exchange ?? '').toLowerCase().trim();
      const ev = String((((oAny.exec ?? {}) as Record<string, unknown>)?.venue ?? '')).toLowerCase().trim();
      if ((Boolean(ex) && ex !== 'hyperliquid') || (Boolean(ev) && ev !== 'hyperliquid')) bad += 1;
    }
    return { total: xs.length, bad, live, sim };
  }, [carryRecentOrdersRows]);

  const { data: quantRecentOrders } = useQuery({
    queryKey: ['orders', 'recent', 'quant'],
    queryFn: () => fetchRecentOrdersWithParams({ limit: 50, sort: 'ingest', include_shadow: 1, ab_owner: 'quant' }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const quantRecentOrdersRows = useMemo(() => {
    const xs = Array.isArray(quantRecentOrders) ? quantRecentOrders : [];
    return filterOrdersForUi(xs, { showShadow: quantOrdersShowShadow, showSimulated: quantOrdersShowSimulated });
  }, [quantRecentOrders, quantOrdersShowShadow, quantOrdersShowSimulated]);

  const quantBtcEthLatest = useMemo(() => {
    const xs = quantRecentOrdersRows;
    const btceth = xs.filter((o) => {
      const rec = o as unknown as Record<string, unknown>;
      const sid = String(rec.strategy_id ?? '').toLowerCase().trim();
      const tag = String(rec.tag ?? '').toLowerCase().trim();
      return sid.includes('quant_pairs_btceth') || tag.includes('quant_pairs_btceth|pair_');
    });
    const latestTag = String((btceth[0] as unknown as Record<string, unknown> | undefined)?.tag ?? '').trim();
    const rows = latestTag ? btceth.filter(o => String((o as unknown as Record<string, unknown>).tag ?? '').trim() === latestTag) : [];
    return { latestTag, rows };
  }, [quantRecentOrdersRows]);

  const openPositionsRows = useMemo(() => {
    const op = (tracker as TrackerStats | undefined)?.open_positions ?? {};
    const rows: {
      pair: string;
      venue: string | null;
      side: string | null;
      owner: string | null;
      leverage: number | null;
      notional_usdc: number;
      age_ms: number;
      last_sync_age_ms: number | null;
      unreal_pnl_u: number | null;
      unreal_pnl_pct: number | null;
      pnl_eff_pct: number | null;
      mrd_dir: string | null;
      mrd_p_dir: number | null;
      hold_risk: number | null;
      hold_value: number | null;
      l1_action: string | null;
      l1_reason: string | null;
      l1_ts_age_ms: number | null;
    }[] = [];
    for (const [pair, v] of Object.entries(op)) {
      const venue = String((v as Record<string, unknown>)?.venue ?? '').toLowerCase() || null;
      const side = String((v as Record<string, unknown>)?.side ?? '').toLowerCase() || null;
      const owner = String((v as Record<string, unknown>)?.exit_owner ?? '') || null;
      const sysId = String((v as Record<string, unknown>)?.system_id ?? 'strategy').toLowerCase().trim();
      if (sysId && sysId !== 'strategy' && sysId !== 'quant') continue;
      if (String(owner || '').toLowerCase().trim() === 'carry_trade') continue;
      const levRaw = _toNum((v as Record<string, unknown>)?.hl_leverage ?? (v as Record<string, unknown>)?.leverage, NaN);
      const lev = Number.isFinite(levRaw) && levRaw > 0 ? Math.floor(levRaw) : null;
      const notional = _toNum((v as Record<string, unknown>)?.notional_usdc, 0);
      const ts = _toNum((v as Record<string, unknown>)?.ts, 0);
      const lastSyncTs = _toNum((v as Record<string, unknown>)?.last_sync_ts, 0);
      const lastSyncAge = nowMs > 0 && lastSyncTs > 0 ? (nowMs - lastSyncTs) : null;
      const unrealPct = _toNum((v as Record<string, unknown>)?.unrealized_pnl_pct, NaN);
      const unrealURaw = _toNum(
        (v as Record<string, unknown>)?.hl_unrealized_pnl_u ?? (v as Record<string, unknown>)?.aster_unrealized_pnl_u ?? (v as Record<string, unknown>)?.unrealized_pnl_u,
        NaN,
      );
      const unrealU = Number.isFinite(unrealURaw)
        ? unrealURaw
        : (Number.isFinite(unrealPct) ? (unrealPct * notional) : NaN);

      const snap = ((v as Record<string, unknown>)?.exit_snapshot ?? null) as Record<string, unknown> | null;
      const snapEff = _toNum(snap?.pnl_eff, NaN);
      const pnlEff = Number.isFinite(snapEff)
        ? snapEff
        : (Number.isFinite(unrealPct) ? (unrealPct * (lev ?? 1)) : NaN);

      const mrdDir = String((v as Record<string, unknown>)?.macro_mrd_dir ?? '').toLowerCase() || null;
      const mrdPDir = _toNum((v as Record<string, unknown>)?.macro_p_mrd_dir, NaN);

      const hr = _toNum((v as Record<string, unknown>)?.hold_risk, NaN);
      const hv = _toNum((v as Record<string, unknown>)?.hold_value, NaN);
      const dec = ((v as Record<string, unknown>)?.exit_l1_last_decision ?? null) as Record<string, unknown> | null;
      const decAction = dec && typeof dec.action === 'string' ? dec.action : null;
      const decReason = dec && typeof dec.reason === 'string' ? dec.reason : null;
      const decTs = _toNum((v as Record<string, unknown>)?.exit_l1_last_decision_ts, 0);
      const decAge = nowMs > 0 && decTs > 0 ? (nowMs - decTs) : null;
      rows.push({
        pair,
        venue,
        side,
        owner,
        leverage: lev,
        notional_usdc: notional,
        age_ms: nowMs > 0 && ts > 0 ? nowMs - ts : 0,
        last_sync_age_ms: lastSyncAge,
        unreal_pnl_u: Number.isFinite(unrealU) ? unrealU : null,
        unreal_pnl_pct: Number.isFinite(unrealPct) ? unrealPct : null,
        pnl_eff_pct: Number.isFinite(pnlEff) ? pnlEff : null,
        mrd_dir: mrdDir ? mrdDir : null,
        mrd_p_dir: Number.isFinite(mrdPDir) ? mrdPDir : null,
        hold_risk: Number.isFinite(hr) ? hr : null,
        hold_value: Number.isFinite(hv) ? hv : null,
        l1_action: decAction,
        l1_reason: decReason,
        l1_ts_age_ms: decAge,
      });
    }
    rows.sort((a, b) => b.notional_usdc - a.notional_usdc);
    return rows;
  }, [tracker, nowMs]);

  const postCloseRows = useMemo(() => {
    const pcs = (tracker as TrackerStats | undefined)?.post_close_cooldowns ?? {};
    const c = (cfg ?? {}) as Record<string, unknown>;
    const freezeH = Math.max(0, _toNum(c.coin_freeze_post_close_hours, 4));
    const freezeMs = freezeH * 3600 * 1000;
    const rows: { pair: string; ts: number; remain_ms: number }[] = [];
    for (const [pair, tsRaw] of Object.entries(pcs)) {
      const ts = _toNum(tsRaw, 0);
      if (ts <= 0 || freezeMs <= 0) continue;
      rows.push({ pair, ts, remain_ms: Math.max(0, (ts + freezeMs) - nowMs) });
    }
    rows.sort((a, b) => b.remain_ms - a.remain_ms);
    return { rows, freezeH };
  }, [tracker, cfg, nowMs]);

  const exitInflightRows = useMemo(() => {
    const inflight = (tracker as TrackerStats | undefined)?.exit_inflight ?? {};
    const c = (cfg ?? {}) as Record<string, unknown>;
    const cdSec = Math.max(0, _toNum(c.exit_inflight_cooldown_sec, 90));
    const cdMs = cdSec * 1000;
    const rows: { pair: string; ts: number; remain_ms: number }[] = [];
    for (const [pair, tsRaw] of Object.entries(inflight)) {
      const ts = _toNum(tsRaw, 0);
      if (ts <= 0 || cdMs <= 0) continue;
      rows.push({ pair, ts, remain_ms: Math.max(0, (ts + cdMs) - nowMs) });
    }
    rows.sort((a, b) => b.remain_ms - a.remain_ms);
    return { rows, cdSec };
  }, [tracker, cfg, nowMs]);

  const exitCfgGroups = useMemo(() => {
    const c = (cfg ?? {}) as Record<string, unknown>;
    const a = ((automation as AutomationStrategiesConfigResponse | undefined)?.automation ?? {}) as Record<string, unknown>;
    type CfgRow = { k: string; v: unknown };
    type CfgGroup = { title: string; rows: CfgRow[] };

    const feederRows: CfgRow[] = [];
    const strategyRows: CfgRow[] = [];
    const quantRows: CfgRow[] = [];
    const carryRows: CfgRow[] = [];

    const push = (rows: CfgRow[], k: string, v: unknown) => rows.push({ k, v });

    push(feederRows, 'enable_strategy_feeders', a.enable_strategy_feeders);
    push(feederRows, 'use_exit_feeder', a.use_exit_feeder);
    push(feederRows, 'use_exit_feeder_strategy', a.use_exit_feeder_strategy);
    push(feederRows, 'exit_feeder_period_seconds', a.exit_feeder_period_seconds);
    push(feederRows, 'feeders_period_seconds', a.feeders_period_seconds);
    push(feederRows, 'use_universe_core', a.use_universe_core);

    push(strategyRows, 'exit_shadow_mode', c.exit_shadow_mode);
    push(strategyRows, 'strategy_exit_enabled', c.strategy_exit_enabled);

    push(strategyRows, 'exit_owner_init_exit_feeder_weight', c.exit_owner_init_exit_feeder_weight);
    push(strategyRows, 'exit_owner_reweight_every', c.exit_owner_reweight_every);
    push(strategyRows, 'exit_owner_reweight_lambda', c.exit_owner_reweight_lambda);
    push(strategyRows, 'exit_owner_reweight_mu', c.exit_owner_reweight_mu);
    push(strategyRows, 'exit_owner_weight_step', c.exit_owner_weight_step);
    push(strategyRows, 'exit_owner_weight_floor', c.exit_owner_weight_floor);
    push(strategyRows, 'exit_owner_weight_cap', c.exit_owner_weight_cap);

    push(strategyRows, 'exit_l0_max_hold_sec', c.exit_l0_max_hold_sec);
    push(strategyRows, 'exit_l0_max_unrealized_loss_pct', c.exit_l0_max_unrealized_loss_pct);
    push(strategyRows, 'exit_apply_leverage_to_thresholds', c.exit_apply_leverage_to_thresholds);
    push(strategyRows, 'exit_inflight_cooldown_sec', c.exit_inflight_cooldown_sec);
    push(strategyRows, 'coin_freeze_post_close_hours', c.coin_freeze_post_close_hours);

    push(strategyRows, 'exit_gate_enabled', c.exit_gate_enabled);
    push(strategyRows, 'exit_gate_use_model', c.exit_gate_use_model);
    push(strategyRows, 'exit_gate_min_conf', c.exit_gate_min_conf);
    push(strategyRows, 'exit_gate_fallback_min_model_conf', c.exit_gate_fallback_min_model_conf);

    push(strategyRows, 'exit_risk_gate_enabled', c.exit_risk_gate_enabled);
    push(strategyRows, 'exit_risk_gate_long_thr', c.exit_risk_gate_long_thr);
    push(strategyRows, 'exit_risk_gate_short_thr', c.exit_risk_gate_short_thr);
    push(strategyRows, 'exit_risk_gate_confirm_n', c.exit_risk_gate_confirm_n);
    push(strategyRows, 'exit_risk_gate_min_hold_sec', c.exit_risk_gate_min_hold_sec);
    push(strategyRows, 'exit_risk_gate_cooldown_min', c.exit_risk_gate_cooldown_min);
    push(strategyRows, 'exit_risk_gate_reduce_frac', c.exit_risk_gate_reduce_frac);
    push(strategyRows, 'exit_risk_gate_close_delay_min', c.exit_risk_gate_close_delay_min);
    push(strategyRows, 'exit_risk_gate_close_risk_boost', c.exit_risk_gate_close_risk_boost);
    push(strategyRows, 'exit_observe_enabled', c.exit_observe_enabled);
    push(strategyRows, 'exit_observe_min_interval_sec', c.exit_observe_min_interval_sec);
    push(strategyRows, 'exit_l1_enabled', c.exit_l1_enabled);
    push(strategyRows, 'exit_l1_hysteresis_n', c.exit_l1_hysteresis_n);
    push(strategyRows, 'exit_l1_action_cooldown_sec', c.exit_l1_action_cooldown_sec);
    push(strategyRows, 'exit_l1_close_cooldown_sec', c.exit_l1_close_cooldown_sec);
    push(strategyRows, 'exit_l1_reduce_cooldown_sec', c.exit_l1_reduce_cooldown_sec);
    push(strategyRows, 'exit_tb_enabled', c.exit_tb_enabled);
    push(strategyRows, 'exit_tstp_enabled', c.exit_tstp_enabled);
    push(strategyRows, 'exit_l2_reduce_frac', c.exit_l2_reduce_frac);
    push(strategyRows, 'exit_l2_take_profit_pct', c.exit_l2_take_profit_pct);
    push(strategyRows, 'exit_l2_trailing_retrace_pct', c.exit_l2_trailing_retrace_pct);
    push(strategyRows, 'exit_feeder_max_open_age_sec', c.exit_feeder_max_open_age_sec);
    push(strategyRows, 'exit_feeder_max_notional_usdc', c.exit_feeder_max_notional_usdc);

    push(strategyRows, 'entry_risk_gate_enabled', c.entry_risk_gate_enabled);
    push(strategyRows, 'entry_risk_gate_long_max', c.entry_risk_gate_long_max);
    push(strategyRows, 'entry_risk_gate_short_max', c.entry_risk_gate_short_max);

    push(strategyRows, 'leverage_dynamic_enabled', c.leverage_dynamic_enabled);
    push(strategyRows, 'leverage_dynamic_min', c.leverage_dynamic_min);
    push(strategyRows, 'leverage_dynamic_max', c.leverage_dynamic_max);

    push(quantRows, 'quant_pairs_btceth_exit_pnl_enabled', c.quant_pairs_btceth_exit_pnl_enabled);
    push(quantRows, 'quant_pairs_btcalt_exit_pnl_enabled', c.quant_pairs_btcalt_exit_pnl_enabled);

    push(carryRows, 'carry_trade_soft_no_exit_reduce_enabled', c.carry_trade_soft_no_exit_reduce_enabled);

    const groups: CfgGroup[] = [
      { title: 'Exit Feeder', rows: feederRows },
      { title: 'Strategy Exit', rows: strategyRows },
      { title: 'Quant Exit', rows: quantRows },
      { title: 'Carry Exit', rows: carryRows },
    ];
    return groups.filter(g => g.rows.length > 0);
  }, [cfg, automation]);

  const exitEvents = useMemo(() => {
    const gh = (gateHistory as { history?: GateHistoryItem[] } | undefined)?.history ?? [];
    const xs = Array.isArray(gh) ? gh : [];
    return xs.filter(it => {
      const r = String(it.reason || '');
      const isExit = r.toLowerCase().includes('exit') || /market_close/i.test(r);
      if (!isExit) return false;
      const exitOwner = String((it as Record<string, unknown>).exit_owner ?? '').toLowerCase().trim();
      if (exitOwner === 'carry_trade') return false;
      const sysId = String((it as Record<string, unknown>).system_id ?? 'strategy').toLowerCase().trim();
      if (sysId && sysId !== 'strategy' && sysId !== 'quant') return false;
      if (!showShadowExitEvents && Boolean((it as Record<string, unknown>).shadow)) return false;
      return true;
    });
  }, [gateHistory, showShadowExitEvents]);

  const calmarSortino = useMemo(() => {
    const m = exitMetrics as ExitMetricsResponse | undefined;
    const toNumOrNull = (v: unknown): number | null => {
      const x = typeof v === 'number' ? v : Number(v ?? NaN);
      return Number.isFinite(x) ? x : null;
    };
    return {
      total: toNumOrNull(m?.total),
      maxdd: toNumOrNull(m?.maxdd),
      calmar: toNumOrNull(m?.calmar),
      sortino: toNumOrNull(m?.sortino),
      trades: toNumOrNull(m?.trades),
      winrate: toNumOrNull(m?.winrate),
      fees_u: toNumOrNull(m?.fees_u),
      funding_u: toNumOrNull(m?.funding_u),
    };
  }, [exitMetrics]);

  const exitOwnerHistory = useMemo(() => {
    const h = (tracker as TrackerStats | undefined)?.exit_owner_state?.history ?? [];
    const xs = Array.isArray(h) ? h : [];
    return xs.map((x) => {
      const ts = _toNum((x as Record<string, unknown>)?.ts, 0);
      const pair = String((x as Record<string, unknown>)?.pair ?? '');
      const owner = String((x as Record<string, unknown>)?.owner ?? '');
      const action = String((x as Record<string, unknown>)?.action ?? '');
      const reason = String((x as Record<string, unknown>)?.reason ?? '');
      const pnlU = _toNum((x as Record<string, unknown>)?.pnl_u, NaN);
      const pnlPct = _toNum((x as Record<string, unknown>)?.pnl_pct, NaN);
      return { ts, pair, owner, action, reason, pnl_u: pnlU, pnl_pct: pnlPct };
    }).filter(x => Number.isFinite(x.ts) && x.ts > 0 && x.owner);
  }, [tracker]);

  const exitCompare = useMemo(() => {
    const closeOnly = exitOwnerHistory.filter(x => (x.action || '').toLowerCase() === 'close' && Number.isFinite(x.pnl_u));
    const ownerNorm = (o: string) => String(o || '').toLowerCase().replace(/\s+/g, '');
    const classify = (o: string): 'strategy' | 'smart' | 'other' => {
      const s = ownerNorm(o);
      if (s.includes('strategy')) return 'strategy';
      if (s.includes('exit') || s.includes('feeder') || s.includes('smart')) return 'smart';
      if (!s) return 'other';
      return 'smart';
    };
    const a = closeOnly.filter(x => classify(x.owner) === 'strategy');
    const b = closeOnly.filter(x => classify(x.owner) === 'smart');

    const agg = (xs: { ts: number; pair: string; pnl_u: number; pnl_pct: number; reason: string; owner: string }[]) => {
      const rets = xs.map(x => ({ ts: x.ts, r: Number(x.pnl_u) }));
      const pnlU = xs.map(x => Number(x.pnl_u));
      const pnlPct = xs.filter(x => Number.isFinite(x.pnl_pct)).map(x => Number(x.pnl_pct));
      const wins = pnlU.filter(x => x > 0);
      const losses = pnlU.filter(x => x < 0);
      const sumWin = wins.reduce((s, x) => s + x, 0);
      const sumLossAbs = Math.abs(losses.reduce((s, x) => s + x, 0));
      const pf = sumLossAbs > 1e-12 ? sumWin / sumLossAbs : (sumWin > 0 ? Infinity : null);
      const avgWin = wins.length ? (sumWin / wins.length) : null;
      const avgLossAbs = losses.length ? (sumLossAbs / losses.length) : null;
      const payoff = avgWin !== null && avgLossAbs !== null && avgLossAbs > 1e-12 ? (avgWin / avgLossAbs) : null;
      const best = pnlU.length ? Math.max(...pnlU) : null;
      const worst = pnlU.length ? Math.min(...pnlU) : null;
      const cvar05 = _cvar(pnlU, 0.05);
      const maxLoseStreak = _maxConsecutive(pnlU, x => x < 0);

      const byReason: Record<string, number> = {};
      const byOwner: Record<string, number> = {};
      const byPair: Record<string, { n: number; pnl: number }> = {};
      for (const x of xs) {
        const r = String(x.reason || '');
        const o = String(x.owner || '');
        const p = String(x.pair || '');
        if (r) byReason[r] = (byReason[r] ?? 0) + 1;
        if (o) byOwner[o] = (byOwner[o] ?? 0) + 1;
        if (p) {
          const cur = byPair[p] ?? { n: 0, pnl: 0 };
          byPair[p] = { n: cur.n + 1, pnl: cur.pnl + Number(x.pnl_u) };
        }
      }
      const topReasons = Object.entries(byReason).sort((x, y) => y[1] - x[1]).slice(0, 6);
      const owners = Object.entries(byOwner).sort((x, y) => y[1] - x[1]);
      const topPairs = Object.entries(byPair)
        .sort((a, b) => b[1].n - a[1].n)
        .slice(0, 6)
        .map(([p, st]) => [p, st.n] as const);
      const topPairsByPnl = Object.entries(byPair)
        .sort((a, b) => b[1].pnl - a[1].pnl)
        .slice(0, 6)
        .map(([p, st]) => [p, st.pnl] as const);

      const firstTs = xs.length ? Math.min(...xs.map(x => x.ts)) : null;
      const lastTs = xs.length ? Math.max(...xs.map(x => x.ts)) : null;
      const spanDays = firstTs !== null && lastTs !== null ? Math.max(0, (lastTs - firstTs) / 86400000) : null;
      const tradesPerDay = spanDays !== null && spanDays > 0 ? (pnlU.length / spanDays) : null;

      const meanU = pnlU.length ? (pnlU.reduce((s, x) => s + x, 0) / pnlU.length) : null;
      const meanPct = pnlPct.length ? (pnlPct.reduce((s, x) => s + x, 0) / pnlPct.length) : null;
      const medU = _quantile(pnlU, 0.5);
      const p10 = _quantile(pnlU, 0.10);
      const p90 = _quantile(pnlU, 0.90);
      const winRate = pnlU.length ? (wins.length / pnlU.length) : null;
      const maxdd = rets.length ? _maxDrawdown(rets) : null;
      return {
        n: pnlU.length,
        wins: wins.length,
        losses: losses.length,
        winRate,
        meanU,
        meanPct,
        medU,
        p10,
        p90,
        pf,
        maxdd,
        avgWin,
        avgLossAbs,
        payoff,
        best,
        worst,
        cvar05,
        maxLoseStreak,
        firstTs,
        lastTs,
        tradesPerDay,
        topReasons,
        topPairs,
        topPairsByPnl,
        owners,
      };
    };

    return { strategy: agg(a), smart: agg(b) };
  }, [exitOwnerHistory]);

  const liveExecMeta = useMemo(() => {
    const c = (cfg ?? {}) as Record<string, unknown>;
    const a = ((automation as AutomationStrategiesConfigResponse | undefined)?.automation ?? {}) as Record<string, unknown>;
    const live = c.live_trading_enabled === true && c.dry_run !== true;
    const exec = c.exit_shadow_mode !== true;
    const venue = String(c.execution_venue ?? '').trim() || null;
    const exitFeeder = a.use_exit_feeder === true;
    const strategyExit = c.strategy_exit_enabled === true;
    return { live, exec, venue, exitFeeder, strategyExit };
  }, [cfg, automation]);

  const exitOwnerMeta = useMemo(() => {
    const st = (tracker as TrackerStats | undefined)?.exit_owner_state ?? undefined;
    const w = (st as { weights?: Record<string, number> } | undefined)?.weights ?? undefined;
    const wf = w ? _toNum(w.exit_feeder, NaN) : NaN;
    const ws = w ? _toNum(w.strategy, NaN) : NaN;
    const last = _toNum((st as { last_reweight_idx?: number } | undefined)?.last_reweight_idx, NaN);
    return {
      wf: Number.isFinite(wf) ? wf : null,
      ws: Number.isFinite(ws) ? ws : null,
      last: Number.isFinite(last) ? last : null,
    };
  }, [tracker]);

  const abView = useMemo(() => {
    const st = ((tracker as TrackerStats | undefined)?.ab_alloc_state ?? null) as Record<string, unknown> | null;
    const owners = (st?.owners ?? {}) as Record<string, unknown>;
    const now = nowMs > 0 ? nowMs : 0;

    const ownerRow = (k: 'strategy' | 'quant') => {
      const rec = (owners?.[k] ?? {}) as Record<string, unknown>;
      const m = (rec.metrics_72h ?? null) as Record<string, unknown> | null;
      const mAll = (rec.metrics_all ?? null) as Record<string, unknown> | null;
      const alloc = _toNum(rec.alloc, NaN);
      const cdUntil = _toNum(rec.cooldown_until_ms, 0);
      const cdActive = cdUntil > 0 && now > 0 && now < cdUntil;
      const cdRemain = cdActive ? (cdUntil - now) : 0;
      const cdReason = rec.cooldown_reason == null ? '' : String(rec.cooldown_reason);
      return {
        key: k,
        alloc: Number.isFinite(alloc) ? alloc : null,
        cooldown: cdActive ? { until_ms: cdUntil, remain_ms: cdRemain, reason: cdReason || null } : null,
        metrics: m,
        metrics_all: mAll,
      };
    };

    const rejects = (st?.rejects_72h ?? null) as Record<string, unknown> | null;
    const rejN = rejects ? _toNum(rejects.n, 0) : 0;
    const rejBy = (rejects?.by_reason ?? {}) as Record<string, unknown>;
    const rejPairs = Object.entries(rejBy)
      .map(([k, v]) => [k, _toNum(v, NaN)] as const)
      .filter(([, v]) => Number.isFinite(v) && v > 0)
      .sort((a, b) => b[1] - a[1]);

    const dedupN = rejPairs.filter(([k]) => k.startsWith('dedup')).reduce((s, [, v]) => s + v, 0);

    const mh = (st?.merge_health_72h ?? null) as Record<string, unknown> | null;
    const mhCounts = ((mh?.counts ?? {}) as Record<string, unknown>) ?? {};
    const mhEventsN = mh ? _toNum(mh.events_n, 0) : 0;
    const mhSame = _toNum(mhCounts.same_side_merge, 0);
    const mhConflict = _toNum(mhCounts.conflict_arbitration, 0);
    const mhDeadband = _toNum(mhCounts.deadband_hold, 0);

    const lastAdj = _toNum(st?.last_adjust_ms, 0);
    const windowMs = _toNum(st?.window_ms, 0);
    const minTrades = _toNum(st?.min_trades_72h, NaN);
    const stepMax = _toNum(st?.step_max, NaN);
    const minAlloc = _toNum(st?.min_alloc, NaN);
    const maxAlloc = _toNum(st?.max_alloc, NaN);

    return {
      ok: Boolean(st),
      now,
      window_ms: windowMs > 0 ? windowMs : null,
      last_adjust_ms: lastAdj > 0 ? lastAdj : null,
      min_trades_72h: Number.isFinite(minTrades) ? minTrades : null,
      step_max: Number.isFinite(stepMax) ? stepMax : null,
      min_alloc: Number.isFinite(minAlloc) ? minAlloc : null,
      max_alloc: Number.isFinite(maxAlloc) ? maxAlloc : null,
      owners: {
        strategy: ownerRow('strategy'),
        quant: ownerRow('quant'),
      },
      merge: {
        events_n: mhEventsN,
        same_side_merge: mhSame,
        conflict_arbitration: mhConflict,
        deadband_hold: mhDeadband,
      },
      rejects: {
        n: rejN,
        dedup_n: dedupN,
        top: rejPairs.slice(0, 12),
      },
    };
  }, [tracker, nowMs]);

  const abExposure = useMemo(() => {
    const op = (tracker as TrackerStats | undefined)?.open_positions ?? {};

    const toCoin = (pair: string) => {
      const p = String(pair || '').trim();
      if (!p) return 'N/A';
      if (p.includes('/')) return p.split('/')[0]?.trim().toUpperCase() || 'N/A';
      if (p.includes('-')) return p.split('-')[0]?.trim().toUpperCase() || 'N/A';
      const m = p.match(/^[A-Za-z]{2,10}/);
      return (m?.[0] ?? p).trim().toUpperCase() || 'N/A';
    };

    const totals = { strategy: 0, quant: 0 };
    const coins: { strategy: Record<string, number>; quant: Record<string, number> } = { strategy: {}, quant: {} };
    let positions = 0;

    for (const [pair, v] of Object.entries(op)) {
      const sysId = String((v as Record<string, unknown>)?.system_id ?? 'strategy').toLowerCase().trim();
      if (sysId && sysId !== 'strategy') continue;
      const owner = String((v as Record<string, unknown>)?.exit_owner ?? '').toLowerCase().trim();
      if (owner === 'carry_trade') continue;

      const notional = _toNum((v as Record<string, unknown>)?.notional_usdc, 0);
      if (!Number.isFinite(notional) || notional <= 0) continue;

      const ocRaw = ((v as Record<string, unknown>)?.owner_contrib ?? null) as Record<string, unknown> | null;
      const abOwnerRaw = String((v as Record<string, unknown>)?.ab_owner ?? '').toLowerCase().trim();
      const oc = (ocRaw && typeof ocRaw === 'object')
        ? { ...ocRaw }
        : (abOwnerRaw ? { [abOwnerRaw]: 1 } : null);
      if (!oc) continue;

      const wS = Math.max(0, _toNum(oc.strategy, 0));
      const wQ = Math.max(0, _toNum(oc.quant, 0));
      const wSum = wS + wQ;
      if (wSum <= 0) continue;

      positions += 1;
      const coin = toCoin(pair);

      const add = (k: 'strategy' | 'quant', w: number) => {
        if (w <= 0) return;
        const amt = notional * (w / wSum);
        totals[k] += amt;
        coins[k][coin] = (coins[k][coin] ?? 0) + amt;
      };

      add('strategy', wS);
      add('quant', wQ);
    }

    const topCoins = (m: Record<string, number>) => Object.entries(m)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12);

    return {
      positions,
      totals,
      top: {
        strategy: topCoins(coins.strategy),
        quant: topCoins(coins.quant),
      },
    };
  }, [tracker]);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Overview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-3">
              <Badge variant="outline">Open Positions: {openPositionsRows.length}</Badge>
              <Badge variant={liveExecMeta.live ? 'outline' : 'destructive'}>
                Live Trading: {liveExecMeta.live ? 'ON' : 'OFF'}
              </Badge>
              <Badge variant={liveExecMeta.exec ? 'outline' : 'destructive'}>
                Exit 实盘执行: {liveExecMeta.exec ? 'ON' : 'OFF'}
              </Badge>
              <Badge variant="outline">Venue: {liveExecMeta.venue ?? 'N/A'}</Badge>
              <Badge variant={liveExecMeta.exitFeeder ? 'outline' : 'destructive'}>
                Exit Feeder: {liveExecMeta.exitFeeder ? 'ON' : 'OFF'}
              </Badge>
              <Badge variant={liveExecMeta.strategyExit ? 'outline' : 'destructive'}>
                Strategy Exit: {liveExecMeta.strategyExit ? 'ON' : 'OFF'}
              </Badge>
              <Badge variant="outline">HL Positions: {trackerSync.hl.open === null ? 'N/A' : String(trackerSync.hl.open)}</Badge>
              <Badge variant="outline">Aster Positions: {trackerSync.aster.open === null ? 'N/A' : String(trackerSync.aster.open)}</Badge>
              <Badge variant="outline">Exit Events: {exitEvents.length}</Badge>
              <Badge variant="outline">Signals: {_toNum((metrics as Metrics | undefined)?.signals, 0)}</Badge>
              <Badge variant="outline">Orders(live): {_toNum((metrics as Metrics | undefined)?.orders_execute ?? (metrics as Metrics | undefined)?.orders_live ?? (metrics as Metrics | undefined)?.orders, 0)}</Badge>
              <Badge variant={trackerSync.hl.ok === false ? 'destructive' : 'outline'}>
                HL Sync: {trackerSync.hl.ok === null ? 'N/A' : (trackerSync.hl.ok ? 'OK' : 'FAIL')}
              </Badge>
              <Badge variant="outline">HL Last: {trackerSync.hl.age === null ? 'N/A' : _msToCompact(Math.max(0, trackerSync.hl.age))}</Badge>
              <Badge variant="outline">HL Pruned: {trackerSync.hl.pruned === null ? 'N/A' : String(trackerSync.hl.pruned)}</Badge>
              <Badge variant={trackerSync.aster.ok === false ? 'destructive' : 'outline'}>
                Aster Sync: {trackerSync.aster.ok === null ? 'N/A' : (trackerSync.aster.ok ? 'OK' : 'FAIL')}
              </Badge>
              <Badge variant="outline">Aster Last: {trackerSync.aster.age === null ? 'N/A' : _msToCompact(Math.max(0, trackerSync.aster.age))}</Badge>
              <Badge variant="outline">Aster Pruned: {trackerSync.aster.pruned === null ? 'N/A' : String(trackerSync.aster.pruned)}</Badge>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setManualSyncMsg('');
                  manualSyncMutation.mutate();
                }}
                disabled={manualSyncMutation.isPending}
              >
                {manualSyncMutation.isPending ? 'Syncing…' : '手动同步'}
              </Button>
            </div>
            {trackerSync.hl.ok === false && trackerSync.hl.err ? (
              <div className="text-xs text-rose-600 break-all">hl: {trackerSync.hl.err}</div>
            ) : null}
            {trackerSync.aster.ok === false && trackerSync.aster.err ? (
              <div className="text-xs text-rose-600 break-all">aster: {trackerSync.aster.err}</div>
            ) : null}
            {manualSyncMsg ? (
              <div className="text-xs text-slate-600 break-all">{manualSyncMsg}</div>
            ) : null}
            <div className="text-sm text-slate-600">
              Total {calmarSortino.total === null ? 'N/A' : _fmtUsd(calmarSortino.total)} | Calmar {calmarSortino.calmar === null ? 'N/A' : calmarSortino.calmar.toFixed(2)} | Sortino {calmarSortino.sortino === null ? 'N/A' : calmarSortino.sortino.toFixed(2)} | MaxDD {calmarSortino.maxdd === null ? 'N/A' : _fmtUsd(calmarSortino.maxdd)} | Trades {calmarSortino.trades === null ? 'N/A' : String(Math.trunc(calmarSortino.trades))} | WinRate {calmarSortino.winrate === null ? 'N/A' : _fmtPct(calmarSortino.winrate, 1)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>离场开关管理</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-700">
            <div className="text-xs text-slate-600 mb-3">统一管理 Strategy / Quant / CarryTrade 的离场相关开关。</div>
            <div className="text-xs text-slate-500 mb-3">提示：Exit 实盘执行实际是否能执行，还受 Live Trading / dry_run / 权限影响。</div>

            <div className="flex flex-wrap items-center gap-2 mb-3">
              <Badge variant={liveExecMeta.live ? 'outline' : 'destructive'}>
                Live Trading: {liveExecMeta.live ? 'ON' : 'OFF'}
              </Badge>
              <Badge variant="outline">dry_run: {((cfg as Record<string, unknown> | undefined)?.dry_run === true) ? 'ON' : 'OFF'}</Badge>
              <Badge variant="outline">live_trading_enabled: {((cfg as Record<string, unknown> | undefined)?.live_trading_enabled === true) ? 'ON' : 'OFF'}</Badge>
              <Badge variant="outline">venue: {String((cfg as Record<string, unknown> | undefined)?.execution_venue ?? '') || 'N/A'}</Badge>

              <Button
                size="sm"
                variant={liveExecMeta.live ? 'outline' : 'default'}
                onClick={() => {
                  setSaveMsg('');
                  const c = (cfg ?? {}) as Record<string, unknown>;
                  const venueRaw = String(c.execution_venue ?? '').trim().toLowerCase();
                  const venue = venueRaw === 'aster' ? 'aster' : 'hyperliquid';
                  const patch: ConfigPatch = {
                    dry_run: false,
                    live_trading_enabled: true,
                    execution_venue: venue,
                    confirm_live: true,
                  };
                  if (venue === 'hyperliquid') patch.hl_trading_enabled = true;
                  if (venue === 'aster') patch.aster_trading_enabled = true;
                  saveConfigMutation.mutate(patch);
                }}
                disabled={saveConfigMutation.isPending}
              >
                {saveConfigMutation.isPending ? 'Saving…' : '开启 Live Trading'}
              </Button>

              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setSaveMsg('');
                  const patch: ConfigPatch = { live_trading_enabled: false, dry_run: true };
                  saveConfigMutation.mutate(patch);
                }}
                disabled={saveConfigMutation.isPending}
              >
                关闭 Live Trading
              </Button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={switches.exitExecEnabled}
                  onChange={(e) => {
                    setSwitchPatch({ exitExecEnabled: e.target.checked });
                  }}
                />
                <span>Exit 实盘执行</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={switches.exitFeederEnabled}
                  onChange={(e) => {
                    setSwitchPatch({ exitFeederEnabled: e.target.checked });
                  }}
                />
                <span>Exit Feeder</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={switches.strategyExitEnabled}
                  onChange={(e) => {
                    setSwitchPatch({ strategyExitEnabled: e.target.checked });
                  }}
                />
                <span>Strategy Exit</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={switches.quantBtcEthExitEnabled}
                  onChange={(e) => {
                    setSwitchPatch({ quantBtcEthExitEnabled: e.target.checked });
                  }}
                />
                <span>Quant BTC-ETH 离场</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={switches.quantBtcAltExitEnabled}
                  onChange={(e) => {
                    setSwitchPatch({ quantBtcAltExitEnabled: e.target.checked });
                  }}
                />
                <span>Quant BTC-ALT 离场</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={switches.carrySoftNoExitReduceEnabled}
                  onChange={(e) => {
                    setSwitchPatch({ carrySoftNoExitReduceEnabled: e.target.checked });
                  }}
                />
                <span>CarryTrade 软禁卖出减仓</span>
              </label>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                onClick={() => {
                  setSaveMsg('');
                  const patch: ConfigPatch = {
                    exit_shadow_mode: !switches.exitExecEnabled,
                    strategy_exit_enabled: Boolean(switches.strategyExitEnabled),
                    quant_pairs_btceth_exit_pnl_enabled: Boolean(switches.quantBtcEthExitEnabled),
                    quant_pairs_btcalt_exit_pnl_enabled: Boolean(switches.quantBtcAltExitEnabled),
                    carry_trade_soft_no_exit_reduce_enabled: Boolean(switches.carrySoftNoExitReduceEnabled),
                  };
                  saveConfigMutation.mutate(patch);
                }}
                disabled={saveConfigMutation.isPending}
              >
                {saveConfigMutation.isPending ? 'Saving…' : '保存 Config'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setSaveMsg('');
                  const a = (automation as AutomationStrategiesConfigResponse | undefined)?.automation;
                  if (!a) {
                    setSaveMsg('automation unavailable');
                    return;
                  }
                  const payload: AutomationStrategiesConfig = {
                    enable_strategy_feeders: Boolean(a.enable_strategy_feeders),
                    feeders_period_seconds: Number(a.feeders_period_seconds ?? 60),
                    strategy_feeders: Array.isArray(a.strategy_feeders) ? a.strategy_feeders : [],
                    use_universe_core: Boolean(a.use_universe_core),
                    exit_feeder_period_seconds: Number(a.exit_feeder_period_seconds ?? 60),
                    use_exit_feeder: Boolean(switches.exitFeederEnabled),
                    use_exit_feeder_strategy: Boolean(a.use_exit_feeder_strategy),
                  };
                  saveAutomationMutation.mutate(payload);
                }}
                disabled={saveAutomationMutation.isPending}
              >
                {saveAutomationMutation.isPending ? 'Saving…' : '保存 Exit Feeder'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setSaveMsg('');
                  setDraftSwitches(null);
                }}
              >
                重置
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setSaveMsg('');
                  saveConfigMutation.mutate(buildExitPresetPatch('trend'));
                }}
                disabled={saveConfigMutation.isPending}
              >
                趋势市默认参数
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setSaveMsg('');
                  saveConfigMutation.mutate(buildExitPresetPatch('chop'));
                }}
                disabled={saveConfigMutation.isPending}
              >
                震荡市默认参数
              </Button>
              {saveMsg ? <span className="text-xs text-slate-600 break-all">{saveMsg}</span> : null}
            </div>

            <div className="mt-4 text-xs text-slate-600 mb-2">当前配置快照（只读）</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">
              {exitCfgGroups.map((g) => (
                <React.Fragment key={g.title}>
                  <div className="col-span-full mt-2 mb-1 text-slate-700 font-semibold">{g.title}</div>
                  {g.rows.map(({ k, v }) => (
                    <div key={`${g.title}:${k}`} className="flex items-center justify-between gap-3">
                      <span className="text-slate-600">{k}</span>
                      <span className="font-mono">{v === null || v === undefined ? '-' : String(v)}</span>
                    </div>
                  ))}
                </React.Fragment>
              ))}
              {exitCfgGroups.length === 0 ? <div className="text-slate-500 text-xs">No config data</div> : null}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>路由验证（Recent Orders）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <div className="text-sm text-slate-700 font-semibold">CarryTrade（期望 exchange=hyperliquid）</div>
                <Badge variant={carryRouteStats.bad > 0 ? 'destructive' : 'secondary'}>
                  live mismatch {carryRouteStats.bad}/{carryRouteStats.live}
                </Badge>
                {carryRouteStats.sim > 0 ? (
                  <Badge variant="outline">sim {carryRouteStats.sim}</Badge>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant={carryOrdersWindow === '24h' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setCarryOrdersWindow('24h')}
                >
                  24h
                </Button>
                <Button
                  variant={carryOrdersWindow === '7d' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setCarryOrdersWindow('7d')}
                >
                  7d
                </Button>
                <Button
                  variant={carryOrdersWindow === 'all' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setCarryOrdersWindow('all')}
                >
                  all
                </Button>
                <Button variant={carryOrdersShowShadow ? 'default' : 'outline'} size="sm" onClick={() => setCarryOrdersShowShadow((v) => !v)}>
                  {carryOrdersShowShadow ? '含 shadow' : '不含 shadow'}
                </Button>
                <Button variant={carryOrdersShowSimulated ? 'default' : 'outline'} size="sm" onClick={() => setCarryOrdersShowSimulated((v) => !v)}>
                  {carryOrdersShowSimulated ? '含模拟' : '不含模拟'}
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-600">
                    <th className="px-2 py-2">Time</th>
                    <th className="px-2 py-2">Pair</th>
                    <th className="px-2 py-2">Side</th>
                    <th className="px-2 py-2">Owner</th>
                    <th className="px-2 py-2">Exchange</th>
                    <th className="px-2 py-2">ExecVenue</th>
                    <th className="px-2 py-2">Tag</th>
                    <th className="px-2 py-2">Mode</th>
                    <th className="px-2 py-2">Status</th>
                    <th className="px-2 py-2">OID</th>
                    <th className="px-2 py-2">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {carryRecentOrdersRowsView.slice(0, 12).map((o) => (
                    (() => {
                      const oAny = o as unknown as Record<string, unknown>;
                      const ex = String(o.exchange ?? '').toLowerCase().trim();
                      const ev = String((((o.exec ?? {}) as Record<string, unknown>)?.venue ?? '')).toLowerCase().trim();
                      const err = String((((oAny.exec ?? {}) as Record<string, unknown>)?.error ?? oAny.error ?? '')).trim();
                      const isSimLike = isOrderSimulatedLike(oAny);
                      const oidRaw = o.exchange_oid ?? (((oAny.exec ?? {}) as Record<string, unknown>)?.oid as unknown);
                      const oid = String(oidRaw ?? '').trim();
                      const mismatch = Boolean(ex) && ex !== 'hyperliquid';
                      const mismatch2 = Boolean(ev) && ev !== 'hyperliquid';
                      const bad = !isSimLike && (mismatch || mismatch2);
                      const warn = isSimLike && (mismatch || mismatch2);
                      return (
                    <tr key={o.id} className="border-t">
                      <td className="px-2 py-2 text-slate-700 whitespace-nowrap">{_fmtTs(Number(o.ts))}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.pair)}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.side)}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.ab_owner ?? '-')}</td>
                      <td className={`px-2 py-2 ${bad ? 'text-rose-700 font-medium' : (warn ? 'text-amber-700 font-medium' : 'text-slate-700')}`}>{String(o.exchange ?? '-')}</td>
                      <td className={`px-2 py-2 ${bad ? 'text-rose-700 font-medium' : (warn ? 'text-amber-700 font-medium' : 'text-slate-700')}`}>{String(((o.exec ?? {}) as Record<string, unknown>)?.venue ?? '-')}</td>
                      <td className="px-2 py-2 text-slate-700 max-w-[240px] truncate" title={String(o.tag ?? '')}>{String(o.tag ?? '-')}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.mode ?? '-')}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.status ?? '-')}</td>
                      <td className="px-2 py-2 text-slate-700 max-w-[220px] truncate" title={oid}>{oid || '-'}</td>
                      <td
                        className={`px-2 py-2 ${err ? 'text-rose-700' : 'text-slate-700'} max-w-[420px] truncate`}
                        title={err}
                      >
                        {err || '-'}
                      </td>
                    </tr>
                      );
                    })()
                  ))}
                  {carryRecentOrdersRowsView.length === 0 && (
                    <tr className="border-t">
                      <td className="px-2 py-3 text-slate-500" colSpan={11}>
                        No CarryTrade orders
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm text-slate-700 font-semibold">Quant（期望 exchange=aster）</div>
              <div className="flex items-center gap-2">
                <Button variant={quantOrdersShowShadow ? 'default' : 'outline'} size="sm" onClick={() => setQuantOrdersShowShadow((v) => !v)}>
                  {quantOrdersShowShadow ? '含 shadow' : '不含 shadow'}
                </Button>
                <Button variant={quantOrdersShowSimulated ? 'default' : 'outline'} size="sm" onClick={() => setQuantOrdersShowSimulated((v) => !v)}>
                  {quantOrdersShowSimulated ? '含模拟' : '不含模拟'}
                </Button>
              </div>
            </div>
            {quantBtcEthLatest.rows.length > 0 ? (
              <div className="text-xs text-slate-600 break-all">
                BTC-ETH latest: {quantBtcEthLatest.latestTag}
              </div>
            ) : null}
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-600">
                    <th className="px-2 py-2">Time</th>
                    <th className="px-2 py-2">Pair</th>
                    <th className="px-2 py-2">Side</th>
                    <th className="px-2 py-2">Owner</th>
                    <th className="px-2 py-2">Exchange</th>
                    <th className="px-2 py-2">ExecVenue</th>
                    <th className="px-2 py-2">Tag</th>
                    <th className="px-2 py-2">Mode</th>
                    <th className="px-2 py-2">Status</th>
                    <th className="px-2 py-2">OID</th>
                    <th className="px-2 py-2">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {(quantBtcEthLatest.rows.length > 0 ? quantBtcEthLatest.rows : quantRecentOrdersRows.slice(0, 12)).map((o) => (
                    (() => {
                      const oAny = o as unknown as Record<string, unknown>;
                      const ex = String(o.exchange ?? '').toLowerCase().trim();
                      const ev = String((((o.exec ?? {}) as Record<string, unknown>)?.venue ?? '')).toLowerCase().trim();
                      const err = String((((oAny.exec ?? {}) as Record<string, unknown>)?.error ?? oAny.error ?? '')).trim();
                      const isSimLike = isOrderSimulatedLike(oAny);
                      const oidRaw = o.exchange_oid ?? (((oAny.exec ?? {}) as Record<string, unknown>)?.oid as unknown);
                      const oid = String(oidRaw ?? '').trim();
                      const mismatch = Boolean(ex) && ex !== 'aster';
                      const mismatch2 = Boolean(ev) && ev !== 'aster';
                      const bad = !isSimLike && (mismatch || mismatch2);
                      const warn = isSimLike && (mismatch || mismatch2);
                      return (
                    <tr key={o.id} className="border-t">
                      <td className="px-2 py-2 text-slate-700 whitespace-nowrap">{_fmtTs(Number(o.ts))}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.pair)}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.side)}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.ab_owner ?? '-')}</td>
                      <td className={`px-2 py-2 ${bad ? 'text-rose-700 font-medium' : (warn ? 'text-amber-700 font-medium' : 'text-slate-700')}`}>{String(o.exchange ?? '-')}</td>
                      <td className={`px-2 py-2 ${bad ? 'text-rose-700 font-medium' : (warn ? 'text-amber-700 font-medium' : 'text-slate-700')}`}>{String(((o.exec ?? {}) as Record<string, unknown>)?.venue ?? '-')}</td>
                      <td className="px-2 py-2 text-slate-700 max-w-[240px] truncate" title={String(o.tag ?? '')}>{String(o.tag ?? '-')}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.mode ?? '-')}</td>
                      <td className="px-2 py-2 text-slate-700">{String(o.status ?? '-')}</td>
                      <td className="px-2 py-2 text-slate-700 max-w-[220px] truncate" title={oid}>{oid || '-'}</td>
                      <td
                        className={`px-2 py-2 ${err ? 'text-rose-700' : 'text-slate-700'} max-w-[420px] truncate`}
                        title={err}
                      >
                        {err || '-'}
                      </td>
                    </tr>
                      );
                    })()
                  ))}
                  {(quantBtcEthLatest.rows.length > 0 ? quantBtcEthLatest.rows.length : quantRecentOrdersRows.length) === 0 && (
                    <tr className="border-t">
                      <td className="px-2 py-3 text-slate-500" colSpan={11}>
                        No quant orders
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>冷却状态</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-slate-50 p-3 rounded">
              <div className="text-gray-500 mb-2">持仓冷却（post_close，{postCloseRows.freezeH}h）</div>
              <div className="flex flex-wrap gap-2">
                {postCloseRows.rows.length === 0 ? (
                  <Badge variant="secondary">暂无持仓冷却</Badge>
                ) : (
                  postCloseRows.rows.map(({ pair, remain_ms }) => (
                    <div key={pair} className="border rounded p-2 text-xs">
                      <div className="font-medium">{pair}</div>
                      <div className="text-slate-500">剩余: {_msToCompact(remain_ms)}</div>
                    </div>
                  ))
                )}
              </div>
            </div>
            <div className="bg-slate-50 p-3 rounded">
              <div className="text-gray-500 mb-2">平仓冷却（inflight，{exitInflightRows.cdSec}s）</div>
              <div className="flex flex-wrap gap-2">
                {exitInflightRows.rows.length === 0 ? (
                  <Badge variant="secondary">暂无平仓冷却</Badge>
                ) : (
                  exitInflightRows.rows.map(({ pair, remain_ms }) => (
                    <div key={pair} className="border rounded p-2 text-xs">
                      <div className="font-medium">{pair}</div>
                      <div className="text-slate-500">剩余: {_msToCompact(remain_ms)}</div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Strategy vs Quant A/B（72h）</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {!abView.ok ? (
            <div className="text-sm text-slate-500">A/B 数据未初始化（等待 /tracker/stats 写入 ab_alloc_state）</div>
          ) : (
            <>
              <div className="bg-slate-50 p-3 rounded">
                <div className="text-sm text-slate-700 font-semibold mb-2">Exposure（当前，按 owner_contrib 拆分）</div>
                <div className="flex flex-wrap gap-2 mb-2">
                  <Badge variant="outline">positions {String(abExposure.positions)}</Badge>
                  <Badge variant="outline">Strategy {_fmtUsd(abExposure.totals.strategy, 0)}</Badge>
                  <Badge variant="outline">Quant {_fmtUsd(abExposure.totals.quant, 0)}</Badge>
                  <Badge variant="outline">Total {_fmtUsd(abExposure.totals.strategy + abExposure.totals.quant, 0)}</Badge>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs text-slate-600 mb-1">Strategy Top Coins</div>
                    <div className="flex flex-wrap gap-2">
                      {abExposure.top.strategy.length ? abExposure.top.strategy.map(([c, u]) => (
                        <Badge key={c} variant="secondary">{c}:{_fmtUsd(u, 0)}</Badge>
                      )) : <Badge variant="secondary">暂无</Badge>}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-600 mb-1">Quant Top Coins</div>
                    <div className="flex flex-wrap gap-2">
                      {abExposure.top.quant.length ? abExposure.top.quant.map(([c, u]) => (
                        <Badge key={c} variant="secondary">{c}:{_fmtUsd(u, 0)}</Badge>
                      )) : <Badge variant="secondary">暂无</Badge>}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">Strategy alloc {abView.owners.strategy.alloc === null ? 'N/A' : _fmtPct(abView.owners.strategy.alloc, 1)}</Badge>
                <Badge variant="outline">Quant alloc {abView.owners.quant.alloc === null ? 'N/A' : _fmtPct(abView.owners.quant.alloc, 1)}</Badge>
                <Badge variant="outline">min_trades_72h {abView.min_trades_72h === null ? 'N/A' : String(abView.min_trades_72h)}</Badge>
                <Badge variant="outline">step_max {abView.step_max === null ? 'N/A' : _fmtPct(abView.step_max, 1)}</Badge>
                <Badge variant="outline">alloc_range {abView.min_alloc === null || abView.max_alloc === null ? 'N/A' : `${_fmtPct(abView.min_alloc, 0)}~${_fmtPct(abView.max_alloc, 0)}`}</Badge>
                <Badge variant="outline">last_adjust {abView.last_adjust_ms === null ? 'N/A' : new Date(abView.last_adjust_ms).toLocaleString()}</Badge>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {(['strategy', 'quant'] as const).map((k) => {
                  const cd = abView.owners[k].cooldown;
                  if (!cd) return <Badge key={k} variant="outline">{k} cooldown: none</Badge>;
                  return (
                    <Badge key={k} variant="destructive">{k} cooldown {cd.reason ? `(${cd.reason}) ` : ''}{_msToCompact(cd.remain_ms)}</Badge>
                  );
                })}
              </div>

              <div className="overflow-x-auto">
                <div className="text-xs text-slate-600 mb-1">72h</div>
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-600">
                      <th className="px-2 py-2">owner</th>
                      <th className="px-2 py-2">trades</th>
                      <th className="px-2 py-2">win_rate</th>
                      <th className="px-2 py-2">net_pnl</th>
                      <th className="px-2 py-2">PF</th>
                      <th className="px-2 py-2">maxDD</th>
                      <th className="px-2 py-2">ret</th>
                      <th className="px-2 py-2">dd_ret</th>
                      <th className="px-2 py-2">avg_hold</th>
                      <th className="px-2 py-2">erosion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(['strategy', 'quant'] as const).map((k) => {
                      const m = abView.owners[k].metrics;
                      const trades = _toNum(m?.trades, NaN);
                      const winRate = _toNum(m?.win_rate, NaN);
                      const pnl = _toNum(m?.net_pnl_usdc, NaN);
                      const pf = m?.profit_factor;
                      const maxdd = _toNum(m?.max_dd_usdc, NaN);
                      const ret = _toNum(m?.ret_ratio, NaN);
                      const ddRet = _toNum(m?.max_dd_ret_ratio, NaN);
                      const hold = _toNum(m?.avg_hold_ms, NaN);
                      const erosion = _toNum(m?.erosion_ret_ratio, NaN);
                      const pfStr = pf == null ? '-' : (Number(pf) === Infinity ? 'Inf' : (Number.isFinite(Number(pf)) ? Number(pf).toFixed(2) : '-'));
                      return (
                        <tr key={k} className="border-t">
                          <td className="px-2 py-2 font-medium text-slate-900">{k}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(trades) ? String(trades) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(winRate) ? _fmtPct(winRate, 1) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(pnl) ? _fmtUsd(pnl, 2) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{pfStr}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(maxdd) ? _fmtUsd(maxdd, 2) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(ret) ? _fmtPct(ret, 2) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(ddRet) ? _fmtPct(ddRet, 2) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(hold) ? _msToCompact(hold) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(erosion) ? _fmtPct(erosion, 3) : '-'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="overflow-x-auto">
                <div className="text-xs text-slate-600 mb-1">All-time（累计）</div>
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-slate-600">
                      <th className="px-2 py-2">owner</th>
                      <th className="px-2 py-2">trades</th>
                      <th className="px-2 py-2">win_rate</th>
                      <th className="px-2 py-2">net_pnl</th>
                      <th className="px-2 py-2">PF</th>
                      <th className="px-2 py-2">maxDD</th>
                      <th className="px-2 py-2">ret</th>
                      <th className="px-2 py-2">dd_ret</th>
                      <th className="px-2 py-2">avg_hold</th>
                      <th className="px-2 py-2">erosion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(['strategy', 'quant'] as const).map((k) => {
                      const m = abView.owners[k].metrics_all;
                      const trades = _toNum(m?.trades, NaN);
                      const winRate = _toNum(m?.win_rate, NaN);
                      const pnl = _toNum(m?.net_pnl_usdc, NaN);
                      const pf = m?.profit_factor;
                      const maxdd = _toNum(m?.max_dd_usdc, NaN);
                      const ret = _toNum(m?.ret_ratio, NaN);
                      const ddRet = _toNum(m?.max_dd_ret_ratio, NaN);
                      const hold = _toNum(m?.avg_hold_ms, NaN);
                      const erosion = _toNum(m?.erosion_ret_ratio, NaN);
                      const pfStr = pf == null ? '-' : (Number(pf) === Infinity ? 'Inf' : (Number.isFinite(Number(pf)) ? Number(pf).toFixed(2) : '-'));
                      return (
                        <tr key={k} className="border-t">
                          <td className="px-2 py-2 font-medium text-slate-900">{k}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(trades) ? String(trades) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(winRate) ? _fmtPct(winRate, 1) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(pnl) ? _fmtUsd(pnl, 2) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{pfStr}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(maxdd) ? _fmtUsd(maxdd, 2) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(ret) ? _fmtPct(ret, 2) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(ddRet) ? _fmtPct(ddRet, 2) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(hold) ? _msToCompact(hold) : '-'}</td>
                          <td className="px-2 py-2 text-slate-700">{Number.isFinite(erosion) ? _fmtPct(erosion, 3) : '-'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-slate-50 p-3 rounded">
                  <div className="text-sm text-slate-700 font-semibold mb-2">Merge Health（72h）</div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">events {String(abView.merge.events_n)}</Badge>
                    <Badge variant="outline">same_side_merge {String(abView.merge.same_side_merge)}</Badge>
                    <Badge variant="outline">conflict_arbitration {String(abView.merge.conflict_arbitration)}</Badge>
                    <Badge variant="outline">deadband_hold {String(abView.merge.deadband_hold)}</Badge>
                  </div>
                </div>

                <div className="bg-slate-50 p-3 rounded">
                  <div className="text-sm text-slate-700 font-semibold mb-2">Rejects（72h）</div>
                  <div className="flex flex-wrap gap-2 mb-2">
                    <Badge variant="outline">rejects {String(abView.rejects.n)}</Badge>
                    <Badge variant="outline">dedup {String(abView.rejects.dedup_n)}</Badge>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {abView.rejects.top.length ? abView.rejects.top.map(([r, n]) => (
                      <Badge key={r} variant="secondary">{r}:{String(n)}{abView.rejects.n > 0 ? ` (${Math.round((n / abView.rejects.n) * 100)}%)` : ''}</Badge>
                    )) : (
                      <Badge variant="secondary">暂无拒绝样本</Badge>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>策略平仓 vs 智能平仓（效果对比）</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between gap-4 mb-3">
            <div className="text-xs text-slate-600">数据源：/tracker/stats → exit_owner_state.history（以触发平仓时的持仓浮盈浮亏快照统计）</div>
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="outline">w_exit_feeder={exitOwnerMeta.wf === null ? 'N/A' : exitOwnerMeta.wf.toFixed(2)}</Badge>
              <Badge variant="outline">w_strategy={exitOwnerMeta.ws === null ? 'N/A' : exitOwnerMeta.ws.toFixed(2)}</Badge>
              <Badge variant="outline">last_reweight_idx={exitOwnerMeta.last === null ? 'N/A' : String(exitOwnerMeta.last)}</Badge>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {([
              { key: 'strategy', name: '策略平仓', x: exitCompare.strategy },
              { key: 'smart', name: '智能平仓', x: exitCompare.smart },
            ] as const).map(({ key, name, x }) => (
              <div key={key} className="border rounded p-3">
                <div className="flex items-center justify-between">
                  <div className="font-medium text-slate-900">{name}</div>
                  <Badge variant="outline">N={x.n}</Badge>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
                  <div className="flex justify-between"><span className="text-slate-600">胜率</span><span className="font-mono">{x.winRate === null ? 'N/A' : _fmtPct(x.winRate, 1)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">Profit Factor</span><span className="font-mono">{x.pf === null ? 'N/A' : (x.pf === Infinity ? 'Inf' : Number(x.pf).toFixed(2))}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">Wins/Losses</span><span className="font-mono">{x.n ? `${x.wins}/${x.losses}` : 'N/A'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">盈亏比</span><span className="font-mono">{x.payoff === null ? 'N/A' : Number(x.payoff).toFixed(2)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">均值PnL(u)</span><span className="font-mono">{x.meanU === null ? 'N/A' : _fmtUsd(x.meanU)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">中位PnL(u)</span><span className="font-mono">{x.medU === null ? 'N/A' : _fmtUsd(x.medU)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">P10/P90(u)</span><span className="font-mono">{x.p10 === null || x.p90 === null ? 'N/A' : `${_fmtUsd(x.p10)} / ${_fmtUsd(x.p90)}`}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">MaxDD(u)</span><span className="font-mono">{x.maxdd === null ? 'N/A' : _fmtUsd(x.maxdd)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">Best/Worst(u)</span><span className="font-mono">{x.best === null || x.worst === null ? 'N/A' : `${_fmtUsd(x.best)} / ${_fmtUsd(x.worst)}`}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">CVaR5%(u)</span><span className="font-mono">{x.cvar05 === null ? 'N/A' : _fmtUsd(x.cvar05)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">均值PnL%</span><span className="font-mono">{x.meanPct === null ? 'N/A' : _fmtPct(x.meanPct, 2)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">最大连亏</span><span className="font-mono">{String(x.maxLoseStreak ?? 0)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">频率(笔/天)</span><span className="font-mono">{x.tradesPerDay === null ? 'N/A' : x.tradesPerDay.toFixed(2)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-600">周期</span><span className="font-mono">{x.firstTs === null || x.lastTs === null ? 'N/A' : `${new Date(x.firstTs).toLocaleDateString()}~${new Date(x.lastTs).toLocaleDateString()}`}</span></div>
                </div>
                <div className="mt-3">
                  <div className="text-xs text-slate-600 mb-1">Top Reasons</div>
                  <div className="flex flex-wrap gap-2">
                    {x.topReasons.length ? x.topReasons.map(([r, n]) => (
                      <Badge key={r} variant="secondary">{r}:{n}</Badge>
                    )) : <Badge variant="secondary">暂无样本</Badge>}
                  </div>
                </div>
                <div className="mt-3">
                  <div className="text-xs text-slate-600 mb-1">Top Pairs</div>
                  <div className="flex flex-wrap gap-2">
                    {x.topPairs.length ? x.topPairs.map(([p, n]) => (
                      <Badge key={p} variant="secondary">{p}:{n}</Badge>
                    )) : <Badge variant="secondary">暂无样本</Badge>}
                  </div>
                </div>
                <div className="mt-3">
                  <div className="text-xs text-slate-600 mb-1">Top Pairs by PnL(u)</div>
                  <div className="flex flex-wrap gap-2">
                    {x.topPairsByPnl.length ? x.topPairsByPnl.map(([p, pnl]) => (
                      <Badge key={p} variant="secondary">{p}:{_fmtUsd(pnl, 1)}</Badge>
                    )) : <Badge variant="secondary">暂无样本</Badge>}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <CardTitle>Open Positions</CardTitle>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className="px-2 py-1">Pair</th>
                  <th className="px-2 py-1">Venue</th>
                  <th className="px-2 py-1">Side</th>
                  <th className="px-2 py-1">Owner</th>
                  <th className="px-2 py-1">Lev</th>
                  <th className="px-2 py-1">L1</th>
                  <th className="px-2 py-1">MRD</th>
                  <th className="px-2 py-1">Risk</th>
                  <th className="px-2 py-1">Value</th>
                  <th className="px-2 py-1">Notional</th>
                  <th className="px-2 py-1">Unreal PnL</th>
                  <th className="px-2 py-1">Unreal%</th>
                  <th className="px-2 py-1">PnL_eff%</th>
                  <th className="px-2 py-1">Age</th>
                  <th className="px-2 py-1">Last Sync</th>
                </tr>
              </thead>
              <tbody>
                {openPositionsRows.map((r) => (
                  <tr key={r.pair} className="border-t">
                    <td className="px-2 py-1">{r.pair}</td>
                    <td className="px-2 py-1">{r.venue ?? '-'}</td>
                    <td className="px-2 py-1">{r.side ?? '-'}</td>
                    <td className="px-2 py-1">{r.owner ?? '-'}</td>
                    <td className="px-2 py-1">{r.leverage === null ? '-' : String(r.leverage)}</td>
                    <td className="px-2 py-1">
                      {r.l1_action ? (
                        <div className="flex flex-col">
                          <span>{r.l1_action}{r.l1_ts_age_ms === null ? '' : ` (${_msToCompact(r.l1_ts_age_ms)})`}</span>
                          <span className="text-xs text-slate-500">{r.l1_reason ?? ''}</span>
                        </div>
                      ) : '-'}
                    </td>
                    <td className="px-2 py-1">
                      {r.mrd_dir ? (
                        <div className="flex flex-col">
                          <span>{r.mrd_dir}</span>
                          <span className="text-xs text-slate-500">{r.mrd_p_dir === null ? '' : _fmtPct(r.mrd_p_dir, 1)}</span>
                        </div>
                      ) : '-'}
                    </td>
                    <td className="px-2 py-1">{r.hold_risk === null ? '-' : _fmtPct(r.hold_risk, 1)}</td>
                    <td className="px-2 py-1">{r.hold_value === null ? '-' : _fmtPct(r.hold_value, 1)}</td>
                    <td className="px-2 py-1">{_fmtUsd(r.notional_usdc)}</td>
                    <td className="px-2 py-1">{r.unreal_pnl_u === null ? '-' : _fmtUsd(r.unreal_pnl_u)}</td>
                    <td className="px-2 py-1">{r.unreal_pnl_pct === null ? '-' : _fmtPct(r.unreal_pnl_pct, 2)}</td>
                    <td className="px-2 py-1">{r.pnl_eff_pct === null ? '-' : _fmtPct(r.pnl_eff_pct, 2)}</td>
                    <td className="px-2 py-1">{_msToCompact(r.age_ms)}</td>
                    <td className="px-2 py-1">{r.last_sync_age_ms === null ? '-' : _msToCompact(r.last_sync_age_ms)}</td>
                  </tr>
                ))}
                {openPositionsRows.length === 0 && (
                  <tr><td className="px-2 py-3 text-slate-500" colSpan={15}>No open positions</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <ExitMlMonitorCard
        data={exitMonitorQuery.data as ExitMlMonitorResponse | undefined}
        loading={exitMonitorQuery.isLoading}
        latestFeatures={(exitLatestFeaturesQuery.data as ExitLatestFeaturesResponse | undefined)?.items ?? []}
      />

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Exit Decisions Timeline</CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowShadowExitEvents(v => !v)}
            >
              {showShadowExitEvents ? '隐藏 Shadow' : '显示 Shadow'}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {exitEvents.slice(0, 5).map((e, i) => (
              <div key={i} className="flex items-center justify-between border rounded px-3 py-2">
                <div className="flex items-center gap-3">
                  <Badge variant="outline">{String(e.pair ?? '')}</Badge>
                  <Badge variant="outline">{String(e.side ?? '')}</Badge>
                  {(() => {
                    const rec = e as Record<string, unknown>;
                    const sysId = String(rec.system_id ?? '').trim();
                    return sysId ? <Badge variant="outline">{sysId}</Badge> : null;
                  })()}
                  {(() => {
                    const rec = e as Record<string, unknown>;
                    const owner = String(rec.exit_owner ?? '').trim();
                    return owner ? <Badge variant="outline">{owner}</Badge> : null;
                  })()}
                  {String((e as Record<string, unknown>).action ?? '') ? (
                    <Badge variant="outline">{String((e as Record<string, unknown>).action ?? '')}</Badge>
                  ) : null}
                  {(() => {
                    const rec = e as Record<string, unknown>;
                    const rf = rec.reduce_frac ?? rec.gate_reduce_frac;
                    const n = Number(rf);
                    return Number.isFinite(n) && n > 0 ? (
                      <Badge variant="outline">rf={(n as number).toFixed(2)}</Badge>
                    ) : null;
                  })()}
                  {(() => {
                    const rec = e as Record<string, unknown>;
                    const executed = Boolean(rec.executed);
                    const shadow = Boolean(rec.shadow);
                    const ok = typeof rec.ok === 'boolean' ? rec.ok : null;
                    const status = executed ? 'EXEC' : (shadow ? 'SIM' : (ok === false ? 'REJECT' : 'DEC'));
                    return <Badge variant="outline">{status}</Badge>;
                  })()}
                  <div className="flex flex-col">
                    <span className="text-slate-700">{String(e.reason ?? '')}</span>
                    {(() => {
                      const rec = e as Record<string, unknown>;
                      const err = rec.error === null || rec.error === undefined ? '' : String(rec.error);
                      const orderId = rec.order_id === null || rec.order_id === undefined ? '' : String(rec.order_id);
                      const exchangeOid = rec.exchange_oid === null || rec.exchange_oid === undefined ? '' : String(rec.exchange_oid);
                      const parts = [err ? `error=${err}` : '', orderId ? `order=${orderId}` : '', exchangeOid ? `oid=${exchangeOid}` : ''].filter(Boolean);
                      return parts.length ? <span className="text-xs text-slate-500">{parts.join(' · ')}</span> : null;
                    })()}
                  </div>
                </div>
                <div className="text-slate-500 text-sm">{_msToCompact(Math.max(0, nowMs - _toNum(e.ts, 0)))}</div>
              </div>
            ))}
            {exitEvents.length === 0 && <div className="text-slate-500 text-sm">No exit events</div>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
