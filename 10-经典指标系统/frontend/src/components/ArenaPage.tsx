import React, { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fetchArenaState, fetchArenaLayer2Status, runArenaLayer2Train, fetchRecentOrdersWithParams, fetchRecentSignalsWithParams, updateConfig, fetchExitMlMonitor, fetchTrackerGateHistory, fetchExitLatestFeatures, runExitMlTrain } from '../lib/api';
import type { ExitLatestFeaturesItem, ExitLatestFeaturesResponse, ExitMlMonitorModel, ExitMlMonitorResponse, ExitMlTrainRequest, GateHistoryItem, Order, Signal, TrackerGateHistoryResponse } from '../lib/api';
import { ArenaCard } from './ArenaCard';
import { CommitteeVoteCard } from './CommitteeVoteCard';
import { ModelsCard } from './ModelsCard';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';

const toMs = (t: number): number => {
  if (!Number.isFinite(t) || t <= 0) return 0;
  return t < 1_000_000_000_000 ? t * 1000 : t;
};

const isRecord = (v: unknown): v is Record<string, unknown> => {
  return typeof v === 'object' && v != null && !Array.isArray(v);
};

const pickSignalTsMs = (sig: Signal | null | undefined): number => {
  if (!sig) return 0;
  return toMs(Number(sig.ingested_ms ?? sig.ts_emit_ms ?? sig.ts ?? 0));
};

const normalizeModelKey = (raw: unknown) => {
  let s = String(raw ?? '');
  s = s.replace(/^online_/, '');
  s = s.replace(/\.(pkl|pth|joblib)$/i, '');
  s = s.replace(/_model$/i, '');
  if (s.startsWith('__') && s.endsWith('__') && s.length >= 4) {
    s = s.slice(2, -2);
  }
  return s.trim().toLowerCase();
};

const isRuleModelKey = (raw: unknown) => normalizeModelKey(raw) === 'rule';

const prettyModelName = (raw: unknown) => {
  let s = String(raw ?? '');
  s = s.replace(/^online_/, '');
  s = s.replace(/\.(pkl|pth|joblib)$/i, '');
  s = s.replace(/_model$/i, '');
  if (s.startsWith('__') && s.endsWith('__') && s.length >= 4) {
    s = s.slice(2, -2);
  }
  const k = s.trim().toLowerCase();
  if (k === 'nn') return 'NN';
  if (k === 'xgb') return 'XGB';
  if (k === 'lstm') return 'LSTM';
  if (k === 'rf' || k === 'randomforest') return 'RF';
  if (k === 'lr' || k === 'linearregression') return 'LR';
  if (k === 'rule') return 'RULE';
  return s;
};

const pickPositiveNumber = (...values: unknown[]): number => {
  for (const v of values) {
    const x = typeof v === 'number' ? v : Number(v ?? NaN);
    if (Number.isFinite(x) && x > 0) return x;
  }
  return NaN;
};

const extractArenaModelsFromSignal = (s: Signal): Record<string, unknown> => {
  const arenaModels = s.arena?.models;
  if (isRecord(arenaModels) && Object.keys(arenaModels).length > 0) return arenaModels;

  const ref = s.decision_info?.arena?.ref as unknown;
  if (isRecord(ref)) {
    const models = (ref as Record<string, unknown>)['models'];
    if (isRecord(models) && Object.keys(models).length > 0) return models;
    const refArena = (ref as Record<string, unknown>)['arena'];
    if (isRecord(refArena)) {
      const nested = (refArena as Record<string, unknown>)['models'];
      if (isRecord(nested) && Object.keys(nested).length > 0) return nested;
    }
  }

  const decisionArena = s.decision_info?.arena as unknown;
  if (isRecord(decisionArena)) {
    const models = (decisionArena as Record<string, unknown>)['models'];
    if (isRecord(models) && Object.keys(models).length > 0) return models;
  }

  return {};
};

const extractGateVoteCounts = (s: Signal): { nTake: number | null; nTotal: number | null } => {
  const arena = s.decision_info?.arena as unknown as Record<string, unknown> | undefined;
  const gate = isRecord(arena) ? (arena['gate'] as unknown) : undefined;
  const agg = isRecord(arena) ? (arena['agg'] as unknown) : undefined;

  const nTake = Number.isFinite(Number((gate as Record<string, unknown> | undefined)?.['n_take'] ?? NaN))
    ? Number((gate as Record<string, unknown>)['n_take'])
    : Number.isFinite(Number((agg as Record<string, unknown> | undefined)?.['n_take'] ?? NaN))
      ? Number((agg as Record<string, unknown>)['n_take'])
      : null;

  const nTotal = Number.isFinite(Number((gate as Record<string, unknown> | undefined)?.['n_models_considered'] ?? NaN))
    ? Number((gate as Record<string, unknown>)['n_models_considered'])
    : Number.isFinite(Number((gate as Record<string, unknown> | undefined)?.['n_models'] ?? NaN))
      ? Number((gate as Record<string, unknown>)['n_models'])
      : Number.isFinite(Number((agg as Record<string, unknown> | undefined)?.['n_models'] ?? NaN))
        ? Number((agg as Record<string, unknown>)['n_models'])
        : null;

  return { nTake, nTotal };
};

