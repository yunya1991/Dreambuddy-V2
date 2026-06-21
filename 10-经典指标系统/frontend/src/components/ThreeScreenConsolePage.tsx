import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Link } from 'react-router-dom';
import { fetchAuditExecutionQuality, fetchConfig, fetchDiagnosticsGateState, fetchRecentOrdersWithParams, fetchRecentSignalsWithParams, fetchSignalRejectStats, fetchThreeScreen5mSignal, fetchThreeScreenBackfillStatus, fetchThreeScreenDailySignal, fetchThreeScreenDailyWfoSummary, fetchThreeScreenWeeklyStatus, postConfigLiveDisable, postConfigLiveEnable, postThreeScreenBackfill, updateConfig } from '../lib/api';
import type { FetchRecentSignalsParams } from '../lib/api';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { OrdersTable } from './OrdersTable';
import { SignalsTable } from './SignalsTable';

function _toMs(t: unknown): number {
  const x = Number(t);
  if (!Number.isFinite(x) || x <= 0) return 0;
  return x < 1_000_000_000_000 ? x * 1000 : x;
}

function _fmtAge(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '-';
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h`;
  return `${Math.floor(ms / 86_400_000)}d`;
}

function _badgeForAge(ageMs: number, staleMs: number): { label: string; variant: 'default' | 'secondary' | 'destructive' | 'outline' } {
  if (!Number.isFinite(ageMs) || ageMs < 0) return { label: 'unknown', variant: 'outline' };
  if (ageMs <= staleMs) return { label: 'fresh', variant: 'default' };
  if (ageMs <= staleMs * 2) return { label: 'stale', variant: 'secondary' };
  return { label: 'very stale', variant: 'destructive' };
}

type SeriesPoint = {
  ts_ms: number;
  p_enter: number | null;
  threshold: number | null;
  executed: number | null;
};

export const ThreeScreenConsolePage: React.FC = () => {
  const qc = useQueryClient();

  const [pair, setPair] = useState<string>('BTC');
  const [groupId, setGroupId] = useState<string>('ts_v1');
  const [groupTouched, setGroupTouched] = useState<boolean>(false);
  const [windowH, setWindowH] = useState<number>(24);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);
  const [viewMode, setViewMode] = useState<'auto' | 'phase0' | 'phase1'>('auto');
  const [includeShadow, setIncludeShadow] = useState<boolean>(true);
  const [includeStale, setIncludeStale] = useState<boolean>(true);
  const [confirmLive, setConfirmLive] = useState<boolean>(false);
  const [useMlVote, setUseMlVote] = useState<boolean>(false);
  const [mlVoteTouched, setMlVoteTouched] = useState<boolean>(false);
  const [autoTrigger5m, setAutoTrigger5m] = useState<boolean>(false);
  const [autoTriggerTouched, setAutoTriggerTouched] = useState<boolean>(false);
  const [forceRequireConfirm, setForceRequireConfirm] = useState<boolean>(true);
  const [forceRequireConfirmTouched, setForceRequireConfirmTouched] = useState<boolean>(false);
  const [backfillDays, setBackfillDays] = useState<string>('900');
  const [backfillJobId, setBackfillJobId] = useState<string | null>(null);
  const windowMs = useMemo(() => Math.max(1, Math.min(168, Math.floor(windowH))) * 3_600_000, [windowH]);

  const { data: config } = useQuery({
    queryKey: ['config', 'get'],
    queryFn: fetchConfig,
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { abOwner: abOwnerCfg, bookId: bookIdCfg, phase: phaseCfg } = useMemo(() => {
    const cfg = (config && typeof config === 'object') ? (config as unknown as Record<string, unknown>) : null;
    const phaseRaw = cfg ? Number(cfg.three_screen_phase ?? 0) : 0;
    const phase0ForceRaw = cfg ? cfg.three_screen_phase0_force_ab_owner_strategy : undefined;
    const phase0Force = typeof phase0ForceRaw === 'boolean' ? phase0ForceRaw : true;
    const phaseN = Number.isFinite(phaseRaw) ? Math.max(0, Math.min(9, Math.floor(phaseRaw))) : 0;
    const expectedBook = (phaseN === 0 && phase0Force) ? 'strategy' : 'three_screen';
    return { abOwner: expectedBook, bookId: expectedBook, phase: phaseN };
  }, [config]);

  const { abOwner, bookId, phase } = useMemo(() => {
    if (viewMode === 'phase0') return { abOwner: 'strategy', bookId: 'strategy', phase: 0 };
    if (viewMode === 'phase1') return { abOwner: 'three_screen', bookId: 'three_screen', phase: 1 };
    return { abOwner: abOwnerCfg, bookId: bookIdCfg, phase: phaseCfg };
  }, [abOwnerCfg, bookIdCfg, phaseCfg, viewMode]);

  useEffect(() => {
    if (!config || typeof config !== 'object') return;
    const cfg = config as unknown as Record<string, unknown>;
    const schedule = (fn: () => void) => {
      try {
        queueMicrotask(fn);
      } catch {
        window.setTimeout(fn, 0);
      }
    };
    const gid0 = String(cfg.three_screen_group_id_default ?? '').trim();
    if (!groupTouched && gid0 && (groupId === 'ts_v1' || !String(groupId ?? '').trim())) {
      schedule(() => setGroupId(gid0));
    }
    const mv0 = cfg.three_screen_use_ml_vote;
    if (!mlVoteTouched && typeof mv0 === 'boolean') {
      schedule(() => setUseMlVote(Boolean(mv0)));
    }
    const at0 = cfg.three_screen_5m_autotrigger_enabled;
    if (!autoTriggerTouched && typeof at0 === 'boolean') {
      schedule(() => setAutoTrigger5m(Boolean(at0)));
    }
    const fc0 = cfg.three_screen_5m_timing_force_require_confirm;
    if (!forceRequireConfirmTouched && typeof fc0 === 'boolean') {
      schedule(() => setForceRequireConfirm(Boolean(fc0)));
    }
  }, [autoTriggerTouched, config, forceRequireConfirmTouched, groupId, groupTouched, mlVoteTouched]);

  const weeklyParams = useMemo(() => {
    return { pair: pair || undefined, group_id: groupId || undefined, auto_compute: 1, require_bar_closed: 1 };
  }, [groupId, pair]);
  const dailyParams = useMemo(() => {
    return { pair: pair || undefined, group_id: groupId || undefined, auto_compute: 1, require_bar_closed: 1 };
  }, [groupId, pair]);
  const wfoParams = useMemo(() => {
    return { pair: pair || undefined, group_id: groupId || undefined, auto_compute: 1 };
  }, [groupId, pair]);
  const fiveMinParams = useMemo(() => {
    return { pair: pair || undefined, group_id: groupId || undefined, auto_compute: 1, require_bar_closed: 1 };
  }, [groupId, pair]);

  const pairSymbol = useMemo(() => {
    const c = String(pair ?? '').trim().toUpperCase();
    if (!c) return undefined;
    return `${c}/USDC`;
  }, [pair]);

  const { data: weeklyStatus, error: weeklyError, isFetching: weeklyFetching } = useQuery({
    queryKey: ['three_screen', 'weekly', weeklyParams],
    queryFn: () => fetchThreeScreenWeeklyStatus(weeklyParams),
    refetchInterval: autoRefresh ? 600_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: dailySignal, error: dailyError, isFetching: dailyFetching } = useQuery({
    queryKey: ['three_screen', 'daily', 'signal', dailyParams],
    queryFn: () => fetchThreeScreenDailySignal(dailyParams),
    refetchInterval: autoRefresh ? 300_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: dailyWfo, error: wfoError, isFetching: wfoFetching } = useQuery({
    queryKey: ['three_screen', 'daily', 'wfo', wfoParams],
    queryFn: () => fetchThreeScreenDailyWfoSummary(wfoParams),
    refetchInterval: autoRefresh ? 1_800_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: fiveMinSignal, error: fiveMinError, isFetching: fiveMinFetching } = useQuery({
    queryKey: ['three_screen', '5m', fiveMinParams],
    queryFn: () => fetchThreeScreen5mSignal(fiveMinParams),
    refetchInterval: autoRefresh ? 15_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: gateState, error: gateError, isFetching: gateFetching } = useQuery({
    queryKey: ['diagnostics', 'gate_state'],
    queryFn: () => fetchDiagnosticsGateState(),
    refetchInterval: autoRefresh ? 5000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const gateStateThreeScreen = useMemo(() => {
    const obj = (gateState && typeof gateState === 'object') ? (gateState as { three_screen?: unknown }).three_screen : undefined;
    return (obj && typeof obj === 'object') ? (obj as Record<string, unknown>) : null;
  }, [gateState]);

  const { data: rejectStats, error: rejectError, isFetching: rejectFetching } = useQuery({
    queryKey: ['signals', 'reject_stats', includeShadow],
    queryFn: () => fetchSignalRejectStats(2000, includeShadow),
    refetchInterval: autoRefresh ? 10_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: execQ, error: execQError, isFetching: execQFetching } = useQuery({
    queryKey: ['audit', 'execution_quality', pairSymbol, includeShadow],
    queryFn: () => fetchAuditExecutionQuality({ pair: pairSymbol, lookback_days: 7, include_shadow: includeShadow ? 1 : 0 }),
    enabled: Boolean(pairSymbol),
    refetchInterval: autoRefresh ? 60_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const poolThreeScreen = useMemo(() => {
    const meta = (config as { strategy_pool_meta?: unknown } | null | undefined)?.strategy_pool_meta;
    const obj = (meta && typeof meta === 'object') ? (meta as Record<string, unknown>) : null;
    const ts = obj?.ThreeScreen;
    return (ts && typeof ts === 'object') ? (ts as Record<string, unknown>) : null;
  }, [config]);

  const poolMaxNotional = useMemo(() => poolThreeScreen ? Number(poolThreeScreen.max_notional_usdc ?? NaN) : Number.NaN, [poolThreeScreen]);
  const poolMaxOpenTrades = useMemo(() => poolThreeScreen ? Number(poolThreeScreen.max_open_trades ?? NaN) : Number.NaN, [poolThreeScreen]);
  const [maxNotionalOverride, setMaxNotionalOverride] = useState<string | null>(null);
  const [maxOpenTradesOverride, setMaxOpenTradesOverride] = useState<string | null>(null);
  const maxNotionalText = maxNotionalOverride ?? (Number.isFinite(poolMaxNotional) ? String(poolMaxNotional) : '');
  const maxOpenTradesText = maxOpenTradesOverride ?? (Number.isFinite(poolMaxOpenTrades) ? String(poolMaxOpenTrades) : '');

  const setPoolMutation = useMutation({
    mutationFn: async () => {
      const n = Number(maxNotionalText);
      const m = Number(maxOpenTradesText);
      const meta0 = (config as { strategy_pool_meta?: unknown } | null | undefined)?.strategy_pool_meta;
      const metaObj = (meta0 && typeof meta0 === 'object') ? (meta0 as Record<string, unknown>) : {};
      const nextMeta = {
        ...metaObj,
        ThreeScreen: {
          ...(typeof metaObj.ThreeScreen === 'object' && metaObj.ThreeScreen ? (metaObj.ThreeScreen as Record<string, unknown>) : {}),
          max_notional_usdc: Number.isFinite(n) ? n : undefined,
          max_open_trades: Number.isFinite(m) ? m : undefined,
        },
      };
      return updateConfig({
        strategy_pool_meta: nextMeta,
        three_screen_use_ml_vote: useMlVote,
        three_screen_5m_autotrigger_enabled: autoTrigger5m,
        three_screen_5m_timing_force_require_confirm: forceRequireConfirm,
        three_screen_5m_venue: 'aster',
        confirm_live: confirmLive,
        trace_id: `ui_three_screen_${Date.now()}`,
      } as unknown as Record<string, unknown>);
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['config', 'get'] });
    },
  });

  const liveEnableMutation = useMutation({
    mutationFn: async () => postConfigLiveEnable({ confirm_live: confirmLive, confirm_execute: true, trace_id: `ui_three_screen_live_enable_${Date.now()}` }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['config', 'get'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', 'weekly'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', 'daily'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', '5m'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', 'signals'] });
    },
  });

  const liveDisableMutation = useMutation({
    mutationFn: async () => postConfigLiveDisable({ confirm_live: confirmLive, confirm_execute: true, trace_id: `ui_three_screen_live_disable_${Date.now()}` }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['config', 'get'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', 'weekly'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', 'daily'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', '5m'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', 'signals'] });
    },
  });

  const backfillMutation = useMutation({
    mutationFn: async () => {
      const raw = Number(backfillDays);
      const d = Number.isFinite(raw) ? Math.max(30, Math.min(3650, Math.floor(raw))) : 200;
      return postThreeScreenBackfill({ coin: pair || undefined, group_id: groupId || undefined, lookback_days: d });
    },
    onSuccess: async (resp) => {
      const jid = String((resp as { job_id?: unknown } | null | undefined)?.job_id ?? '').trim();
      if (jid) {
        setBackfillJobId(jid);
        return;
      }
      await qc.invalidateQueries({ queryKey: ['three_screen', 'weekly'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', 'daily'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', '5m'] });
    },
  });

  const { data: backfillStatusResp } = useQuery({
    queryKey: ['three_screen', 'backfill', 'status', backfillJobId],
    queryFn: () => fetchThreeScreenBackfillStatus({ job_id: String(backfillJobId) }),
    enabled: Boolean(backfillJobId),
    refetchInterval: (q) => {
      const d = q.state.data as { ok?: unknown; job?: unknown } | undefined;
      const job = (d && typeof d === 'object') ? (d as { job?: unknown }).job : undefined;
      const obj = (job && typeof job === 'object') ? (job as Record<string, unknown>) : null;
      const st = String(obj?.status ?? '').trim();
      if (!st || st === 'queued' || st === 'running') return 2000;
      return false;
    },
    refetchOnWindowFocus: false,
    retry: false,
  });

  const backfillJob = useMemo(() => {
    const job = (backfillStatusResp && typeof backfillStatusResp === 'object') ? (backfillStatusResp as { job?: unknown }).job : undefined;
    return (job && typeof job === 'object') ? (job as Record<string, unknown>) : null;
  }, [backfillStatusResp]);

  useEffect(() => {
    if (!backfillJobId || !backfillJob) return;
    const st = String(backfillJob.status ?? '').trim();
    if (st !== 'done' && st !== 'error') return;
    const done = st === 'done';
    const refresh = async () => {
      await qc.invalidateQueries({ queryKey: ['three_screen', 'weekly'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', 'daily'] });
      await qc.invalidateQueries({ queryKey: ['three_screen', '5m'] });
    };
    void refresh();
    const id = window.setTimeout(() => {
      setBackfillJobId(null);
    }, done ? 8000 : 12000);
    return () => window.clearTimeout(id);
  }, [backfillJob, backfillJobId, qc]);

  const signalsParams = useMemo((): FetchRecentSignalsParams => {
    return {
      limit: 200,
      strategy_id: 'ThreeScreen',
      pair: pairSymbol,
      ab_owner: abOwner,
      book_id: bookId,
      group_id: groupId || undefined,
      include_shadow: includeShadow ? 1 : 0,
      include_stale: includeStale ? 1 : 0,
      require_bar_closed: 1,
    };
  }, [abOwner, bookId, groupId, includeShadow, includeStale, pairSymbol]);

  const { data: signals, dataUpdatedAt: signalsUpdatedAt, isFetching: signalsFetching } = useQuery({
    queryKey: ['three_screen', 'signals', phase, abOwner, bookId, groupId, pairSymbol, includeShadow, includeStale],
    queryFn: () => fetchRecentSignalsWithParams(signalsParams),
    refetchInterval: autoRefresh ? 15_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: orders } = useQuery({
    queryKey: ['three_screen', 'orders', phase, abOwner, bookId, groupId, pairSymbol, includeShadow],
    queryFn: () =>
      fetchRecentOrdersWithParams({
        limit: 200,
        sort: 'ingest',
        strategy_id: 'ThreeScreen',
        pair: pairSymbol,
        ab_owner: abOwner,
        book_id: bookId,
        group_id: groupId || undefined,
        include_shadow: includeShadow ? 1 : 0,
      }),
    refetchInterval: autoRefresh ? 15_000 : false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const latestSignalTs = useMemo(() => {
    const raw = Array.isArray(signals) ? signals : [];
    let mx = 0;
    for (const s of raw) {
      if (!s || typeof s !== 'object') continue;
      const ts = _toMs((s as { ts?: unknown } | null | undefined)?.ts ?? (s as { ts_ms?: unknown } | null | undefined)?.ts_ms);
      if (ts > mx) mx = ts;
    }
    return mx;
  }, [signals]);

  const series: SeriesPoint[] = useMemo(() => {
    const raw = Array.isArray(signals) ? signals : [];
    const orderArr = Array.isArray(orders) ? orders : [];
    const executedByEventId = new Set<string>();
    for (const o of orderArr) {
      const eid = String((o as { event_id?: unknown } | null | undefined)?.event_id ?? '').trim();
      if (eid) executedByEventId.add(eid);
    }

    const rows: SeriesPoint[] = [];
    for (const s of raw) {
      if (!s || typeof s !== 'object') continue;
      const ts = _toMs((s as { ts?: unknown } | null | undefined)?.ts ?? (s as { ts_ms?: unknown } | null | undefined)?.ts_ms);
      if (latestSignalTs > 0 && ts > 0 && ts < latestSignalTs - windowMs) continue;
      const evtId = String((s as { id?: unknown } | null | undefined)?.id ?? '').trim();
      const di = (s as { decision_info?: unknown } | null | undefined)?.decision_info as Record<string, unknown> | undefined;
      const out = (di && typeof di === 'object') ? (di as Record<string, unknown>) : null;
      const p = Number(out?.p_enter ?? out?.p ?? NaN);
      const th = Number(out?.threshold ?? NaN);
      rows.push({
        ts_ms: ts,
        p_enter: Number.isFinite(p) ? p : null,
        threshold: Number.isFinite(th) ? th : null,
        executed: (evtId && executedByEventId.has(evtId)) ? 1 : 0,
      });
    }
    rows.sort((a, b) => a.ts_ms - b.ts_ms);
    return rows;
  }, [latestSignalTs, orders, signals, windowMs]);

  const seriesAge = useMemo(() => {
    const ts = signalsUpdatedAt ? Number(signalsUpdatedAt) : 0;
    if (!ts || latestSignalTs <= 0) return { ageMs: Number.NaN, ageText: '-' };
    return { ageMs: ts - latestSignalTs, ageText: _fmtAge(ts - latestSignalTs) };
  }, [latestSignalTs, signalsUpdatedAt]);
  const seriesAgeBadge = useMemo(() => _badgeForAge(seriesAge.ageMs, 60_000), [seriesAge.ageMs]);

  const [nowMs, setNowMs] = useState<number>(0);
  useEffect(() => {
    let alive = true;
    const tick = () => {
      if (!alive) return;
      try {
        setNowMs(Date.now());
      } catch {
        void 0;
      }
    };
    tick();
    const id = window.setInterval(tick, 30_000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const weeklyAge = useMemo(() => {
    const ts = Number((weeklyStatus as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms ?? NaN);
    if (!Number.isFinite(ts) || ts <= 0) return null;
    if (nowMs <= 0) return null;
    const ageMs = nowMs - ts;
    return { ageMs, badge: _badgeForAge(ageMs, 7 * 24 * 3_600_000) };
  }, [nowMs, weeklyStatus]);
  const dailyAge = useMemo(() => {
    const ts = Number((dailySignal as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms ?? NaN);
    if (!Number.isFinite(ts) || ts <= 0) return null;
    if (nowMs <= 0) return null;
    const ageMs = nowMs - ts;
    return { ageMs, badge: _badgeForAge(ageMs, 2 * 24 * 3_600_000) };
  }, [dailySignal, nowMs]);
  const fiveMinAge = useMemo(() => {
    const ts = Number((fiveMinSignal as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms ?? NaN);
    if (!Number.isFinite(ts) || ts <= 0) return null;
    if (nowMs <= 0) return null;
    const ageMs = nowMs - ts;
    return { ageMs, badge: _badgeForAge(ageMs, 2 * 3_600_000) };
  }, [fiveMinSignal, nowMs]);
  const weeklyBarClosed = (weeklyStatus as { bar_closed?: unknown } | null | undefined)?.bar_closed;
  const dailyBarClosed = (dailySignal as { bar_closed?: unknown } | null | undefined)?.bar_closed;
  const fiveMinBarClosed = (fiveMinSignal as { bar_closed?: unknown } | null | undefined)?.bar_closed;
  const weeklyBarCloseMs = Number((weeklyStatus as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms ?? NaN);
  const dailyBarCloseMs = Number((dailySignal as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms ?? NaN);
  const fiveMinBarCloseMs = Number((fiveMinSignal as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms ?? NaN);
  const mtfOrderingOk = useMemo(() => {
    if (!Number.isFinite(fiveMinBarCloseMs) || fiveMinBarCloseMs <= 0) return null;
    if (Number.isFinite(weeklyBarCloseMs) && weeklyBarCloseMs > 0 && weeklyBarCloseMs > fiveMinBarCloseMs) return false;
    if (Number.isFinite(dailyBarCloseMs) && dailyBarCloseMs > 0 && dailyBarCloseMs > fiveMinBarCloseMs) return false;
    return true;
  }, [dailyBarCloseMs, fiveMinBarCloseMs, weeklyBarCloseMs]);
  const dailyAlignmentReason = (dailySignal as { alignment_reason?: unknown } | null | undefined)?.alignment_reason;
  const dailyValidFromMs = Number((dailySignal as { valid_from_ms?: unknown } | null | undefined)?.valid_from_ms ?? NaN);
  const dailyValidUntilMs = Number((dailySignal as { valid_until_ms?: unknown } | null | undefined)?.valid_until_ms ?? NaN);
  const dailyValidNow = useMemo(() => {
    if (!Number.isFinite(nowMs) || nowMs <= 0) return null;
    if (!Number.isFinite(dailyValidFromMs) || !Number.isFinite(dailyValidUntilMs)) return null;
    if (dailyValidFromMs <= 0 || dailyValidUntilMs <= 0) return null;
    return nowMs >= dailyValidFromMs && nowMs <= dailyValidUntilMs;
  }, [dailyValidFromMs, dailyValidUntilMs, nowMs]);
  const dailyWfoCostBps = Number((dailyWfo as { costs?: { cost_bps?: unknown } } | null | undefined)?.costs?.cost_bps ?? NaN);
  const dailyWfoBest = (dailyWfo as { summary?: { best_indicator_id?: unknown } } | null | undefined)?.summary?.best_indicator_id;
  const dailyWfoStability = (dailyWfo as { stability?: unknown } | null | undefined)?.stability as Record<string, unknown> | null | undefined;

  const phase0MlUrl = useMemo(() => `/ml?owner=strategy&strategy_id=ThreeScreen&ab_owner=strategy&book_id=strategy#ml-signals`, []);
  const phase1MlUrl = useMemo(() => `/ml?owner=three_screen&ab_owner=three_screen&book_id=three_screen#ml-signals`, []);
  const researchUrl = useMemo(() => {
    const q = new URLSearchParams();
    const p = String(pair ?? '').trim();
    const g = String(groupId ?? '').trim();
    if (p) q.set('pair', p);
    if (g) q.set('group_id', g);
    const qs = q.toString();
    return qs ? `/three_screen/research?${qs}` : '/three_screen/research';
  }, [groupId, pair]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">三屏交易 / ThreeScreen Console</h1>
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <span>view={viewMode}</span>
            <span>ab_owner={abOwner}</span>
            <span>book_id={bookId}</span>
            <span>strategy_id=ThreeScreen</span>
            {groupId ? <span>group_id={groupId}</span> : null}
            {viewMode !== 'auto' ? (
              <>
                <span className="text-slate-400">|</span>
                <span className="text-slate-500">cfg_ab_owner={abOwnerCfg}</span>
                <span className="text-slate-500">cfg_book_id={bookIdCfg}</span>
                <span className="text-slate-500">cfg_phase={phaseCfg}</span>
              </>
            ) : (
              <span className="text-slate-500">phase={phaseCfg}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link to={researchUrl}>
            <Button variant="outline">Research ↗</Button>
          </Link>
          <Link to={phase0MlUrl}>
            <Button variant="outline">打开 /ml (Phase0)</Button>
          </Link>
          <Link to={phase1MlUrl}>
            <Button variant="outline">打开 /ml (ThreeScreen)</Button>
          </Link>
          <a className="text-sm text-slate-600 underline" href="/docs#0.4.1.9">
            规格文档
          </a>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">全局筛选与刷新</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
          <div className="md:col-span-1">
            <div className="text-xs text-slate-500 mb-1">Pair</div>
            <Input value={pair} onChange={(e) => setPair(e.target.value)} placeholder="BTC" />
          </div>
          <div className="md:col-span-1">
            <div className="text-xs text-slate-500 mb-1">Group ID</div>
            <Input
              value={groupId}
              onChange={(e) => {
                setGroupTouched(true);
                setGroupId(e.target.value);
              }}
              placeholder="ts_v1"
            />
          </div>
          <div className="md:col-span-1">
            <div className="text-xs text-slate-500 mb-1">窗口(小时)</div>
            <Input value={String(windowH)} onChange={(e) => setWindowH(Number(e.target.value))} placeholder="24" />
          </div>
          <div className="md:col-span-2 flex items-center gap-2">
            <button
              type="button"
              className={viewMode === 'auto' ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200'}
              onClick={() => setViewMode('auto')}
            >
              view=auto
            </button>
            <button
              type="button"
              className={viewMode === 'phase0' ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200'}
              onClick={() => setViewMode('phase0')}
            >
              view=phase0
            </button>
            <button
              type="button"
              className={viewMode === 'phase1' ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200'}
              onClick={() => setViewMode('phase1')}
            >
              view=phase1
            </button>
            <button
              type="button"
              className={autoRefresh ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200'}
              onClick={() => setAutoRefresh((v) => !v)}
            >
              {autoRefresh ? '自动刷新 ON' : '自动刷新 OFF'}
            </button>
            <button
              type="button"
              className={includeShadow ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200'}
              onClick={() => setIncludeShadow((v) => !v)}
            >
              {includeShadow ? '含 shadow' : '不含 shadow'}
            </button>
            <button
              type="button"
              className={includeStale ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200'}
              onClick={() => setIncludeStale((v) => !v)}
            >
              {includeStale ? '含 stale' : '不含 stale'}
            </button>
            {signalsFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">周线趋势</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant={weeklyAge?.badge.variant ?? 'outline'}>
                {weeklyStatus?.ok ? (weeklyAge?.badge.label ?? 'ok') : (weeklyError ? 'error' : 'no data')}
              </Badge>
              <span className="text-sm text-slate-600">GET /three_screen/weekly/status</span>
              {weeklyFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
            </div>
            <div className="text-xs text-slate-600">{weeklyAge ? `data_age=${_fmtAge(weeklyAge.ageMs)}` : 'data_age=-'}</div>
            <div className="text-sm">
              <span className="text-slate-700">dir={String(weeklyStatus?.weekly_trend_dir ?? '-')}</span>
              <span className="text-slate-500"> · </span>
              <span className="text-slate-700">strength={weeklyStatus?.weekly_trend_strength == null ? '-' : String(weeklyStatus.weekly_trend_strength)}</span>
            </div>
            <div className="text-xs text-slate-600">
              bar_closed={weeklyBarClosed == null ? '-' : String(Boolean(weeklyBarClosed))}
              <span className="text-slate-400"> · </span>
              bar_close={Number.isFinite(weeklyBarCloseMs) && weeklyBarCloseMs > 0 ? new Date(weeklyBarCloseMs).toLocaleString() : '-'}
            </div>
            <div className="text-xs text-slate-600">
              weekly_regime={String((weeklyStatus as { weekly_regime?: unknown } | null | undefined)?.weekly_regime ?? '-')}
            </div>
            <div className="text-xs text-slate-600">
              components={(() => {
                const c =
                  (weeklyStatus as { weekly_components?: unknown; components?: unknown } | null | undefined)?.weekly_components ??
                  (weeklyStatus as { weekly_components?: unknown; components?: unknown } | null | undefined)?.components;
                return c && typeof c === 'object'
                  ? Object.keys((c as Record<string, unknown>) ?? {}).slice(0, 6).join(',')
                  : '-';
              })()}
            </div>
            <div className="text-xs text-slate-600">
              <div>asof_week={String(weeklyStatus?.asof_week ?? '-')}</div>
              {(() => {
                const raw = Array.isArray(weeklyStatus?.weekly_reason_codes)
                  ? weeklyStatus?.weekly_reason_codes
                  : (Array.isArray(weeklyStatus?.reason_codes) ? weeklyStatus?.reason_codes : []);
                const codes = raw.map((x) => String(x ?? '').trim()).filter((x) => x);
                if (!codes.length) return <div>reason_codes=</div>;
                const mid = Math.max(1, Math.ceil(codes.length / 2));
                const line1 = codes.slice(0, mid).join(',');
                const line2 = codes.slice(mid).join(',');
                return (
                  <>
                    <div className="break-all">reason_codes={line1}</div>
                    {line2 ? <div className="ml-4 break-all">{line2}</div> : null}
                  </>
                );
              })()}
            </div>
            <div className="pt-2 space-y-2">
              <div className="flex items-center gap-2">
                <Input
                  value={backfillDays}
                  onChange={(e) => setBackfillDays(e.target.value)}
                  className="h-8 w-20"
                  placeholder="days"
                />
                <Button
                  variant="outline"
                  onClick={() => backfillMutation.mutate()}
                  disabled={backfillMutation.isPending}
                >
                  一键 backfill
                </Button>
              </div>
              {backfillJobId && backfillJob ? (
                <div className="text-xs text-slate-600 break-all">
                  {(() => {
                    const st = String(backfillJob.status ?? '-');
                    const ok = backfillJob.ok;
                    const bf = (backfillJob.backfill && typeof backfillJob.backfill === 'object') ? (backfillJob.backfill as Record<string, unknown>) : null;
                    const w = bf ? bf.local_weekly_rows : undefined;
                    const d = bf ? bf.local_daily_rows : undefined;
                    return `job=${String(backfillJobId)} status=${st} ok=${String(ok)} local_daily_rows=${String(d ?? '-')} local_weekly_rows=${String(w ?? '-')}`;
                  })()}
                </div>
              ) : backfillMutation.data ? (
                <div className="text-xs text-slate-600 break-all">
                  {`backfill_ok=${String(Boolean(backfillMutation.data.ok))} local_weekly_rows=${String((backfillMutation.data.backfill as Record<string, unknown> | null | undefined)?.local_weekly_rows ?? '-')}`}
                </div>
              ) : null}
              {backfillMutation.error ? (
                <div className="text-xs text-rose-700">
                  {String((backfillMutation.error as { message?: unknown } | null | undefined)?.message ?? 'backfill_failed')}
                </div>
              ) : null}
            </div>
            {weeklyError ? (
              <div className="text-xs text-rose-700">
                {String((weeklyError as { message?: unknown } | null | undefined)?.message ?? 'request_failed')}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">日线 WFO / OOS</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant={dailyWfo?.ok ? 'default' : 'outline'}>{dailyWfo?.ok ? 'ok' : (wfoError ? 'error' : 'no data')}</Badge>
              <span className="text-sm text-slate-600">GET /three_screen/daily/wfo_summary</span>
              {wfoFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
            </div>
            <div className="text-sm">
              <span className="text-slate-700">asof_date={String(dailyWfo?.asof_date ?? '-')}</span>
              <span className="text-slate-500"> · </span>
              <span className="text-slate-700">selection_mode={String(dailyWfo?.selection_mode ?? '-')}</span>
            </div>
            <div className="text-xs text-slate-600">
              best_indicator_id={String(dailyWfoBest ?? '-')}
              <span className="text-slate-400"> · </span>
              cost_bps={Number.isFinite(dailyWfoCostBps) ? String(dailyWfoCostBps) : '-'}
            </div>
            <div className="text-xs text-slate-600">
              stability={dailyWfoStability && typeof dailyWfoStability === 'object' ? Object.entries(dailyWfoStability).slice(0, 4).map(([k, v]) => `${k}=${String(v ?? '-')}`).join(' ') : '-'}
            </div>
            <div className="text-xs text-slate-600">
              topk_k={dailyWfo?.topk_k == null ? '-' : String(dailyWfo.topk_k)} topk_n={Array.isArray(dailyWfo?.topk) ? dailyWfo.topk.length : 0}
            </div>
            {wfoError ? (
              <div className="text-xs text-rose-700">
                {String((wfoError as { message?: unknown } | null | undefined)?.message ?? 'request_failed')}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">日线信号</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant={dailyAge?.badge.variant ?? 'outline'}>
                {dailySignal?.ok ? (dailyAge?.badge.label ?? 'ok') : (dailyError ? 'error' : 'no data')}
              </Badge>
              <span className="text-sm text-slate-600">GET /three_screen/daily/signal</span>
              {dailyFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
            </div>
            <div className="text-xs text-slate-600">{dailyAge ? `data_age=${_fmtAge(dailyAge.ageMs)}` : 'data_age=-'}</div>
            <div className="text-sm">
              <span className="text-slate-700">dir={String(dailySignal?.daily_signal_dir ?? '-')}</span>
              <span className="text-slate-500"> · </span>
              <span className="text-slate-700">conf={dailySignal?.daily_signal_confidence == null ? '-' : String(dailySignal.daily_signal_confidence)}</span>
            </div>
            <div className="text-xs text-slate-600">
              bar_closed={dailyBarClosed == null ? '-' : String(Boolean(dailyBarClosed))}
              <span className="text-slate-400"> · </span>
              bar_close={Number.isFinite(dailyBarCloseMs) && dailyBarCloseMs > 0 ? new Date(dailyBarCloseMs).toLocaleString() : '-'}
            </div>
            <div className="text-xs text-slate-600">
              align_with_weekly={String(Boolean(dailySignal?.align_with_weekly))} alignment_reason={String(dailyAlignmentReason ?? '-')}
            </div>
            <div className="text-xs text-slate-600">
              valid_from={Number.isFinite(dailyValidFromMs) && dailyValidFromMs > 0 ? new Date(dailyValidFromMs).toLocaleString() : '-'} valid_until={Number.isFinite(dailyValidUntilMs) && dailyValidUntilMs > 0 ? new Date(dailyValidUntilMs).toLocaleString() : '-'}
              <span className="text-slate-400"> · </span>
              valid_now={dailyValidNow == null ? '-' : String(Boolean(dailyValidNow))}
            </div>
            <div className="text-xs text-slate-600">
              setup_family={String(dailySignal?.daily_setup?.setup_family ?? dailySignal?.daily_setup?.family ?? '-')} indicator={String(dailySignal?.daily_setup?.indicator_id ?? '-')} confirm_dir={String(dailySignal?.daily_setup?.confirm_dir ?? '-')}
            </div>
            <div className="text-xs text-slate-600">
              setup_reason_codes={Array.isArray(dailySignal?.daily_setup?.setup_reason_codes) ? String(dailySignal?.daily_setup?.setup_reason_codes.join(',')) : '-'}
            </div>
            {dailyError ? (
              <div className="text-xs text-rose-700">
                {String((dailyError as { message?: unknown } | null | undefined)?.message ?? 'request_failed')}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">5m 入场信号</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant={fiveMinAge?.badge.variant ?? 'outline'}>
                {fiveMinSignal?.ok ? (fiveMinAge?.badge.label ?? 'ok') : (fiveMinError ? 'error' : 'no data')}
              </Badge>
              <span className="text-sm text-slate-600">GET /three_screen/5m/signal</span>
              {fiveMinFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
            </div>
            <div className="text-xs text-slate-600">{fiveMinAge ? `data_age=${_fmtAge(fiveMinAge.ageMs)}` : 'data_age=-'}</div>
            <div className="text-sm">
              <span className="text-slate-700">action={String(fiveMinSignal?.action ?? '-')}</span>
              <span className="text-slate-500"> · </span>
              <span className="text-slate-700">side={String(fiveMinSignal?.side ?? '-')}</span>
            </div>
            <div className="text-xs text-slate-600">
              tag={String(fiveMinSignal?.tag ?? '-')}
            </div>
            <div className="text-xs text-slate-600">
              reject_reason={String(fiveMinSignal?.signal?.reject_reason ?? '-')} trigger_block_reason={String(fiveMinSignal?.signal?.trigger_block_reason ?? '-')}
            </div>
            <div className="text-xs text-slate-600">
              allowed_side={String(fiveMinSignal?.signal?.allowed_side ?? '-')} gate={String(fiveMinSignal?.signal?.gate ?? '-')}
            </div>
            <div className="text-xs text-slate-600">
              bar_closed={fiveMinBarClosed == null ? '-' : String(Boolean(fiveMinBarClosed))}
              <span className="text-slate-400"> · </span>
              bar_close={Number.isFinite(fiveMinBarCloseMs) && fiveMinBarCloseMs > 0 ? new Date(fiveMinBarCloseMs).toLocaleString() : '-'}
            </div>
            <div className="text-xs text-slate-600">
              mtf_bar_close_order_ok={mtfOrderingOk == null ? '-' : String(Boolean(mtfOrderingOk))}
            </div>
            {fiveMinError ? (
              <div className="text-xs text-rose-700">
                {String((fiveMinError as { message?: unknown } | null | undefined)?.message ?? 'request_failed')}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">门控状态（Gate State）</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant={gateState?.ok ? 'default' : 'outline'}>{gateState?.ok ? 'ok' : (gateError ? 'error' : 'no data')}</Badge>
              <span className="text-sm text-slate-600">GET /diagnostics/gate_state</span>
              {gateFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
            </div>
            <div className="text-xs text-slate-600">live={String(Boolean(gateState?.live))} venue={String(gateState?.execution_venue ?? '-')}</div>
            <div className="text-xs text-slate-600">
              three_screen.force_require_confirm={String((gateStateThreeScreen?.timing_force_require_confirm ?? (config as { three_screen_5m_timing_force_require_confirm?: unknown } | null | undefined)?.three_screen_5m_timing_force_require_confirm ?? '-'))}
              <span className="text-slate-400"> · </span>
              entry_mode={String((gateStateThreeScreen?.entry_mode_5m ?? (config as { three_screen_5m_entry_mode?: unknown } | null | undefined)?.three_screen_5m_entry_mode ?? '-'))}
            </div>
            <div className="text-xs text-slate-600">
              pool.cap_usdc={String((gateStateThreeScreen?.pool_cap_usdc ?? '-'))}
              <span className="text-slate-400"> · </span>
              used_usdc={String(((gateStateThreeScreen?.pool_usage as { notional_usdc?: unknown } | null | undefined)?.notional_usdc ?? '-'))}
              <span className="text-slate-400"> · </span>
              remaining_usdc={String((gateStateThreeScreen?.pool_remaining_usdc ?? '-'))}
              <span className="text-slate-400"> · </span>
              open_n={String(((gateStateThreeScreen?.pool_usage as { n?: unknown } | null | undefined)?.n ?? '-'))}
              <span className="text-slate-400">/</span>
              max_open={String((gateStateThreeScreen?.pool_max_open_trades ?? '-'))}
            </div>
            <div className="text-xs text-slate-600">
              macro_gate.enabled={String(Boolean((gateState as { macro_gate?: unknown } | null | undefined)?.macro_gate && typeof (gateState as { macro_gate?: unknown } | null | undefined)?.macro_gate === 'object' ? Boolean(((gateState as { macro_gate?: Record<string, unknown> } | null | undefined)?.macro_gate as Record<string, unknown>).enabled) : false))}
              <span className="text-slate-400"> · </span>
              fresh={String(((gateState as { macro_gate?: Record<string, unknown> } | null | undefined)?.macro_gate as Record<string, unknown> | undefined)?.fresh ?? '-')}
            </div>
            <div className="text-xs text-slate-600">
              gate_summary.n={String(((gateState as { gate_summary?: Record<string, unknown> } | null | undefined)?.gate_summary as Record<string, unknown> | undefined)?.n ?? '-')}
              <span className="text-slate-400"> · </span>
              ok={String((((gateState as { gate_summary?: Record<string, unknown> } | null | undefined)?.gate_summary as Record<string, unknown> | undefined)?.by_ok as Record<string, unknown> | undefined)?.ok ?? '-')}
              <span className="text-slate-400">/</span>
              reject={String((((gateState as { gate_summary?: Record<string, unknown> } | null | undefined)?.gate_summary as Record<string, unknown> | undefined)?.by_ok as Record<string, unknown> | undefined)?.reject ?? '-')}
            </div>
            {gateError ? (
              <div className="text-xs text-rose-700">
                {String((gateError as { message?: unknown } | null | undefined)?.message ?? 'request_failed')}
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">拒单统计 / 执行质量（近 7d）</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center gap-2">
              <Badge variant={rejectStats?.ok ? 'default' : 'outline'}>{rejectStats?.ok ? 'ok' : (rejectError ? 'error' : 'no data')}</Badge>
              <span className="text-sm text-slate-600">GET /signals/reject_stats</span>
              {rejectFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
            </div>
            <div className="text-xs text-slate-600">
              total={rejectStats?.total_events == null ? '-' : String(rejectStats.total_events)} with_decision={rejectStats?.with_decision == null ? '-' : String(rejectStats.with_decision)}
            </div>
            <div className="rounded border bg-white overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left p-2 font-medium text-slate-700">reason</th>
                    <th className="text-right p-2 font-medium text-slate-700">n</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const br = (rejectStats && typeof rejectStats === 'object' && rejectStats.by_reason && typeof rejectStats.by_reason === 'object') ? rejectStats.by_reason : {};
                    const rows = Object.entries(br)
                      .map(([k, v]) => ({ k, v: Number(v) }))
                      .filter((x) => x.k && Number.isFinite(x.v))
                      .sort((a, b) => b.v - a.v)
                      .slice(0, 6);
                    return rows.length ? rows.map((r) => (
                      <tr key={r.k} className="border-t">
                        <td className="p-2 text-slate-800">{r.k}</td>
                        <td className="p-2 text-right text-slate-700">{String(r.v)}</td>
                      </tr>
                    )) : (
                      <tr>
                        <td className="p-2 text-slate-600" colSpan={2}>no rows</td>
                      </tr>
                    );
                  })()}
                </tbody>
              </table>
            </div>

            <div className="flex items-center gap-2">
              <Badge variant={execQ?.ok ? 'default' : 'outline'}>{execQ?.ok ? 'ok' : (execQError ? 'error' : 'no data')}</Badge>
              <span className="text-sm text-slate-600">GET /audit/execution-quality</span>
              {execQFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
            </div>
            <div className="text-xs text-slate-600">
              n_orders={execQ?.n_orders == null ? '-' : String(execQ.n_orders)} fail_rate={execQ?.order_fail_rate == null ? '-' : String(execQ.order_fail_rate)}
            </div>
            <div className="text-xs text-slate-600">
              latency_p95_ms={execQ?.latency?.p95_ms == null ? '-' : String(execQ.latency.p95_ms)} slippage_p95_bps={execQ?.slippage?.p95_bps == null ? '-' : String(execQ.slippage.p95_bps)}
            </div>
            {rejectError || execQError ? (
              <div className="text-xs text-rose-700">
                {rejectError ? `reject_stats: ${String((rejectError as { message?: unknown } | null | undefined)?.message ?? 'request_failed')}` : null}
                {rejectError && execQError ? ' · ' : null}
                {execQError ? `execution_quality: ${String((execQError as { message?: unknown } | null | undefined)?.message ?? 'request_failed')}` : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">资金池 / 配额控制</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-9 gap-3 items-end">
          <div className="md:col-span-2">
            <div className="text-xs text-slate-500 mb-1">max_notional_usdc</div>
            <Input value={maxNotionalText} onChange={(e) => setMaxNotionalOverride(e.target.value)} placeholder="e.g. 5000" />
          </div>
          <div className="md:col-span-2">
            <div className="text-xs text-slate-500 mb-1">max_open_trades</div>
            <Input value={maxOpenTradesText} onChange={(e) => setMaxOpenTradesOverride(e.target.value)} placeholder="e.g. 5" />
          </div>
          <div className="md:col-span-1">
            <button
              type="button"
              className={useMlVote ? 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200 w-full' : 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900 w-full'}
              onClick={() => {
                setMlVoteTouched(true);
                setUseMlVote((v) => !v);
              }}
            >
              {useMlVote ? 'ml_vote=on' : 'ml_vote=off'}
            </button>
          </div>
          <div className="md:col-span-1">
            <button
              type="button"
              className={autoTrigger5m ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900 w-full' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200 w-full'}
              onClick={() => {
                setAutoTriggerTouched(true);
                setAutoTrigger5m((v) => !v);
              }}
            >
              {autoTrigger5m ? '5m_autotrigger=on' : '5m_autotrigger=off'}
            </button>
          </div>
          <div className="md:col-span-1">
            <button
              type="button"
              className={forceRequireConfirm ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900 w-full' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200 w-full'}
              onClick={() => {
                setForceRequireConfirmTouched(true);
                setForceRequireConfirm((v) => !v);
              }}
            >
              {forceRequireConfirm ? 'force_require_confirm=on' : 'force_require_confirm=off'}
            </button>
          </div>
          <div className="md:col-span-1">
            <button
              type="button"
              className={confirmLive ? 'px-2 py-1 rounded text-xs border bg-slate-900 text-white border-slate-900 w-full' : 'px-2 py-1 rounded text-xs border bg-white text-slate-700 border-slate-200 w-full'}
              onClick={() => setConfirmLive((v) => !v)}
            >
              {confirmLive ? 'confirm_live=true' : 'confirm_live=false'}
            </button>
          </div>
          <div className="md:col-span-1 flex items-center gap-2">
            <Button
              onClick={() => setPoolMutation.mutate()}
              disabled={setPoolMutation.isPending}
              className="w-full"
            >
              {setPoolMutation.isPending ? 'Saving…' : '保存'}
            </Button>
          </div>
          <div className="md:col-span-8 flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => liveEnableMutation.mutate()}
              disabled={!confirmLive || liveEnableMutation.isPending || liveDisableMutation.isPending}
            >
              {liveEnableMutation.isPending ? '实盘开启中…' : '实盘开启'}
            </Button>
            <Button
              variant="outline"
              onClick={() => liveDisableMutation.mutate()}
              disabled={!confirmLive || liveDisableMutation.isPending || liveEnableMutation.isPending}
            >
              {liveDisableMutation.isPending ? '实盘关闭中…' : '实盘关闭'}
            </Button>
            {liveEnableMutation.isError ? (
              <span className="text-xs text-rose-700">实盘开启失败：{String((liveEnableMutation.error as { message?: unknown } | null | undefined)?.message ?? 'unknown')}</span>
            ) : null}
            {liveDisableMutation.isError ? (
              <span className="text-xs text-rose-700">实盘关闭失败：{String((liveDisableMutation.error as { message?: unknown } | null | undefined)?.message ?? 'unknown')}</span>
            ) : null}
            {liveEnableMutation.isSuccess ? <span className="text-xs text-emerald-700">已提交“实盘开启”</span> : null}
            {liveDisableMutation.isSuccess ? <span className="text-xs text-emerald-700">已提交“实盘关闭”</span> : null}
          </div>
          {setPoolMutation.isError ? (
            <div className="md:col-span-6 text-xs text-rose-700">
              保存失败：{String((setPoolMutation.error as { message?: unknown } | null | undefined)?.message ?? 'unknown')}
            </div>
          ) : null}
          {setPoolMutation.isSuccess ? (
            <div className="md:col-span-6 text-xs text-emerald-700">
              已提交配置更新（可在 /config/get 校验）
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-base">5m 入场图表</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant={seriesAgeBadge.variant}>{seriesAgeBadge.label}</Badge>
            <span className="text-xs text-slate-600">data_age={seriesAge.ageText}</span>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="ts_ms"
                  type="number"
                  domain={['dataMin', 'dataMax']}
                  tickFormatter={(v) => new Date(Number(v)).toLocaleTimeString()}
                />
                <YAxis domain={[0, 1]} />
                <Tooltip
                  labelFormatter={(v) => new Date(Number(v)).toLocaleString()}
                  formatter={(v) => (v == null ? '-' : String(v))}
                />
                <ReferenceLine y={0.5} stroke="#94a3b8" strokeDasharray="4 4" />
                <Line type="monotone" dataKey="p_enter" stroke="#0f172a" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="threshold" stroke="#64748b" dot={false} strokeWidth={1} />
                <Line type="stepAfter" dataKey="executed" stroke="#16a34a" dot={false} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <SignalsTable
            abOwner={abOwner}
            bookId={bookId}
            strategyId="ThreeScreen"
            groupId={groupId || undefined}
            pair={pairSymbol}
            includeShadow={includeShadow}
            includeStale={includeStale}
            title="入场信号 / Gate / 下单联动（showOrderInfo）"
            displayLimit={40}
            showOrderInfo={true}
            defaultActionFilter="all"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">出场信号（close）</CardTitle>
        </CardHeader>
        <CardContent>
          <SignalsTable
            abOwner={abOwner}
            bookId={bookId}
            strategyId="ThreeScreen"
            groupId={groupId || undefined}
            pair={pairSymbol}
            includeShadow={includeShadow}
            includeStale={includeStale}
            title="Exit Signals / Gate / 下单联动（showOrderInfo）"
            displayLimit={40}
            showOrderInfo={true}
            defaultActionFilter="close"
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">订单（入场 / 离场）</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="entry">
            <TabsList>
              <TabsTrigger value="entry">Entry</TabsTrigger>
              <TabsTrigger value="exit">Exit</TabsTrigger>
            </TabsList>
            <TabsContent value="entry">
              <OrdersTable
                abOwner={abOwner}
                bookId={bookId}
                strategyId="ThreeScreen"
                groupId={groupId || undefined}
                pair={pairSymbol}
                includeShadow={includeShadow}
                actionGroup="entry"
                title="Entry Orders"
                displayLimit={30}
              />
            </TabsContent>
            <TabsContent value="exit">
              <OrdersTable
                abOwner={abOwner}
                bookId={bookId}
                strategyId="ThreeScreen"
                groupId={groupId || undefined}
                pair={pairSymbol}
                includeShadow={includeShadow}
                actionGroup="exit"
                title="Exit Orders"
                displayLimit={30}
              />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
};