const ExitModelMonitorCard: React.FC<{
  data?: ExitMlMonitorResponse | null;
  loading: boolean;
  gateHistory?: GateHistoryItem[];
  latestFeatures?: ExitLatestFeaturesItem[];
}> = ({ data, loading, gateHistory, latestFeatures }) => {
  const models = (data?.models ?? {}) as Record<string, ExitMlMonitorModel>;
  const tail = models['tail'];
  const move = models['move'];
  const gate = models['gate'];
  const feedback = models['feedback'];

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

  const dataField = (m: ExitMlMonitorModel | undefined, key: string) => {
    const rec = (m ?? {}) as unknown as Record<string, unknown>;
    const data = (rec['data'] ?? {}) as Record<string, unknown>;
    const v = data[key];
    if (v == null) return '-';
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '-';
    return String(v);
  };

  const fmtCompact = (v: unknown, digits: number = 4) => {
    const x = typeof v === 'number' ? v : Number(v ?? NaN);
    if (!Number.isFinite(x)) return '-';
    return x.toFixed(digits);
  };

  const fmtAge = (v: unknown) => {
    const x = typeof v === 'number' ? v : Number(v ?? NaN);
    if (!Number.isFinite(x) || x < 0) return '-';
    if (x >= 3600) return `${(x / 3600).toFixed(1)}h`;
    if (x >= 60) return `${(x / 60).toFixed(1)}m`;
    return `${Math.round(x)}s`;
  };

  const renderKvTable = (rows: { k: string; v: React.ReactNode }[]) => {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <tbody>
            {rows.map((r) => (
              <tr key={r.k} className="border-t first:border-t-0">
                <td className="py-1 pr-3 text-slate-500 whitespace-nowrap">{r.k}</td>
                <td className="py-1 text-slate-900">{r.v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderGateHistoryTable = (items: GateHistoryItem[]) => {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left">
          <thead className="text-[11px] text-slate-500 uppercase bg-slate-50/50">
            <tr>
              <th className="px-2 py-2">Time</th>
              <th className="px-2 py-2">Owner</th>
              <th className="px-2 py-2">Pair</th>
              <th className="px-2 py-2">Side</th>
              <th className="px-2 py-2">Action</th>
              <th className="px-2 py-2">Reason</th>
              <th className="px-2 py-2">Shadow</th>
              <th className="px-2 py-2">Exec</th>
              <th className="px-2 py-2">OK</th>
              <th className="px-2 py-2">Gate</th>
              <th className="px-2 py-2">Min</th>
              <th className="px-2 py-2">Src</th>
              <th className="px-2 py-2">Take</th>
              <th className="px-2 py-2">conf</th>
              <th className="px-2 py-2">hold</th>
              <th className="px-2 py-2">close_thr</th>
              <th className="px-2 py-2">reduce_thr</th>
              <th className="px-2 py-2">L1Δ</th>
              <th className="px-2 py-2">p_tail</th>
              <th className="px-2 py-2">p_move</th>
              <th className="px-2 py-2">pnl%</th>
              <th className="px-2 py-2">pnl_u</th>
              <th className="px-2 py-2">dd</th>
              <th className="px-2 py-2">Age</th>
              <th className="px-2 py-2">Obs</th>
              <th className="px-2 py-2">Evt</th>
              <th className="px-2 py-2">Err</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr className="border-t">
                <td className="px-2 py-3 text-slate-500" colSpan={27}>
                  No gate history yet
                </td>
              </tr>
            ) : (
              items.map((it, i) => (
                <tr key={i} className="border-t">
                  <td className="px-2 py-2 text-slate-700 whitespace-nowrap">{fmtTs(Number(it.ts))}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it['exit_owner'] ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it.pair ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it.side ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it['action'] ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700" title={String(it.reason ?? '')}>
                    {String(it.reason ?? '-').slice(0, 28)}
                  </td>
                  <td className="px-2 py-2 text-slate-700">{String(it['shadow'] ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it['executed'] ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it['ok'] ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['gate_conf'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['gate_min_conf'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it['gate_src'] ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it['take_action'] ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['model_conf'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['hold_risk'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['close_thr'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['reduce_thr'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['exit_l1_thr_delta'], 4)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['p_tail'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['p_move'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['pnl_pct'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['pnl_u'], 2)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it['dd'], 3)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtAge(it['pos_age_s'])}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it['observe_event_id'] ?? '-').slice(0, 8)}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it['event_id'] ?? '-').slice(0, 8)}</td>
                  <td className="px-2 py-2 text-slate-700" title={String(it['error'] ?? '')}>
                    {String(it['error'] ?? '-').slice(0, 14)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    );
  };

  const renderLatestFeaturesTable = (items: ExitLatestFeaturesItem[]) => {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left">
          <thead className="text-[11px] text-slate-500 uppercase bg-slate-50/50">
            <tr>
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
            {items.length === 0 ? (
              <tr className="border-t">
                <td className="px-2 py-3 text-slate-500" colSpan={7}>
                  No open positions / no latest features
                </td>
              </tr>
            ) : (
              items.map((it, i) => (
                <tr key={i} className="border-t">
                  <td className="px-2 py-2 text-slate-700 whitespace-nowrap">{fmtTs(Number(it.ts))}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it.pair)}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it.side ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{String(it.exit_owner ?? '-')}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it.hold_risk, 4)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact(it.hold_value, 4)}</td>
                  <td className="px-2 py-2 text-slate-700">{fmtCompact((it.features as Record<string, unknown>)?.['model_conf'], 3)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    );
  };

  const renderPlot = (opts: {
    title: string;
    b64?: string;
    data?: Record<string, number>[];
    xKey: string;
    yKey: string;
  }) => {
    if (opts.b64) {
      return (
        <div className="border border-slate-200 rounded overflow-hidden">
          <img src={`data:image/png;base64,${opts.b64}`} alt={opts.title} className="w-full" />
        </div>
      );
    }

    const rows = Array.isArray(opts.data) ? opts.data : [];
    if (rows.length >= 2) {
      return (
        <div className="h-[180px] border border-slate-200 rounded bg-white p-2">
          <div className="text-[11px] text-slate-500 mb-1">{opts.title}</div>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey={opts.xKey} domain={[0, 1]} type="number" tick={{ fontSize: 10 }} />
              <YAxis domain={[0, 1]} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Line type="monotone" dataKey={opts.yKey} stroke="#f58518" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      );
    }

    return (
      <div className="h-[180px] border border-slate-200 rounded bg-slate-50 flex items-center justify-center text-xs text-slate-500">
        {opts.title}: no chart
      </div>
    );
  };

  const renderModelBlock = (title: string, m: ExitMlMonitorModel | undefined) => {
    const loaded = Boolean(m?.loaded);
    const rec = (m ?? {}) as unknown as Record<string, unknown>;
    const err = String(rec['error'] ?? '');
    const fileExists = Boolean(rec['file_exists']);
    return (
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-semibold text-slate-900">{title}</div>
            <div className="text-xs text-slate-500">{loaded ? 'loaded' : 'not loaded'} · {fmtTs(m?.ts)}</div>
          </div>
          <div className="text-right text-xs text-slate-600">
            <div>AUC {metricNum(m, 'auc', 3)}</div>
            <div>PR {metricNum(m, 'pr_auc', 3)}</div>
            <div>ECE {metricNum(m, 'ece', 3)}</div>
            <div>Brier {metricNum(m, 'brier', 4)}</div>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {renderPlot({
            title: `${title} ROC`,
            b64: m?.charts?.roc_curve_png_base64,
            data: (m?.charts?.roc_points as unknown as Record<string, number>[] | undefined) ?? undefined,
            xKey: 'fpr',
            yKey: 'tpr',
          })}
          {renderPlot({
            title: `${title} PR`,
            b64: m?.charts?.pr_curve_png_base64,
            data: (m?.charts?.pr_points as unknown as Record<string, number>[] | undefined) ?? undefined,
            xKey: 'recall',
            yKey: 'precision',
          })}
          {renderPlot({
            title: `${title} Calibration`,
            b64: m?.charts?.calibration_curve_png_base64,
            data: (m?.charts?.calibration_points as unknown as Record<string, number>[] | undefined) ?? undefined,
            xKey: 'prob',
            yKey: 'actual',
          })}
        </div>

        {renderKvTable([
          { k: 'loaded', v: loaded ? 'true' : 'false' },
          { k: 'file_exists', v: fileExists ? 'true' : 'false' },
          { k: 'error', v: err || '-' },
          { k: 'built_n', v: builtField(m, 'n') },
          { k: 'gate_history_actions', v: dataField(m, 'gate_history_actions') },
          { k: 'gate_history_total', v: dataField(m, 'gate_history_total') },
        ])}

        {title === 'gate' && Array.isArray(gateHistory) && (
            <div className="space-y-2">
              <div className="text-xs text-slate-700 font-semibold">Recent gate actions</div>
              {(() => {
                const xs = gateHistory.slice(0, 200);
                const l1 = xs.filter((x) => String(x['exit_owner'] ?? '') === 'l1' || x['gate_conf'] != null || x['gate_src'] != null || x['take_action'] != null);
                const filtered = xs.filter((x) => x['gate_conf'] != null || x['gate_src'] != null || x['take_action'] != null || x['action'] != null || x['shadow'] != null);
                const show = (l1.length > 0 ? l1 : filtered.length > 0 ? filtered : xs).slice(0, 12);
                return renderGateHistoryTable(show);
              })()}
            </div>
        )}

        {title === 'feedback' && Array.isArray(latestFeatures) && (
          <div className="space-y-2">
            <div className="text-xs text-slate-700 font-semibold">Latest feedback inputs</div>
            {renderLatestFeaturesTable(latestFeatures.slice(0, 12))}
          </div>
        )}
      </div>
    );
  };

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>Exit ML Monitor</CardTitle>
      </CardHeader>
      <CardContent>
        {loading && (
          <div className="border border-slate-200 bg-slate-50 text-slate-900 rounded px-4 py-3 text-sm">Loading exit charts...</div>
        )}
        {!loading && (!data || !data.ok) && (
          <div className="border border-rose-200 bg-rose-50 text-rose-900 rounded px-4 py-3 text-sm">Exit monitor API unavailable</div>
        )}
        {!loading && data && data.ok && (
          <div className="space-y-6">
            <div className="space-y-4">
              <div className="text-sm text-slate-700 font-semibold">Decision (sequence) · tail / move</div>
              {renderModelBlock('tail', tail)}
              {renderModelBlock('move', move)}
            </div>
            <div className="space-y-4">
              <div className="text-sm text-slate-700 font-semibold">Gate (meta-labeling)</div>
              {renderModelBlock('gate', gate)}
            </div>
            <div className="space-y-4">
              <div className="text-sm text-slate-700 font-semibold">Feedback (calibration)</div>
              {renderModelBlock('feedback', feedback)}
            </div>
            <div className="space-y-3">
              <div className="text-sm text-slate-700 font-semibold">Open positions (latest features)</div>
              {renderLatestFeaturesTable(Array.isArray(latestFeatures) ? latestFeatures : [])}
            </div>
            <div className="space-y-3">
              <div className="text-sm text-slate-700 font-semibold">Exit gate history</div>
              {renderGateHistoryTable(Array.isArray(gateHistory) ? gateHistory : [])}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export const ArenaPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<'entry' | 'exit'>('entry');
  const arenaQuery = useQuery({
    queryKey: ['arena', 'state', mode],
    queryFn: () => fetchArenaState(mode),
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const arenaState = arenaQuery.data;

  const { data: recentOrders } = useQuery({
    queryKey: ['orders', 'recent'],
    queryFn: () => fetchRecentOrdersWithParams({ ab_owner: 'strategy', book_id: 'strategy' }),
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
    enabled: mode === 'entry',
  });

  const { data: recentSignals } = useQuery({
    queryKey: ['signals', 'recent'],
    queryFn: () =>
      fetchRecentSignalsWithParams({
        require_bar_closed: 0,
        no_default_filter: 1,
        diverse: 0,
        per_pair: 3,
        scan_limit: 20000,
        include_stale: 0,
        include_shadow: 0,
        ab_owner: 'strategy',
        book_id: 'strategy',
      }),
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
    enabled: mode === 'entry',
  });

  const latestOrderWithCommittee = useMemo(() => {
    if (!recentOrders || !Array.isArray(recentOrders)) return null;
    return recentOrders.find((o: Order) => o.committee && Object.keys(o.committee).length > 0);
  }, [recentOrders]);

  const { data: layer2State } = useQuery({
    queryKey: ['arena', 'layer2', mode],
    queryFn: () => fetchArenaLayer2Status(mode),
    refetchInterval: 5000,
    enabled: mode === 'entry' && Boolean(arenaState?.ok && arenaState?.enabled),
  });

  const exitMonitorQuery = useQuery({
    queryKey: ['exit', 'ml', 'monitor'],
    queryFn: () => fetchExitMlMonitor({ include_charts: true, auto_eval: true, limit: 200 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: mode === 'exit',
  });

  const gateHistoryQuery = useQuery({
    queryKey: ['tracker', 'gate_history', 'exit'],
    queryFn: () => fetchTrackerGateHistory({ limit: 200 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: mode === 'exit',
  });

  const exitLatestFeaturesQuery = useQuery({
    queryKey: ['exit', 'latest_features'],
    queryFn: () => fetchExitLatestFeatures({ include_macro: false }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: mode === 'exit',
  });

  const exitTrainMutation = useMutation({
    mutationFn: (req: ExitMlTrainRequest) => runExitMlTrain(req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exit', 'ml', 'monitor'] });
      queryClient.invalidateQueries({ queryKey: ['tracker', 'gate_history', 'exit'] });
      queryClient.invalidateQueries({ queryKey: ['exit', 'latest_features'] });
    },
  });

  const trainMutation = useMutation({
    mutationFn: (force: boolean) => runArenaLayer2Train(force, mode),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['arena', 'layer2'] });
    },
  });

  const setArenaEnabledMutation = useMutation({
    mutationFn: (enabled: boolean) => updateConfig({ arena_enabled: enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['arena'] });
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['signals'] });
    },
  });

  const loadedOk = Boolean(arenaState?.ok);
  const enabled = Boolean(loadedOk && arenaState?.enabled);
  const models = useMemo(() => arenaState?.models ?? [], [arenaState]);
  const l2Enabled = Boolean(layer2State?.layer2_enabled);
  const l2Stats = layer2State?.state;
  const calibRows = useMemo(() => {
    const rows: Array<{ mid: string; method?: unknown; ts?: unknown; metrics: Record<string, unknown> }> = [];
    const rawCalib = layer2State?.model_calib;

    if (isRecord(rawCalib)) {
      for (const [mid, item] of Object.entries(rawCalib)) {
        if (!isRecord(item)) continue;
        const metrics = isRecord(item.metrics) ? item.metrics : {};
        rows.push({
          mid,
          method: item.method,
          ts: item.ts,
          metrics,
        });
      }
    }

    if (rows.length > 0) return rows;

    const updated = isRecord(l2Stats?.updated) ? l2Stats.updated : {};
    for (const [mid, item] of Object.entries(updated)) {
      if (!isRecord(item)) continue;
      rows.push({
        mid,
        method: 'layer2',
        ts: l2Stats?.last_train_ms,
        metrics: item,
      });
    }

    return rows;
  }, [layer2State?.model_calib, l2Stats]);

  const series = useMemo(() => {
    return models.map((m, idx) => ({
      key: `m${idx}`,
      id: String(m.id ?? m.name),
      name: String(m.name ?? ''),
    }));
  }, [models]);

  const equityData = useMemo(() => {
    const byTs = new Map<number, Record<string, number>>();
    for (const s of series) {
      const m = models.find((x) => String(x.id ?? x.name) === s.id);
      const eq = m?.equity ?? [];
      for (const pt of eq) {
        const ts = Number(pt.ts ?? 0);
        if (!Number.isFinite(ts) || ts <= 0) continue;
        const cur = byTs.get(ts) ?? { ts };
        cur[s.key] = Number(pt.equity_u ?? 0);
        byTs.set(ts, cur);
      }
    }
    return Array.from(byTs.values()).sort((a, b) => Number(a.ts) - Number(b.ts));
  }, [models, series]);

  const colors = ['#2563eb', '#16a34a', '#f97316', '#a855f7', '#ef4444', '#0ea5e9'];

  const fmtPct = (v: unknown, digits: number = 1) => {
    const x = typeof v === 'number' ? v : Number(v ?? NaN);
    if (!Number.isFinite(x)) return '-';
    return `${(x * 100).toFixed(digits)}%`;
  };

  const fmtNum = (v: unknown, digits: number = 4) => {
    const x = typeof v === 'number' ? v : Number(v ?? NaN);
    if (!Number.isFinite(x)) return '-';
    return x.toFixed(digits);
  };

  const fmtInt = (v: unknown) => {
    const x = typeof v === 'number' ? v : Number(v ?? NaN);
    if (!Number.isFinite(x)) return '-';
    return String(Math.trunc(x));
  };

  const signalRows = useMemo(() => {
    const sigs = (recentSignals ?? []) as Signal[];
    return sigs
      .map((s) => {
        const arena = (s.arena ?? {}) as NonNullable<Signal['arena']>;
        const decisionArena = s.decision_info?.arena as unknown;
        const gateThr =
          isRecord(decisionArena) && isRecord((decisionArena as Record<string, unknown>)['gate'])
            ? ((decisionArena as Record<string, unknown>)['gate'] as Record<string, unknown>)['threshold']
            : undefined;
        const arenaThr = pickPositiveNumber(
          arena?.threshold,
          s.decision_info?.threshold,
          gateThr,
          s.decision_info?.arena?.agg?.threshold,
        );
        const models = extractArenaModelsFromSignal(s);
        const gateCounts = extractGateVoteCounts(s);

        const entries = Object.entries(models)
          .filter(([mid]) => !isRuleModelKey(mid))
          .map(([mid, m]) => ({
            id: mid,
            name: prettyModelName(mid),
            p: Number((m as Record<string, unknown> | undefined)?.['p'] ?? 0),
            pc: Number((m as Record<string, unknown> | undefined)?.['pc'] ?? 0),
            take: (m as Record<string, unknown> | undefined)?.['take'],
            weight: Number((m as Record<string, unknown> | undefined)?.['weight'] ?? 0),
            eligible:
              (m as Record<string, unknown> | undefined)?.['eligible'] == null
                ? true
                : Boolean((m as Record<string, unknown>)['eligible']),
            voteAgree: false,
          }))
          .map((e) => {
            const pc = Number(e.pc ?? NaN);
            const eligible = Boolean(e.eligible);
            const useThr = Number.isFinite(arenaThr) && arenaThr > 0 ? arenaThr : NaN;
            const take = e.take;
            const voteAgree =
              eligible &&
              (typeof take === 'boolean'
                ? take
                : Number.isFinite(useThr)
                  ? pc >= useThr
                  : false);
            return { ...e, voteAgree };
          })
          .sort((a, b) => b.pc - a.pc);
        const agreeN = entries.filter((e) => e.eligible && e.voteAgree).length;
        const vetoN = entries.filter((e) => e.eligible && !e.voteAgree).length;
        const ineligibleN = entries.filter((e) => !e.eligible).length;
        return {
          sig: s,
          arena: {
            ...arena,
            threshold: Number.isFinite(arenaThr) && arenaThr > 0 ? arenaThr : undefined,
            chosen: arena?.chosen ?? s.decision_info?.arena?.agg?.chosen ?? null,
            explore: Boolean(arena?.explore ?? s.decision_info?.arena?.agg?.explore ?? false),
            regime: arena?.regime ?? (s.decision_info?.regime ?? s.decision_info?.arena?.agg?.regime ?? undefined),
            models: isRecord(models) && Object.keys(models).length > 0 ? (models as NonNullable<Signal['arena']>['models']) : undefined,
          },
          entries,
          agreeN,
          vetoN,
          ineligibleN,
          gateCounts,
        };
      })
      .sort((a, b) => pickSignalTsMs(b.sig) - pickSignalTsMs(a.sig));
  }, [recentSignals]);

  const latestSignalWithArenaVotes = useMemo(() => {
    for (const r of signalRows) {
      if (Array.isArray(r.entries) && r.entries.length > 0) return r;
    }
    return null;
  }, [signalRows]);

  const latestSignalCommittee = useMemo(() => {
    if (!latestSignalWithArenaVotes) return null;
    const committee: Record<string, { p: number; pc: number; vote: string }> = {};
    for (const e of latestSignalWithArenaVotes.entries ?? []) {
      committee[e.id] = {
        p: Number(e.p ?? 0),
        pc: Number(e.pc ?? 0),
        vote: e.voteAgree ? 'agree' : 'veto',
      };
    }
    return Object.keys(committee).length > 0 ? committee : null;
  }, [latestSignalWithArenaVotes]);

  const latestCommitteeSnapshot = useMemo(() => {
    const orderHasCommittee = Boolean(
      latestOrderWithCommittee?.committee && Object.keys(latestOrderWithCommittee.committee).length > 0,
    );
    const sigHasCommittee = Boolean(latestSignalCommittee && latestSignalWithArenaVotes?.sig);

    const orderTs = orderHasCommittee ? toMs(Number(latestOrderWithCommittee?.ts)) : NaN;
    const sigTs = sigHasCommittee ? pickSignalTsMs(latestSignalWithArenaVotes?.sig) : NaN;

    const useOrder =
      orderHasCommittee &&
      !sigHasCommittee;

    if (useOrder) {
      const committee0 = latestOrderWithCommittee!.committee as Record<string, { p: number; pc: number; vote: string }>;
      const entries = Object.entries(committee0);
      const nonRule = entries.filter(([k]) => !isRuleModelKey(k));
      const committee = Object.fromEntries((nonRule.length > 0 ? nonRule : entries)) as Record<string, { p: number; pc: number; vote: string }>;
      return {
        committee,
        pair: String(latestOrderWithCommittee!.pair ?? ''),
        side: String(latestOrderWithCommittee!.side ?? ''),
        ts: Number.isFinite(orderTs) ? orderTs : 0,
      };
    }

    if (sigHasCommittee) {
      return {
        committee: latestSignalCommittee as Record<string, { p: number; pc: number; vote: string }>,
        pair: String(latestSignalWithArenaVotes!.sig?.pair ?? ''),
        side: String(latestSignalWithArenaVotes!.sig?.side ?? ''),
        ts: Number.isFinite(sigTs) ? sigTs : 0,
      };
    }

    return null;
  }, [latestOrderWithCommittee, latestSignalCommittee, latestSignalWithArenaVotes]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-2xl font-bold text-slate-900">Arena</h2>
        <div className="flex items-center gap-2">
          <Button size="sm" variant={mode === 'entry' ? 'default' : 'outline'} onClick={() => setMode('entry')}>
            Entry
          </Button>
          <Button size="sm" variant={mode === 'exit' ? 'default' : 'outline'} onClick={() => setMode('exit')}>
            Exit
          </Button>
        </div>
      </div>

      {mode === 'entry' && latestCommitteeSnapshot && (
        <CommitteeVoteCard
          committee={latestCommitteeSnapshot.committee}
          pair={latestCommitteeSnapshot.pair}
          side={latestCommitteeSnapshot.side}
          ts={latestCommitteeSnapshot.ts}
        />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {mode === 'entry' ? (
          <ModelsCard />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => exitTrainMutation.mutate({ task: 'gate', output_charts: true, save: true, limit: 2000, interval: '5m', horizon: 12 })}
                disabled={exitTrainMutation.isPending}
              >
                Train gate
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => exitTrainMutation.mutate({ task: 'feedback', output_charts: true, save: true, limit: 2000, interval: '5m', horizon: 12 })}
                disabled={exitTrainMutation.isPending}
              >
                Train feedback
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => exitTrainMutation.mutate({ task: 'tail', family: 'lr', output_charts: true, save: true, limit: 2000, interval: '5m', horizon: 12 })}
                disabled={exitTrainMutation.isPending}
              >
                Train tail
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => exitTrainMutation.mutate({ task: 'move', family: 'lr', output_charts: true, save: true, limit: 2000, interval: '5m', horizon: 12 })}
                disabled={exitTrainMutation.isPending}
              >
                Train move
              </Button>
            </div>
            <ExitModelMonitorCard
              data={exitMonitorQuery.data}
              loading={exitMonitorQuery.isLoading}
              gateHistory={(gateHistoryQuery.data as TrackerGateHistoryResponse | undefined)?.history ?? []}
              latestFeatures={(exitLatestFeaturesQuery.data as ExitLatestFeaturesResponse | undefined)?.items ?? []}
            />
          </div>
        )}
        <ArenaCard mode={mode} />
      </div>

      {arenaQuery.isLoading && (
        <div className="border border-slate-200 bg-slate-50 text-slate-900 rounded px-4 py-3 text-sm">
          Loading arena...
        </div>
      )}

      {!arenaQuery.isLoading && arenaState && !arenaState.ok && (
        <div className="border border-rose-200 bg-rose-50 text-rose-900 rounded px-4 py-3 text-sm">
          Arena API unavailable
        </div>
      )}

      {!arenaQuery.isLoading && loadedOk && !enabled && (
        <div className="border border-amber-200 bg-amber-50 text-amber-900 rounded px-4 py-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <div>Arena disabled</div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setArenaEnabledMutation.mutate(true)}
              disabled={setArenaEnabledMutation.isPending}
            >
              Enable
            </Button>
          </div>
        </div>
      )}

      {mode === 'entry' && enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Equity Curves</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={equityData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis
                    dataKey="ts"
                    tickFormatter={(v) => new Date(Number(v)).toLocaleTimeString()}
                    stroke="#64748b"
                    fontSize={12}
                  />
                  <YAxis stroke="#64748b" fontSize={12} />
                  <Tooltip
                    labelFormatter={(v) => new Date(Number(v)).toLocaleString()}
                    formatter={(v: unknown) => [Number(v ?? 0).toFixed(2), 'equity_u']}
                  />
                  {series.map((s, idx) => (
                    <Line
                      key={s.key}
                      type="monotone"
                      dataKey={s.key}
                      name={s.name}
                      dot={false}
                      strokeWidth={2}
                      stroke={colors[idx % colors.length]}
                      isAnimationActive={false}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {mode === 'entry' && enabled && (
        <Card>
          <CardHeader>
            <CardTitle>Ledger</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-500 uppercase bg-gray-50/50">
                  <tr>
                    <th className="px-3 py-2">Model</th>
                    <th className="px-3 py-2">Weight</th>
                    <th className="px-3 py-2">Capital</th>
                    <th className="px-3 py-2">WinRate</th>
                    <th className="px-3 py-2">Logloss</th>
                    <th className="px-3 py-2">MaxDD</th>
                    <th className="px-3 py-2">Turnover</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {models.map((m) => (
                    <tr key={m.id ?? m.name} className="hover:bg-slate-50/50">
                      <td className="px-3 py-2 font-medium text-gray-900 truncate max-w-[240px]" title={m.name}>
                        {m.name}
                      </td>
                      <td className="px-3 py-2 text-gray-700">{Number(m.weight ?? 0).toFixed(4)}</td>
                      <td className="px-3 py-2 text-gray-700">{Number(m.capital_u ?? 0).toFixed(2)}u</td>
                      <td className="px-3 py-2 text-gray-700">{(Number(m.win_rate ?? 0) * 100).toFixed(1)}%</td>
                      <td className="px-3 py-2 text-gray-700">{Number(m.avg_logloss ?? 0).toFixed(4)}</td>
                      <td className="px-3 py-2 text-gray-700">{(Number(m.max_dd ?? 0) * 100).toFixed(1)}%</td>
                      <td className="px-3 py-2 text-gray-700">{(Number(m.turnover ?? 0) * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                  {models.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-3 py-6 text-center text-gray-500">
                        No arena models
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {mode === 'entry' && enabled && l2Enabled && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Layer 2 Calibration</CardTitle>
            <div className="flex gap-2">
              <Button 
                variant="outline" 
                size="sm"
                onClick={() => trainMutation.mutate(true)}
                disabled={trainMutation.isPending}
              >
                {trainMutation.isPending ? 'Training...' : 'Force Train'}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="mb-4 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div className="bg-slate-50 p-3 rounded">
                <div className="text-gray-500">Last Train</div>
                <div className="font-mono">{l2Stats?.last_train_ms ? new Date(l2Stats.last_train_ms).toLocaleString() : '-'}</div>
              </div>
              <div className="bg-slate-50 p-3 rounded">
                <div className="text-gray-500">Attrib Samples</div>
                <div className="font-mono">{l2Stats?.attrib_count ?? 0}</div>
              </div>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-500 uppercase bg-gray-50/50">
                  <tr>
                    <th className="px-3 py-2">Model</th>
                    <th className="px-3 py-2">Method</th>
                    <th className="px-3 py-2">Update TS</th>
                    <th className="px-3 py-2">OOS Base MSE</th>
                    <th className="px-3 py-2">OOS New MSE</th>
                    <th className="px-3 py-2">Improvement</th>
                    <th className="px-3 py-2">OOS Used</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {calibRows.map(({ mid, method, ts, metrics }) => {
                    const oosMseBase = metrics['oos_mse_base'];
                    const oosMse = metrics['oos_mse'];
                    const improve = metrics['improve'];
                    const oosUsed = metrics['oos_used'];

                    const improveScaled = Number(improve ?? NaN) * 1000;
                    const improveText = fmtNum(improveScaled, 4);

                    return (
                      <tr key={mid} className="hover:bg-slate-50/50">
                        <td className="px-3 py-2 font-medium">{mid}</td>
                        <td className="px-3 py-2">{String(method ?? '') || '-'}</td>
                        <td className="px-3 py-2 text-gray-500">
                          {Number.isFinite(Number(ts ?? NaN)) && Number(ts ?? 0) > 0 ? new Date(Number(ts)).toLocaleTimeString() : '-'}
                        </td>
                        <td className="px-3 py-2 text-gray-700">{fmtNum(oosMseBase, 6)}</td>
                        <td className="px-3 py-2 text-gray-700">{fmtNum(oosMse, 6)}</td>
                        <td className="px-3 py-2 font-bold text-green-600">{improveText === '-' ? '-' : `${improveText}e-3`}</td>
                        <td className="px-3 py-2">{fmtInt(oosUsed)}</td>
                      </tr>
                    );
                  })}
                  {calibRows.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-3 py-6 text-center text-gray-500">
                        No calibration data yet
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {mode === 'entry' && (
        <Card>
          <CardHeader>
            <CardTitle>Signal Votes</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-500 uppercase bg-gray-50/50">
                  <tr>
                    <th className="px-3 py-2">Time</th>
                    <th className="px-3 py-2">Strategy</th>
                    <th className="px-3 py-2">Pair</th>
                    <th className="px-3 py-2">Side</th>
                    <th className="px-3 py-2">Thr</th>
                    <th className="px-3 py-2">Chosen</th>
                    <th className="px-3 py-2">Votes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {signalRows.map(({ sig, arena, entries, agreeN, vetoN, ineligibleN, gateCounts }) => (
                    <tr key={sig.id} className="align-top hover:bg-slate-50/50">
                      <td className="px-3 py-2 text-gray-600 whitespace-nowrap">
                        {pickSignalTsMs(sig) ? new Date(pickSignalTsMs(sig)).toLocaleTimeString() : '-'}
                      </td>
                      <td className="px-3 py-2 text-gray-900 whitespace-nowrap">
                        {sig.strategy_id ?? '-'}
                      </td>
                      <td className="px-3 py-2 font-medium text-gray-900 whitespace-nowrap">
                        {sig.pair}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <span className={sig.side === 'long' ? 'text-green-700 font-semibold' : 'text-red-700 font-semibold'}>
                          {sig.side?.toUpperCase?.() ?? String(sig.side ?? '')}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-gray-700 whitespace-nowrap">
                        {arena?.threshold == null ? '-' : fmtNum(arena.threshold, 3)}
                      </td>
                      <td className="px-3 py-2 text-gray-700 whitespace-nowrap">
                        {arena?.chosen ?? '-'}
                        {arena?.explore ? <span className="ml-2 text-xs text-amber-700">explore</span> : null}
                      </td>
                      <td className="px-3 py-2">
                        {entries.length === 0 ? (
                          <div className="text-gray-500">No arena votes</div>
                        ) : (
                          <details>
                            <summary className="cursor-pointer select-none text-gray-700">
                              <span className="text-green-700 font-semibold">赞成 {agreeN}</span>
                              <span className="mx-2 text-gray-400">/</span>
                              <span className="text-red-700 font-semibold">否定 {vetoN}</span>
                              {ineligibleN > 0 ? (
                                <>
                                  <span className="mx-2 text-gray-400">/</span>
                                  <span className="text-gray-500 font-semibold">不合格 {ineligibleN}</span>
                                </>
                              ) : null}
                              {gateCounts?.nTake != null && gateCounts?.nTotal != null ? (
                                <>
                                  <span className="mx-2 text-gray-400">/</span>
                                  <span className="text-slate-600 font-semibold">
                                    take {Math.trunc(gateCounts.nTake)}/{Math.trunc(gateCounts.nTotal)}
                                  </span>
                                </>
                              ) : null}
                              {arena?.regime ? <span className="ml-2 text-xs text-gray-500">{arena.regime}</span> : null}
                            </summary>
                            <div className="mt-2 border border-slate-200 rounded-md overflow-hidden">
                              <table className="w-full text-xs">
                                <thead className="bg-slate-50 text-gray-500">
                                  <tr>
                                    <th className="text-left px-2 py-2">Model</th>
                                    <th className="text-right px-2 py-2">pc</th>
                                    <th className="text-right px-2 py-2">p</th>
                                    <th className="text-right px-2 py-2">Vote</th>
                                    <th className="text-right px-2 py-2">Weight</th>
                                    <th className="text-right px-2 py-2">Eligible</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-100">
                                  {entries.map((e) => (
                                    <tr key={e.id}>
                                      <td className="px-2 py-2 font-mono text-gray-800 whitespace-nowrap" title={e.id}>{e.name}</td>
                                      <td className="px-2 py-2 text-right text-gray-800">{fmtPct(e.pc, 1)}</td>
                                      <td className="px-2 py-2 text-right text-gray-800">{fmtPct(e.p, 1)}</td>
                                      <td className="px-2 py-2 text-right">
                                        {!e.eligible ? (
                                          <span className="text-gray-600 font-semibold">不合格</span>
                                        ) : e.voteAgree ? (
                                          <span className="text-green-700 font-semibold">赞成</span>
                                        ) : (
                                          <span className="text-red-700 font-semibold">否定</span>
                                        )}
                                      </td>
                                      <td className="px-2 py-2 text-right text-gray-700">{fmtNum(e.weight, 3)}</td>
                                      <td className="px-2 py-2 text-right text-gray-700">{e.eligible ? 'Y' : 'N'}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </details>
                        )}
                      </td>
                    </tr>
                  ))}
                  {signalRows.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-3 py-6 text-center text-gray-500">
                        No signals
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
