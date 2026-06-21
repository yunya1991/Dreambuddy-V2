import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchRecentOrdersWithParams, fetchRecentSignalsWithParams, fetchThreeScreen5mResearch, fetchThreeScreen5mSignal, fetchThreeScreenDailySignal, fetchThreeScreenDailyTalibRank, fetchThreeScreenDailyWfoSummary, fetchThreeScreenWeeklyDiagnostics, fetchThreeScreenWeeklyStatus } from '../lib/api';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import type { ThreeScreenDailyTalibRank } from '../lib/api';
import type { ThreeScreen5mResearch, ThreeScreenDailySignal, ThreeScreenDailyWfoSummary, ThreeScreen5mSignal, ThreeScreenWeeklyDiagnostics, ThreeScreenWeeklyStatus } from '../lib/api';

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

type TalibRankRow = {
  indicator_id?: string;
  family?: string;
  params?: Record<string, unknown> | null;
  score?: number;
  stability_pass?: boolean;
  stats_oos?: Record<string, unknown> | null;
  stats_folds?: Array<Record<string, unknown>> | null;
  notes?: string | null;
  [key: string]: unknown;
};

function _asNum(v: unknown): number | null {
  const x = Number(v);
  if (!Number.isFinite(x)) return null;
  return x;
}

const _rankErrorText = (d: ThreeScreenDailyTalibRank | null | undefined): string | null => {
  if (!d) return null;
  if (d.ok) return null;
  const err = String((d as { error?: unknown } | null | undefined)?.error ?? '').trim();
  if (!err) return 'error';
  return err;
};

export const ThreeScreenResearchPage: React.FC = () => {
  const [sp] = useSearchParams();

  const [pair, setPair] = useState<string>(() => String(sp.get('pair') ?? 'BTC').trim() || 'BTC');
  const [groupId, setGroupId] = useState<string>(() => String(sp.get('group_id') ?? 'ts_v1').trim() || 'ts_v1');

  const pairSymbol = useMemo(() => {
    const c = String(pair ?? '').trim().toUpperCase();
    if (!c) return undefined;
    return `${c}/USDC`;
  }, [pair]);

  const weeklyParams = useMemo(() => ({ pair: pair || undefined, group_id: groupId || undefined, auto_compute: 1 }), [groupId, pair]);
  const dailyParams = useMemo(() => ({ pair: pair || undefined, group_id: groupId || undefined, auto_compute: 1 }), [groupId, pair]);
  const wfoParams = useMemo(() => ({ pair: pair || undefined, group_id: groupId || undefined, auto_compute: 1 }), [groupId, pair]);
  const fiveMinParams = useMemo(
    () => ({ pair: pair || undefined, group_id: groupId || undefined, auto_compute: 1, require_bar_closed: 1, trigger_decision: 0 }),
    [groupId, pair],
  );

  const { data: weeklyStatus, isFetching: weeklyFetching, error: weeklyErr } = useQuery({
    queryKey: ['three_screen', 'research', 'weekly', weeklyParams],
    queryFn: () => fetchThreeScreenWeeklyStatus(weeklyParams),
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: dailySignal, isFetching: dailyFetching, error: dailyErr } = useQuery({
    queryKey: ['three_screen', 'research', 'daily', 'signal', dailyParams],
    queryFn: () => fetchThreeScreenDailySignal(dailyParams),
    refetchInterval: 30_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: dailyWfo, isFetching: wfoFetching } = useQuery({
    queryKey: ['three_screen', 'research', 'daily', 'wfo', wfoParams],
    queryFn: () => fetchThreeScreenDailyWfoSummary(wfoParams),
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: fiveMinSignal, isFetching: fiveMinFetching, error: fiveMinErr } = useQuery({
    queryKey: ['three_screen', 'research', '5m', fiveMinParams],
    queryFn: () => fetchThreeScreen5mSignal(fiveMinParams),
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const { data: fiveMinResearch, isFetching: fiveMinResearchFetching, error: fiveMinResearchErr } = useQuery({
    queryKey: ['three_screen', 'research', '5m', 'research', fiveMinParams],
    queryFn: () => fetchThreeScreen5mResearch(fiveMinParams),
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const [nowMs, setNowMs] = useState<number>(0);
  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const weeklyAge = useMemo(() => {
    const ts = _toMs((weeklyStatus as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms);
    if (!ts || nowMs <= 0) return null;
    const ageMs = nowMs - ts;
    return { ageMs, badge: _badgeForAge(ageMs, 7 * 24 * 3_600_000) };
  }, [nowMs, weeklyStatus]);
  const dailyAge = useMemo(() => {
    const ts = _toMs((dailySignal as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms);
    if (!ts || nowMs <= 0) return null;
    const ageMs = nowMs - ts;
    return { ageMs, badge: _badgeForAge(ageMs, 2 * 24 * 3_600_000) };
  }, [dailySignal, nowMs]);
  const fiveMinAge = useMemo(() => {
    const ts = _toMs((fiveMinSignal as { bar_close_ms?: unknown } | null | undefined)?.bar_close_ms);
    if (!ts || nowMs <= 0) return null;
    const ageMs = nowMs - ts;
    return { ageMs, badge: _badgeForAge(ageMs, 2 * 3_600_000) };
  }, [fiveMinSignal, nowMs]);

  const dailyTopk = useMemo(() => {
    const topk = (dailyWfo as ThreeScreenDailyWfoSummary | null | undefined)?.summary?.daily_topk;
    return Array.isArray(topk) ? topk : [];
  }, [dailyWfo]);

  const [rankLookbackDays, setRankLookbackDays] = useState<string>('1000');
  const [rankTrainDays, setRankTrainDays] = useState<string>('');
  const [rankTestDays, setRankTestDays] = useState<string>('');
  const [rankFolds, setRankFolds] = useState<string>('');
  const [rankGapDays, setRankGapDays] = useState<string>('');
  const [rankCostBps, setRankCostBps] = useState<string>('12');
  const [rankTopn, setRankTopn] = useState<string>('20');
  const [rankCacheTtl, setRankCacheTtl] = useState<string>('21600');

  const [rankParams, setRankParams] = useState(() => ({
    pair: pair || undefined,
    group_id: groupId || undefined,
    lookback_days: 1000,
    cost_bps: 12,
    topn: 20,
    cache_ttl_sec: 21600,
    train_days: undefined as number | undefined,
    test_days: undefined as number | undefined,
    folds: undefined as number | undefined,
    gap_days: undefined as number | undefined,
  }));

  const applyRankParams = () => {
    const lookback = Math.floor(Number(rankLookbackDays));
    const cost = Number(rankCostBps);
    const topn = Math.floor(Number(rankTopn));
    const ttl = Math.floor(Number(rankCacheTtl));
    const train = _asNum(rankTrainDays);
    const test = _asNum(rankTestDays);
    const folds = _asNum(rankFolds);
    const gap = _asNum(rankGapDays);
    setRankParams({
      pair: pair || undefined,
      group_id: groupId || undefined,
      lookback_days: Number.isFinite(lookback) ? lookback : 1000,
      cost_bps: Number.isFinite(cost) ? cost : 12,
      topn: Number.isFinite(topn) ? topn : 20,
      cache_ttl_sec: Number.isFinite(ttl) ? ttl : 21600,
      train_days: train == null ? undefined : Math.floor(train),
      test_days: test == null ? undefined : Math.floor(test),
      folds: folds == null ? undefined : Math.floor(folds),
      gap_days: gap == null ? undefined : Math.floor(gap),
    });
  };

  const { data: talibRank, isFetching: rankFetching, refetch: refetchRank } = useQuery({
    queryKey: ['three_screen', 'research', 'daily', 'talib_rank', rankParams],
    queryFn: () => fetchThreeScreenDailyTalibRank(rankParams),
    refetchOnWindowFocus: false,
    retry: false,
  });

  const rankRows: TalibRankRow[] = useMemo(() => {
    const rows = (talibRank as { rows?: unknown } | null | undefined)?.rows;
    return Array.isArray(rows) ? (rows as TalibRankRow[]) : [];
  }, [talibRank]);
  const rankErr = useMemo(() => _rankErrorText(talibRank), [talibRank]);

  const weeklyDir = String((weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_dir ?? '').trim() || '-';
  const weeklyRegime = String((weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_regime ?? '').trim() || '-';
  const weeklyDirA = String((weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_dir_a ?? '').trim() || '-';
  const weeklyStrengthA = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_strength_a;
  const weeklyDirB = String((weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_dir_b ?? '').trim() || '-';
  const weeklyStrengthB = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_strength_b;
  const weeklyBEnabled = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_ab_b_enabled;
  const weeklyBNeutralMult = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_ab_b_neutral_strength_mult;
  const weeklyBVetoOpposite = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_ab_b_veto_opposite;
  const weeklyBDampened = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_ab_b_dampened;
  const weeklyBVetoed = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_ab_b_vetoed;
  const weeklyBScoreLong = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_ab_b_score_long;
  const weeklyBScoreShort = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_ab_b_score_short;
  const weeklyBReasonCodes = useMemo(() => {
    const rc = (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_reason_codes_b;
    return Array.isArray(rc) ? rc.map((x) => String(x ?? '').trim()).filter(Boolean) : [];
  }, [weeklyStatus]);
  const weeklyReasonCodes = useMemo(() => {
    const rc =
      (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_reason_codes ??
      (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.reason_codes;
    return Array.isArray(rc) ? rc.map((x) => String(x ?? '').trim()).filter(Boolean) : [];
  }, [weeklyStatus]);
  const weeklyComponents = useMemo(() => {
    const c =
      (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_components ??
      (weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.components;
    if (!c || typeof c !== 'object') return null;
    return c as Record<string, unknown>;
  }, [weeklyStatus]);

  const dailyDir = String((dailySignal as ThreeScreenDailySignal | null | undefined)?.daily_signal_dir ?? '').trim() || '-';
  const dailyConf = (dailySignal as ThreeScreenDailySignal | null | undefined)?.daily_signal_confidence;
  const alignOk = Boolean((dailySignal as ThreeScreenDailySignal | null | undefined)?.align_with_weekly);
  const alignmentReason = String((dailySignal as ThreeScreenDailySignal | null | undefined)?.alignment_reason ?? '').trim() || '-';
  const fiveMinSide = String((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.side ?? '').trim() || '-';
  const fiveMinAction = String((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.action ?? '').trim() || '-';
  const fiveMinTag = String((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.tag ?? '').trim() || '-';
  const fiveMinBarClosed = (fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.bar_closed;
  const fiveMinAllowedSide = String(((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { allowed_side?: unknown } | null | undefined)?.allowed_side ?? '').trim() || '-';
  const fiveMinEntryDecision = String(((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { entry_decision?: unknown } | null | undefined)?.entry_decision ?? '').trim() || '-';
  const fiveMinEntryModelFamily = String(((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { entry_model_family?: unknown } | null | undefined)?.entry_model_family ?? '').trim() || '-';
  const fiveMinRejectReason = String(((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { reject_reason?: unknown } | null | undefined)?.reject_reason ?? '').trim() || '-';
  const fiveMinArenaModelId = String(((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { arena_model_id?: unknown } | null | undefined)?.arena_model_id ?? '').trim() || '-';
  const fiveMinArenaPc = ((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { arena_pc?: unknown } | null | undefined)?.arena_pc;
  const fiveMinArenaThr = ((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { arena_threshold?: unknown } | null | undefined)?.arena_threshold;
  const fiveMinArenaMargin = ((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { arena_margin?: unknown } | null | undefined)?.arena_margin;
  const fiveMinGate = useMemo(() => {
    const g = ((fiveMinSignal as ThreeScreen5mSignal | null | undefined)?.signal as { gate?: unknown } | null | undefined)?.gate;
    if (!g || typeof g !== 'object') return null;
    return g as Record<string, unknown>;
  }, [fiveMinSignal]);

  const fiveMinResearchBar = useMemo(() => {
    const b = (fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.bar;
    if (!b || typeof b !== 'object') return null;
    return b as Record<string, unknown>;
  }, [fiveMinResearch]);
  const fiveMinResearchTouchEval = useMemo(() => {
    const t = (fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.touch_eval;
    if (!t || typeof t !== 'object') return null;
    return t as Record<string, unknown>;
  }, [fiveMinResearch]);
  const fiveMinResearchConfirm = useMemo(() => {
    const c = (fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.confirm;
    if (!c || typeof c !== 'object') return null;
    return c as Record<string, unknown>;
  }, [fiveMinResearch]);
  const fiveMinResearchWindow = useMemo(() => {
    const w = (fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.window;
    if (!w || typeof w !== 'object') return null;
    return w as Record<string, unknown>;
  }, [fiveMinResearch]);
  const fiveMinResearchArena = useMemo(() => {
    const a = (fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.arena;
    if (!a || typeof a !== 'object') return null;
    return a as Record<string, unknown>;
  }, [fiveMinResearch]);
  const fiveMinResearchDecision = useMemo(() => {
    const d = (fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.decision;
    if (!d || typeof d !== 'object') return null;
    return d as Record<string, unknown>;
  }, [fiveMinResearch]);
  const fiveMinModelsTop = useMemo(() => {
    const rows = (fiveMinResearchArena as { models_top?: unknown } | null | undefined)?.models_top;
    return Array.isArray(rows) ? (rows as Array<Record<string, unknown>>) : [];
  }, [fiveMinResearchArena]);

  const recentSignalsParams = useMemo(() => {
    return {
      limit: 200,
      strategy_id: 'ThreeScreen',
      group_id: groupId || undefined,
      pair: pairSymbol,
      include_shadow: 1,
      include_stale: 1,
      require_bar_closed: 1,
    };
  }, [groupId, pairSymbol]);
  const { data: recentSignals } = useQuery({
    queryKey: ['three_screen', 'research', 'recent', 'signals', recentSignalsParams],
    queryFn: () => fetchRecentSignalsWithParams(recentSignalsParams),
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: Boolean(pairSymbol),
  });
  const { data: recentOrders } = useQuery({
    queryKey: ['three_screen', 'research', 'recent', 'orders', recentSignalsParams],
    queryFn: () =>
      fetchRecentOrdersWithParams({
        limit: 200,
        sort: 'ingest',
        strategy_id: 'ThreeScreen',
        group_id: groupId || undefined,
        pair: pairSymbol,
        include_shadow: 1,
      }),
    refetchInterval: 15_000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: Boolean(pairSymbol),
  });

  const recent5mStats = useMemo(() => {
    const sigs = Array.isArray(recentSignals) ? recentSignals : [];
    const ords = Array.isArray(recentOrders) ? recentOrders : [];
    const executed = new Set<string>();
    for (const o of ords) {
      const eid = String((o as { event_id?: unknown } | null | undefined)?.event_id ?? '').trim();
      if (eid) executed.add(eid);
    }
    const rows = sigs
      .filter((s) => s && typeof s === 'object')
      .filter((s) => (s as { bar_closed?: unknown } | null | undefined)?.bar_closed !== false);
    const N = Math.max(10, Math.min(200, 50));
    const slice = rows.slice(0, N);
    const tsOf = (s: unknown) => {
      const t = (s as { ts_ms?: unknown; ts?: unknown } | null | undefined)?.ts_ms ?? (s as { ts?: unknown } | null | undefined)?.ts;
      return _toMs(t);
    };
    let tMax = 0;
    let tMin = 0;
    let nExec = 0;
    for (const s of slice) {
      const ts = tsOf(s);
      if (ts > tMax) tMax = ts;
      if (tMin === 0 || (ts > 0 && ts < tMin)) tMin = ts;
      const eid = String((s as { id?: unknown } | null | undefined)?.id ?? '').trim();
      if (eid && executed.has(eid)) nExec += 1;
    }
    const spanMs = (tMax > 0 && tMin > 0 && tMax >= tMin) ? (tMax - tMin) : 0;
    const spanH = spanMs > 0 ? spanMs / 3_600_000 : 0;
    const densityPerH = spanH > 1e-9 ? (Math.max(1, slice.length - 1) / spanH) : null;
    const execRate = slice.length > 0 ? (nExec / slice.length) : null;
    return { n: slice.length, spanMs, densityPerH, execRate };
  }, [recentOrders, recentSignals]);

  const dailyBest = useMemo(() => {
    const v = (dailyWfo as ThreeScreenDailyWfoSummary | null | undefined)?.summary?.best_indicator_id;
    const s = String(v ?? '').trim();
    return s || '-';
  }, [dailyWfo]);

  const dailyScenarios = useMemo(() => {
    const s =
      (dailySignal as ThreeScreenDailySignal | null | undefined)?.daily_scenarios ??
      (((dailySignal as ThreeScreenDailySignal | null | undefined)?.signal as { daily_scenarios?: unknown } | null | undefined)?.daily_scenarios as unknown);
    if (!s || typeof s !== 'object') return null;
    return s as Record<string, unknown>;
  }, [dailySignal]);
  const dailySetups = useMemo(() => {
    const s =
      (dailySignal as ThreeScreenDailySignal | null | undefined)?.daily_setups ??
      (((dailySignal as ThreeScreenDailySignal | null | undefined)?.signal as { daily_setups?: unknown } | null | undefined)?.daily_setups as unknown);
    if (!s || typeof s !== 'object') return null;
    return s as Record<string, unknown>;
  }, [dailySignal]);
  const breakoutSetup = useMemo(() => {
    const s = (dailySetups as { trend_breakout_confirm?: unknown } | null | undefined)?.trend_breakout_confirm;
    if (!s || typeof s !== 'object') return null;
    return s as Record<string, unknown>;
  }, [dailySetups]);
  const pullbackSetup = useMemo(() => {
    const s = (dailySetups as { trend_pullback?: unknown } | null | undefined)?.trend_pullback;
    if (!s || typeof s !== 'object') return null;
    return s as Record<string, unknown>;
  }, [dailySetups]);
  const dailyValidFromMs = useMemo(() => {
    const v = (dailySignal as ThreeScreenDailySignal | null | undefined)?.valid_from_ms ?? (dailySignal as ThreeScreenDailySignal | null | undefined)?.bar_open_ms;
    return _toMs(v);
  }, [dailySignal]);
  const dailyValidUntilMs = useMemo(() => {
    const v = (dailySignal as ThreeScreenDailySignal | null | undefined)?.valid_until_ms ?? ((dailySignal as ThreeScreenDailySignal | null | undefined)?.signal as { valid_until_ms?: unknown } | null | undefined)?.valid_until_ms;
    return _toMs(v);
  }, [dailySignal]);
  const dailyValidDays = useMemo(() => {
    const v = (dailySignal as ThreeScreenDailySignal | null | undefined)?.valid_days ?? ((dailySignal as ThreeScreenDailySignal | null | undefined)?.signal as { valid_days?: unknown } | null | undefined)?.valid_days;
    const x = _asNum(v);
    return x == null ? null : Math.floor(x);
  }, [dailySignal]);
  const dailyValidNow = useMemo(() => {
    const v = ((dailySignal as ThreeScreenDailySignal | null | undefined)?.signal as { valid_now?: unknown } | null | undefined)?.valid_now;
    if (typeof v === 'boolean') return v;
    if (dailyValidUntilMs > 0 && nowMs > 0) return nowMs <= dailyValidUntilMs;
    return null;
  }, [dailySignal, dailyValidUntilMs, nowMs]);

  const docsUrl = '/docs?doc=技术文档.md&section=0.4.1.9.2';
  const _fmtN = (v: unknown, digits: number = 4): string => {
    const x = Number(v);
    if (!Number.isFinite(x)) return '-';
    return x.toFixed(digits);
  };
  const _fmtUtc = (ms: number): string => {
    if (!Number.isFinite(ms) || ms <= 0) return '-';
    try {
      return new Date(ms).toISOString().replace('T', ' ').slice(0, 16) + 'Z';
    } catch {
      return '-';
    }
  };
  const _dirBadgeVariant = (d: string): 'default' | 'secondary' | 'destructive' | 'outline' => {
    const s = String(d ?? '').trim().toLowerCase();
    if (s === 'long') return 'default';
    if (s === 'short') return 'destructive';
    if (s === 'neutral') return 'secondary';
    return 'outline';
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">三屏交易 / ThreeScreen Research</h1>
          <div className="flex items-center gap-2 text-sm text-slate-600">
            <span>pair={pair || '-'}</span>
            <span>group_id={groupId || '-'}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link to="/three_screen">
            <Button variant="outline">返回控制台</Button>
          </Link>
          <a className="text-sm text-slate-600 underline" href={docsUrl}>
            规格文档
          </a>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">全局筛选</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <div className="text-xs text-slate-500 mb-1">Pair</div>
            <Input value={pair} onChange={(e) => setPair(String(e.target.value ?? ''))} placeholder="BTC" />
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-1">Group ID</div>
            <Input value={groupId} onChange={(e) => setGroupId(String(e.target.value ?? ''))} placeholder="ts_v1" />
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline">weekly={weeklyDir}</Badge>
            <Badge variant="outline">daily={dailyDir}</Badge>
            <Badge variant="outline">5m={fiveMinSide}/{fiveMinAction}</Badge>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="core" className="w-full">
        <TabsList>
          <TabsTrigger value="core">核心</TabsTrigger>
          <TabsTrigger value="advanced">高级</TabsTrigger>
        </TabsList>

        <TabsContent value="core" className="space-y-4">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center justify-between">
                  <span>周屏（Regime / Bias）</span>
                  {weeklyFetching ? <Badge variant="secondary">updating</Badge> : <Badge variant="outline">ready</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center gap-2">
                  <Badge variant={weeklyAge?.badge.variant ?? 'outline'}>{weeklyStatus?.ok ? (weeklyAge?.badge.label ?? 'ok') : (weeklyErr ? 'error' : 'no data')}</Badge>
                  <div className="text-xs text-slate-600">{weeklyAge ? `data_age=${_fmtAge(weeklyAge.ageMs)}` : 'data_age=-'}</div>
                </div>
                <div className="text-sm text-slate-700">weekly_trend_dir={String((weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_dir ?? '-')}</div>
                <div className="text-sm text-slate-700">weekly_trend_strength={String((weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_strength ?? '-')}</div>
                <div className="text-sm text-slate-700">weekly_regime={weeklyRegime}</div>
                <div className="text-xs text-slate-600">reason_codes={weeklyReasonCodes.length ? weeklyReasonCodes.slice(0, 6).join(', ') : '-'}</div>
                <div className="text-xs text-slate-600">components={weeklyComponents ? Object.keys(weeklyComponents).slice(0, 6).join(', ') : '-'}</div>
                <div className="text-xs text-slate-600">crypto_hint=周屏更像风险偏好/波动状态过滤器</div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center justify-between">
                  <span>日屏（Selection / Ranking）</span>
                  {dailyFetching || wfoFetching ? <Badge variant="secondary">updating</Badge> : <Badge variant="outline">ready</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center gap-2">
                  <Badge variant={dailyAge?.badge.variant ?? 'outline'}>{dailySignal?.ok ? (dailyAge?.badge.label ?? 'ok') : (dailyErr ? 'error' : 'no data')}</Badge>
                  <div className="text-xs text-slate-600">{dailyAge ? `data_age=${_fmtAge(dailyAge.ageMs)}` : 'data_age=-'}</div>
                </div>
                <div className="rounded border bg-white p-2 space-y-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-slate-700 truncate">
                      valid_window={_fmtUtc(dailyValidFromMs)} → {_fmtUtc(dailyValidUntilMs)} (valid_days={dailyValidDays == null ? '-' : String(dailyValidDays)})
                    </div>
                    {dailyValidNow == null ? <Badge variant="outline">valid_now=-</Badge> : <Badge variant={dailyValidNow ? 'default' : 'secondary'}>valid_now={dailyValidNow ? 'true' : 'false'}</Badge>}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={_dirBadgeVariant(dailyDir)}>daily_dir={dailyDir}</Badge>
                    <Badge variant="outline">confidence={dailyConf == null ? '-' : String(dailyConf)}</Badge>
                    <Badge variant={alignOk ? 'default' : 'secondary'}>align_with_weekly={alignOk ? 'true' : 'false'}</Badge>
                    <Badge variant="outline">alignment_reason={alignmentReason}</Badge>
                  </div>
                  <div className="text-slate-700">best_indicator_id={dailyBest}</div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    <div className="rounded border bg-slate-50 p-2 space-y-1">
                      <div className="text-xs text-slate-500">趋势突破确认（breakout_confirm）</div>
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-slate-700 truncate">
                          bias={_fmtN((dailyScenarios as { breakout_confirm_bias?: unknown } | null | undefined)?.breakout_confirm_bias, 3)} share={_fmtN((dailyScenarios as { breakout_confirm_share?: unknown } | null | undefined)?.breakout_confirm_share, 3)} qual={_fmtN((dailyScenarios as { breakout_confirm_qual?: unknown } | null | undefined)?.breakout_confirm_qual, 3)}
                        </div>
                        <Badge variant={_dirBadgeVariant(String((breakoutSetup as { confirm_dir?: unknown } | null | undefined)?.confirm_dir ?? '-'))}>confirm={String((breakoutSetup as { confirm_dir?: unknown } | null | undefined)?.confirm_dir ?? '-')}</Badge>
                      </div>
                      <div className="text-slate-700 truncate">
                        level={_fmtN((breakoutSetup as { setup_level?: unknown } | null | undefined)?.setup_level, 2)} band={_fmtN((breakoutSetup as { band_width?: unknown } | null | undefined)?.band_width, 2)} retest_band={_fmtN((breakoutSetup as { retest_band?: unknown } | null | undefined)?.retest_band, 2)} cap={_fmtN((breakoutSetup as { extension_atr_cap?: unknown } | null | undefined)?.extension_atr_cap, 2)}
                      </div>
                      <div className="text-slate-700 truncate">
                        dist_from_level_atr={_fmtN((breakoutSetup as { dist_from_level_atr?: unknown } | null | undefined)?.dist_from_level_atr, 3)} breakout_margin_atr={_fmtN((breakoutSetup as { breakout_margin_atr?: unknown } | null | undefined)?.breakout_margin_atr, 3)}
                      </div>
                      <div className="text-slate-700 truncate">
                        retest_margin_atr={_fmtN((breakoutSetup as { retest_margin_atr?: unknown } | null | undefined)?.retest_margin_atr, 3)} extension_left={_fmtN((breakoutSetup as { extension_left?: unknown } | null | undefined)?.extension_left, 3)}
                      </div>
                    </div>
                    <div className="rounded border bg-slate-50 p-2 space-y-1">
                      <div className="text-xs text-slate-500">趋势回抽/反抽失败（pullback）</div>
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-slate-700 truncate">
                          bias={_fmtN((dailyScenarios as { pullback_bias?: unknown } | null | undefined)?.pullback_bias, 3)} share={_fmtN((dailyScenarios as { pullback_share?: unknown } | null | undefined)?.pullback_share, 3)} qual={_fmtN((dailyScenarios as { pullback_qual?: unknown } | null | undefined)?.pullback_qual, 3)}
                        </div>
                        <Badge variant={_dirBadgeVariant(String((pullbackSetup as { confirm_dir?: unknown } | null | undefined)?.confirm_dir ?? '-'))}>confirm={String((pullbackSetup as { confirm_dir?: unknown } | null | undefined)?.confirm_dir ?? '-')}</Badge>
                      </div>
                      <div className="text-slate-700 truncate">
                        ma_ref={String((pullbackSetup as { ma_ref?: unknown } | null | undefined)?.ma_ref ?? '-')} ma={_fmtN((pullbackSetup as { ma_value?: unknown } | null | undefined)?.ma_value, 2)} atr14={_fmtN((pullbackSetup as { atr14?: unknown } | null | undefined)?.atr14, 2)} band={_fmtN((pullbackSetup as { band_width?: unknown } | null | undefined)?.band_width, 2)}
                      </div>
                      <div className="text-slate-700 truncate">
                        dist_to_ma_atr={_fmtN((pullbackSetup as { dist_to_ma_atr?: unknown } | null | undefined)?.dist_to_ma_atr, 3)} touch_margin_atr={_fmtN((pullbackSetup as { touch_margin_atr?: unknown } | null | undefined)?.touch_margin_atr, 3)} reject_margin_atr={_fmtN((pullbackSetup as { reject_margin_atr?: unknown } | null | undefined)?.reject_margin_atr, 3)}
                      </div>
                      <div className="text-slate-700 truncate">
                        touch_long={String(Boolean((pullbackSetup as { touch_long?: unknown } | null | undefined)?.touch_long))} touch_short={String(Boolean((pullbackSetup as { touch_short?: unknown } | null | undefined)?.touch_short))}
                      </div>
                    </div>
                  </div>
                  <div className="text-slate-700">
                    bias_lead={_fmtN((dailyScenarios as { bias_lead?: unknown } | null | undefined)?.bias_lead, 3)}
                  </div>
                </div>
                {dailyTopk.length ? (
                  <div className="pt-1">
                    <div className="text-xs text-slate-500 mb-1">Top-K（来自 /three_screen/daily/wfo_summary）</div>
                    <div className="rounded border bg-white overflow-hidden">
                      <table className="w-full text-xs">
                        <thead className="bg-slate-50">
                          <tr>
                            <th className="text-left p-2 font-medium text-slate-700">indicator</th>
                            <th className="text-right p-2 font-medium text-slate-700">weight</th>
                            <th className="text-right p-2 font-medium text-slate-700">oos_score</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dailyTopk.slice(0, 6).map((it, i) => (
                            <tr key={`${String(it.indicator_id ?? '')}_${i}`} className="border-t">
                              <td className="p-2 text-slate-800">{String(it.indicator_id ?? '-')}</td>
                              <td className="p-2 text-right text-slate-700">{it.weight == null ? '-' : String(it.weight)}</td>
                              <td className="p-2 text-right text-slate-700">{it.oos_score == null ? '-' : String(it.oos_score)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center justify-between">
                  <span>5m（Entry Timing）</span>
                  {fiveMinFetching ? <Badge variant="secondary">updating</Badge> : <Badge variant="outline">ready</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center gap-2">
                  <Badge variant={fiveMinAge?.badge.variant ?? 'outline'}>{fiveMinSignal?.ok ? (fiveMinAge?.badge.label ?? 'ok') : (fiveMinErr ? 'error' : 'no data')}</Badge>
                  <div className="text-xs text-slate-600">{fiveMinAge ? `data_age=${_fmtAge(fiveMinAge.ageMs)}` : 'data_age=-'}</div>
                </div>
                <div className="text-sm text-slate-700">side={fiveMinSide}</div>
                <div className="text-sm text-slate-700">action={fiveMinAction}</div>
                <div className="text-sm text-slate-700">tag={fiveMinTag}</div>
                <div className="text-sm text-slate-700">bar_closed={fiveMinBarClosed == null ? '-' : (fiveMinBarClosed ? 'true' : 'false')}</div>
                <div className="text-sm text-slate-700">allowed_side={fiveMinAllowedSide}</div>
                <div className="text-sm text-slate-700">entry_decision={fiveMinEntryDecision}</div>
                <div className="text-sm text-slate-700">entry_model_family={fiveMinEntryModelFamily}</div>
                <div className="text-sm text-slate-700">arena_model_id={fiveMinArenaModelId}</div>
                <div className="text-sm text-slate-700">
                  arena_pc={_fmtN(fiveMinArenaPc, 4)} thr={_fmtN(fiveMinArenaThr, 4)} margin={_fmtN(fiveMinArenaMargin, 4)}
                </div>
                <div className="text-xs text-slate-600">reject_reason={fiveMinRejectReason}</div>
                <div className="text-xs text-slate-600">gate={fiveMinGate ? Object.keys(fiveMinGate).slice(0, 6).join(', ') : '-'}</div>
                <div className="text-xs text-slate-600">
                  recent_n={recent5mStats.n} span={recent5mStats.spanMs > 0 ? _fmtAge(recent5mStats.spanMs) : '-'} density={recent5mStats.densityPerH == null ? '-' : `${recent5mStats.densityPerH.toFixed(2)}/h`} executed={recent5mStats.execRate == null ? '-' : `${(recent5mStats.execRate * 100).toFixed(0)}%`}
                </div>
                <div className="text-xs text-slate-600">crypto_hint=只吃 bar_closed=true，显示门控与执行质量</div>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center justify-between">
                  <span>5m 拆解（Touch / Confirm / Window / Arena）</span>
                  {fiveMinResearchFetching ? <Badge variant="secondary">updating</Badge> : <Badge variant="outline">ready</Badge>}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{(fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.ok ? 'ok' : (fiveMinResearchErr ? 'error' : 'no data')}</Badge>
                  <Badge variant="outline">allowed_side={String(((fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.mtf as { allowed_side?: unknown } | null | undefined)?.allowed_side ?? '-')}</Badge>
                  <Badge variant="outline">setup_valid={String(((fiveMinResearch as ThreeScreen5mResearch | null | undefined)?.mtf as { setup_valid?: unknown } | null | undefined)?.setup_valid ?? '-')}</Badge>
                  <Badge variant="outline">entry_decision={String((fiveMinResearchDecision as { entry_decision?: unknown } | null | undefined)?.entry_decision ?? '-')}</Badge>
                  <Badge variant="outline">reject_reason={String((fiveMinResearchDecision as { reject_reason?: unknown } | null | undefined)?.reject_reason ?? '-')}</Badge>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">Last px</div>
                    <div className="text-sm text-slate-800">{_fmtN((fiveMinResearchBar as { px?: unknown } | null | undefined)?.px, 2)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">EMA20d</div>
                    <div className="text-sm text-slate-800">{_fmtN((fiveMinResearchTouchEval as { ema20d?: unknown } | null | undefined)?.ema20d, 2)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">dev / thr</div>
                    <div className="text-sm text-slate-800">
                      {(() => {
                        const dev = Number((fiveMinResearchTouchEval as { dev?: unknown } | null | undefined)?.dev);
                        const thr = Number((fiveMinResearchTouchEval as { thr?: unknown } | null | undefined)?.thr);
                        const devStr = Number.isFinite(dev) ? `${(dev * 100).toFixed(3)}%` : '-';
                        const thrStr = Number.isFinite(thr) ? `${(thr * 100).toFixed(3)}%` : '-';
                        return `${devStr} / ${thrStr}`;
                      })()}
                    </div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">Touch</div>
                    <div className="text-sm text-slate-800">
                      {String((fiveMinResearchTouchEval as { status?: unknown } | null | undefined)?.status ?? '-')},{' '}
                      {String((fiveMinResearchTouchEval as { ok?: unknown } | null | undefined)?.ok ?? '-')}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  <div className="rounded border bg-white p-2 space-y-1">
                    <div className="text-xs text-slate-500">Confirm（OR）</div>
                    <div className="text-sm text-slate-800">tag={String((fiveMinResearchConfirm as { tag?: unknown } | null | undefined)?.tag ?? '-')}</div>
                    <div className="text-sm text-slate-800">ok={String((fiveMinResearchConfirm as { ok?: unknown } | null | undefined)?.ok ?? '-')}</div>
                    <div className="text-xs text-slate-600 break-all">
                      confirm_tags={
                        Array.isArray((fiveMinResearchConfirm as { confirm_tags?: unknown } | null | undefined)?.confirm_tags)
                          ? ((fiveMinResearchConfirm as { confirm_tags?: unknown } | null | undefined)?.confirm_tags as unknown[]).map((x) => String(x ?? '').trim()).filter(Boolean).join(', ')
                          : '-'
                      }
                    </div>
                    <div className="text-xs text-slate-600 break-all">
                      details_keys=
                      {(() => {
                        const details = (fiveMinResearchConfirm as { details?: unknown } | null | undefined)?.details;
                        if (!details || typeof details !== 'object') return '-';
                        return Object.keys(details as Record<string, unknown>).slice(0, 12).join(', ');
                      })()}
                    </div>
                  </div>

                  <div className="rounded border bg-white p-2 space-y-1">
                    <div className="text-xs text-slate-500">Window / Ema-turn</div>
                    <div className="text-sm text-slate-800">
                      range={_fmtN((fiveMinResearchWindow as { low?: unknown } | null | undefined)?.low, 2)} ~ {_fmtN((fiveMinResearchWindow as { high?: unknown } | null | undefined)?.high, 2)}
                    </div>
                    <div className="text-sm text-slate-800">
                      bos_prev_high={_fmtN((fiveMinResearchWindow as { bos_prev_high?: unknown } | null | undefined)?.bos_prev_high, 2)} / bos_prev_low={_fmtN((fiveMinResearchWindow as { bos_prev_low?: unknown } | null | undefined)?.bos_prev_low, 2)}
                    </div>
                    <div className="text-sm text-slate-800">bos_break={String((fiveMinResearchWindow as { bos_break?: unknown } | null | undefined)?.bos_break ?? '-')}</div>
                    <div className="text-xs text-slate-600 break-all">
                      {(() => {
                        const e = (fiveMinResearchWindow as { ema_turn?: unknown } | null | undefined)?.ema_turn;
                        if (!e || typeof e !== 'object') return 'ema_turn=-';
                        const o = e as Record<string, unknown>;
                        const turn = String(o.turn ?? '-');
                        const volOk = String(o.vol_ok ?? '-');
                        const atrOk = String(o.atr_ok ?? '-');
                        const atrPct = _fmtN(o.atr_pct, 4);
                        return `turn=${turn} vol_ok=${volOk} atr_ok=${atrOk} atr_pct=${atrPct}`;
                      })()}
                    </div>
                  </div>
                </div>

                <div className="rounded border bg-white p-2 space-y-1">
                  <div className="text-xs text-slate-500">Arena（择优）</div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <Badge variant="outline">used={String((fiveMinResearchArena as { used?: unknown } | null | undefined)?.used ?? '-')}</Badge>
                    <Badge variant="outline">picked={String((fiveMinResearchArena as { picked_model_id?: unknown } | null | undefined)?.picked_model_id ?? '-')}</Badge>
                    <Badge variant="outline">pc={_fmtN((fiveMinResearchArena as { pc?: unknown } | null | undefined)?.pc, 4)}</Badge>
                    <Badge variant="outline">thr={_fmtN((fiveMinResearchArena as { threshold?: unknown } | null | undefined)?.threshold, 4)}</Badge>
                    <Badge variant="outline">margin={_fmtN((fiveMinResearchArena as { margin?: unknown } | null | undefined)?.margin, 4)}</Badge>
                  </div>
                  {fiveMinModelsTop.length ? (
                    <div className="pt-1">
                      <div className="rounded border bg-white overflow-hidden">
                        <table className="w-full text-xs">
                          <thead className="bg-slate-50">
                            <tr>
                              <th className="text-left p-2 font-medium text-slate-700">model</th>
                              <th className="text-right p-2 font-medium text-slate-700">weight</th>
                              <th className="text-right p-2 font-medium text-slate-700">pc</th>
                              <th className="text-right p-2 font-medium text-slate-700">thr</th>
                              <th className="text-right p-2 font-medium text-slate-700">eligible</th>
                            </tr>
                          </thead>
                          <tbody>
                            {fiveMinModelsTop.slice(0, 8).map((r, i) => (
                              <tr key={`${String(r.model_id ?? '')}_${i}`} className="border-t">
                                <td className="p-2 text-slate-800">{String(r.model_id ?? '-')}</td>
                                <td className="p-2 text-right text-slate-700">{_fmtN(r.weight, 4)}</td>
                                <td className="p-2 text-right text-slate-700">{_fmtN(r.pc, 4)}</td>
                                <td className="p-2 text-right text-slate-700">{r.thr == null ? '-' : _fmtN(r.thr, 4)}</td>
                                <td className="p-2 text-right text-slate-700">{String(r.eligible ?? '-')}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card className="lg:col-span-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center justify-between gap-2">
                  <span>周线 B 方案（EMA20w/EMA50w + ADX 过滤）</span>
                  <div className="flex items-center gap-2">
                    <Badge variant={_dirBadgeVariant(weeklyDirB)}>B={weeklyDirB}</Badge>
                    <Badge variant="outline">B_strength={weeklyStrengthB == null ? '-' : _fmtN(weeklyStrengthB, 3)}</Badge>
                  </div>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant={_dirBadgeVariant(weeklyDirA)}>A={weeklyDirA}</Badge>
                  <Badge variant="outline">A_strength={weeklyStrengthA == null ? '-' : _fmtN(weeklyStrengthA, 3)}</Badge>
                  <Badge variant={_dirBadgeVariant(weeklyDir)}>Final={weeklyDir}</Badge>
                  <Badge variant="outline">Final_strength={(weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_strength == null ? '-' : _fmtN((weeklyStatus as ThreeScreenWeeklyStatus | null | undefined)?.weekly_trend_strength, 3)}</Badge>
                  <Badge variant="outline">enabled={weeklyBEnabled == null ? '-' : (weeklyBEnabled ? 'true' : 'false')}</Badge>
                  <Badge variant="outline">neutral_mult={weeklyBNeutralMult == null ? '-' : _fmtN(weeklyBNeutralMult, 2)}</Badge>
                  <Badge variant="outline">veto_opposite={weeklyBVetoOpposite == null ? '-' : (weeklyBVetoOpposite ? 'true' : 'false')}</Badge>
                  <Badge variant="outline">dampened={weeklyBDampened == null ? '-' : (weeklyBDampened ? 'true' : 'false')}</Badge>
                  <Badge variant="outline">vetoed={weeklyBVetoed == null ? '-' : (weeklyBVetoed ? 'true' : 'false')}</Badge>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">EMA20w</div>
                    <div className="text-sm text-slate-800">{_fmtN((weeklyComponents as Record<string, unknown> | null | undefined)?.ema_fast, 2)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">EMA50w</div>
                    <div className="text-sm text-slate-800">{_fmtN((weeklyComponents as Record<string, unknown> | null | undefined)?.ema_slow, 2)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">EMA20 slope</div>
                    <div className="text-sm text-slate-800">{_fmtN((weeklyComponents as Record<string, unknown> | null | undefined)?.ema_slope, 4)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">ADX(14w)</div>
                    <div className="text-sm text-slate-800">{_fmtN((weeklyComponents as Record<string, unknown> | null | undefined)?.adx, 2)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">MACD_hist</div>
                    <div className="text-sm text-slate-800">{_fmtN((weeklyComponents as Record<string, unknown> | null | undefined)?.macd_hist, 4)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">MA spread</div>
                    <div className="text-sm text-slate-800">{_fmtN((weeklyComponents as Record<string, unknown> | null | undefined)?.ma_spread, 6)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">B_score_long</div>
                    <div className="text-sm text-slate-800">{weeklyBScoreLong == null ? '-' : _fmtN(weeklyBScoreLong, 3)}</div>
                  </div>
                  <div className="rounded border bg-white p-2">
                    <div className="text-xs text-slate-500">B_score_short</div>
                    <div className="text-sm text-slate-800">{weeklyBScoreShort == null ? '-' : _fmtN(weeklyBScoreShort, 3)}</div>
                  </div>
                </div>

                <div className="text-xs text-slate-600 break-all">
                  b_reason_codes={weeklyBReasonCodes.length ? weeklyBReasonCodes.join(',') : '-'}
                </div>
                <div className="text-xs text-slate-600 break-all">
                  final_reason_codes={weeklyReasonCodes.length ? weeklyReasonCodes.slice(0, 12).join(',') : '-'}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="advanced" className="space-y-4">
          <WeeklyDiagnosticsCard pair={pair} />
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base flex items-center justify-between">
                <span>日线 TA-Lib 指标回测排名（研究态，只读）</span>
                <div className="flex items-center gap-2">
                  {rankFetching ? <Badge variant="secondary">refreshing</Badge> : <Badge variant="outline">ready</Badge>}
                  <Button variant="outline" onClick={() => void refetchRank()} disabled={rankFetching}>Refresh</Button>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 md:grid-cols-7 gap-2 items-end">
                <div className="col-span-1">
                  <div className="text-xs text-slate-500 mb-1">lookback_days</div>
                  <Input value={rankLookbackDays} onChange={(e) => setRankLookbackDays(String(e.target.value ?? ''))} placeholder="1000" />
                </div>
                <div className="col-span-1">
                  <div className="text-xs text-slate-500 mb-1">cost_bps</div>
                  <Input value={rankCostBps} onChange={(e) => setRankCostBps(String(e.target.value ?? ''))} placeholder="12" />
                </div>
                <div className="col-span-1">
                  <div className="text-xs text-slate-500 mb-1">topn</div>
                  <Input value={rankTopn} onChange={(e) => setRankTopn(String(e.target.value ?? ''))} placeholder="20" />
                </div>
                <div className="col-span-1">
                  <div className="text-xs text-slate-500 mb-1">cache_ttl_sec</div>
                  <Input value={rankCacheTtl} onChange={(e) => setRankCacheTtl(String(e.target.value ?? ''))} placeholder="21600" />
                </div>
                <div className="col-span-1">
                  <div className="text-xs text-slate-500 mb-1">train_days</div>
                  <Input value={rankTrainDays} onChange={(e) => setRankTrainDays(String(e.target.value ?? ''))} placeholder="默认配置" />
                </div>
                <div className="col-span-1">
                  <div className="text-xs text-slate-500 mb-1">test_days</div>
                  <Input value={rankTestDays} onChange={(e) => setRankTestDays(String(e.target.value ?? ''))} placeholder="默认配置" />
                </div>
                <div className="col-span-1">
                  <div className="text-xs text-slate-500 mb-1">folds / gap_days</div>
                  <div className="flex gap-2">
                    <Input value={rankFolds} onChange={(e) => setRankFolds(String(e.target.value ?? ''))} placeholder="folds" />
                    <Input value={rankGapDays} onChange={(e) => setRankGapDays(String(e.target.value ?? ''))} placeholder="gap" />
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => {
                    applyRankParams();
                    void refetchRank();
                  }}
                >
                  Apply
                </Button>
                {talibRank?.cached ? <Badge variant="secondary">cached</Badge> : <Badge variant="outline">live</Badge>}
                {rankErr ? <Badge variant="destructive">{rankErr}</Badge> : null}
              </div>

              <div className="rounded border bg-white overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-left p-2 font-medium text-slate-700">indicator</th>
                      <th className="text-left p-2 font-medium text-slate-700">family</th>
                      <th className="text-right p-2 font-medium text-slate-700">score</th>
                      <th className="text-right p-2 font-medium text-slate-700">PF</th>
                      <th className="text-right p-2 font-medium text-slate-700">maxDD</th>
                      <th className="text-right p-2 font-medium text-slate-700">trades</th>
                      <th className="text-right p-2 font-medium text-slate-700">turnover</th>
                      <th className="text-right p-2 font-medium text-slate-700">net_pnl</th>
                      <th className="text-left p-2 font-medium text-slate-700">folds</th>
                      <th className="text-center p-2 font-medium text-slate-700">stable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rankRows.length ? (
                      rankRows.map((r, i) => {
                        const st = (r.stats_oos && typeof r.stats_oos === 'object') ? (r.stats_oos as Record<string, unknown>) : {};
                        const folds = Array.isArray(r.stats_folds) ? r.stats_folds : (Array.isArray((r as { stats_folds?: unknown } | null | undefined)?.stats_folds) ? ((r as { stats_folds?: unknown } | null | undefined)?.stats_folds as Array<Record<string, unknown>>) : []);
                        return (
                          <tr key={`${String(r.indicator_id ?? '')}_${i}`} className="border-t">
                            <td className="p-2 text-slate-800">{String(r.indicator_id ?? '-')}</td>
                            <td className="p-2 text-slate-700">{String(r.family ?? '-')}</td>
                            <td className="p-2 text-right text-slate-700">{r.score == null ? '-' : String(r.score)}</td>
                            <td className="p-2 text-right text-slate-700">{st.pf == null ? '-' : String(st.pf)}</td>
                            <td className="p-2 text-right text-slate-700">{st.max_dd == null ? '-' : String(st.max_dd)}</td>
                            <td className="p-2 text-right text-slate-700">{st.trades == null ? '-' : String(st.trades)}</td>
                            <td className="p-2 text-right text-slate-700">{st.turnover == null ? '-' : String(st.turnover)}</td>
                            <td className="p-2 text-right text-slate-700">{st.net_pnl_usdc == null ? '-' : String(st.net_pnl_usdc)}</td>
                            <td className="p-2 text-slate-700">
                              {folds.length ? (
                                <details className="select-none">
                                  <summary className="cursor-pointer text-slate-700 underline underline-offset-2">folds({folds.length})</summary>
                                  <div className="mt-2 rounded border bg-white overflow-hidden">
                                    <table className="w-full text-xs">
                                      <thead className="bg-slate-50">
                                        <tr>
                                          <th className="text-left p-2 font-medium text-slate-700">test</th>
                                          <th className="text-right p-2 font-medium text-slate-700">PF</th>
                                          <th className="text-right p-2 font-medium text-slate-700">maxDD</th>
                                          <th className="text-right p-2 font-medium text-slate-700">trades</th>
                                          <th className="text-right p-2 font-medium text-slate-700">turnover</th>
                                          <th className="text-right p-2 font-medium text-slate-700">net_pnl</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {folds.slice(0, 12).map((f, j) => {
                                          const testStart = String(f.test_start ?? '-');
                                          const testEnd = String(f.test_end ?? '-');
                                          return (
                                            <tr key={`${testStart}_${testEnd}_${j}`} className="border-t">
                                              <td className="p-2 text-slate-800">{testStart}→{testEnd}</td>
                                              <td className="p-2 text-right text-slate-700">{f.pf == null ? '-' : String(f.pf)}</td>
                                              <td className="p-2 text-right text-slate-700">{f.max_dd == null ? '-' : String(f.max_dd)}</td>
                                              <td className="p-2 text-right text-slate-700">{f.trades == null ? '-' : String(f.trades)}</td>
                                              <td className="p-2 text-right text-slate-700">{f.turnover == null ? '-' : String(f.turnover)}</td>
                                              <td className="p-2 text-right text-slate-700">{f.net_pnl_usdc == null ? '-' : String(f.net_pnl_usdc)}</td>
                                            </tr>
                                          );
                                        })}
                                      </tbody>
                                    </table>
                                  </div>
                                </details>
                              ) : (
                                <span className="text-slate-400">-</span>
                              )}
                            </td>
                            <td className="p-2 text-center">{r.stability_pass ? <Badge variant="default">pass</Badge> : <Badge variant="outline">fail</Badge>}</td>
                          </tr>
                        );
                      })
                    ) : (
                      <tr>
                        <td className="p-2 text-slate-600" colSpan={10}>no rows</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

const WeeklyDiagnosticsCard: React.FC<{ pair: string }> = ({ pair }) => {
  const [lookbackWeeks, setLookbackWeeks] = useState<string>('260');
  const [bins, setBins] = useState<string>('10');

  const params = useMemo(() => {
    const lb = Math.floor(Number(lookbackWeeks));
    const b = Math.floor(Number(bins));
    return {
      pair: String(pair || 'BTC').trim() || 'BTC',
      lookback_weeks: Number.isFinite(lb) ? lb : 260,
      bins: Number.isFinite(b) ? b : 10,
    };
  }, [bins, lookbackWeeks, pair]);

  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['three_screen', 'research', 'weekly', 'diagnostics', params],
    queryFn: () => fetchThreeScreenWeeklyDiagnostics(params),
    refetchOnWindowFocus: false,
    retry: false,
  });

  const diag = data as ThreeScreenWeeklyDiagnostics | null | undefined;
  const rawCorr = Array.isArray(diag?.raw?.corr_top) ? diag?.raw?.corr_top : [];
  const rawMi = Array.isArray(diag?.raw?.mi_top) ? diag?.raw?.mi_top : [];
  const stCorr = Array.isArray(diag?.strength?.corr_top) ? diag?.strength?.corr_top : [];
  const stMi = Array.isArray(diag?.strength?.mi_top) ? diag?.strength?.mi_top : [];
  const vif0 = (diag?.strength?.vif && typeof diag.strength.vif === 'object') ? diag.strength.vif : ((diag?.raw?.vif && typeof diag.raw.vif === 'object') ? diag.raw.vif : null);
  const vifRows = useMemo(() => {
    const obj = (vif0 && typeof vif0 === 'object') ? (vif0 as Record<string, unknown>) : null;
    if (!obj) return [];
    const rows = Object.entries(obj)
      .map(([k, v]) => ({ key: k, vif: Number(v) }))
      .filter((r) => r.key && Number.isFinite(r.vif))
      .sort((a, b) => b.vif - a.vif);
    return rows;
  }, [vif0]);

  const pca0 = (diag?.strength?.pca && typeof diag.strength.pca === 'object') ? diag.strength.pca : ((diag?.raw?.pca && typeof diag.raw.pca === 'object') ? diag.raw.pca : null);
  const pcaRep = useMemo(() => {
    const obj = (pca0 && typeof pca0 === 'object') ? (pca0 as Record<string, unknown>) : null;
    if (!obj) return null;
    const ok = Boolean(obj.ok);
    const error = typeof obj.error === 'string' ? obj.error : null;
    const nRows = Number(obj.n_rows);
    const evrRaw = obj.explained_var_ratio;
    const evr = Array.isArray(evrRaw) ? evrRaw.map((x) => Number(x)).filter((x) => Number.isFinite(x)) : [];
    const compsRaw = obj.components;
    const components = Array.isArray(compsRaw) ? (compsRaw as Array<Record<string, unknown>>) : [];
    return { ok, error, nRows: Number.isFinite(nRows) ? nRows : null, evr, components };
  }, [pca0]);

  const pcaCards = useMemo(() => {
    if (!pcaRep?.ok) return [];
    const out: Array<{ pc: string; evr: number | null; top: Array<{ k: string; v: number }> }> = [];
    for (const c of pcaRep.components.slice(0, 3)) {
      const pc = Number(c.pc);
      const evr = Number(c.explained_var_ratio);
      const load0 = (c.loadings && typeof c.loadings === 'object') ? (c.loadings as Record<string, unknown>) : {};
      const top = Object.entries(load0)
        .map(([k, v]) => ({ k, v: Number(v) }))
        .filter((x) => x.k && Number.isFinite(x.v))
        .sort((a, b) => Math.abs(b.v) - Math.abs(a.v))
        .slice(0, 6);
      out.push({ pc: Number.isFinite(pc) ? `PC${pc}` : 'PC?', evr: Number.isFinite(evr) ? evr : null, top });
    }
    return out;
  }, [pcaRep]);
  const errText = (() => {
    const e = error as unknown as { message?: unknown; response?: { status?: unknown } } | null | undefined;
    const status = e?.response?.status;
    const msg = typeof e?.message === 'string' ? e.message : '';
    if (status != null) return `${String(status)}${msg ? `: ${msg}` : ''}`;
    return msg || (diag?.ok ? '' : String(diag?.error ?? 'request_failed'));
  })();

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center justify-between">
          <span>周屏 Diagnostics（相关性/MI/PCA 摘要）</span>
          <div className="flex items-center gap-2">
            {isFetching ? <Badge variant="secondary">refreshing</Badge> : <Badge variant="outline">ready</Badge>}
            <Button variant="outline" onClick={() => void refetch()} disabled={isFetching}>Refresh</Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-2 items-end">
          <div className="col-span-1">
            <div className="text-xs text-slate-500 mb-1">pair</div>
            <Input value={pair} disabled />
          </div>
          <div className="col-span-1">
            <div className="text-xs text-slate-500 mb-1">lookback_weeks</div>
            <Input value={lookbackWeeks} onChange={(e) => setLookbackWeeks(String(e.target.value ?? ''))} />
          </div>
          <div className="col-span-1">
            <div className="text-xs text-slate-500 mb-1">bins</div>
            <Input value={bins} onChange={(e) => setBins(String(e.target.value ?? ''))} />
          </div>
          <div className="col-span-3 flex items-center gap-2">
            <Badge variant="outline">rows={diag?.n_rows == null ? '-' : String(diag?.n_rows)}</Badge>
            <Badge variant="outline">range={diag?.range_approx?.from ?? '-'}→{diag?.range_approx?.to ?? '-'}</Badge>
            {errText ? <Badge variant="destructive">{errText}</Badge> : null}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-2">
            <div className="text-xs text-slate-500">strength.corr_top (Top 6)</div>
            <div className="rounded border bg-white overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left p-2 font-medium text-slate-700">a</th>
                    <th className="text-left p-2 font-medium text-slate-700">b</th>
                    <th className="text-right p-2 font-medium text-slate-700">corr</th>
                  </tr>
                </thead>
                <tbody>
                  {(stCorr.length ? stCorr : rawCorr).slice(0, 6).map((r, i) => (
                    <tr key={`${String(r.a ?? '')}_${String(r.b ?? '')}_${i}`} className="border-t">
                      <td className="p-2 text-slate-800">{String(r.a ?? '-')}</td>
                      <td className="p-2 text-slate-700">{String(r.b ?? '-')}</td>
                      <td className="p-2 text-right text-slate-700">{r.corr == null ? '-' : String(r.corr)}</td>
                    </tr>
                  ))}
                  {((stCorr.length ? stCorr : rawCorr).length === 0) ? (
                    <tr>
                      <td className="p-2 text-slate-600" colSpan={3}>no rows</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-xs text-slate-500">strength.mi_top (Top 6)</div>
            <div className="rounded border bg-white overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left p-2 font-medium text-slate-700">a</th>
                    <th className="text-left p-2 font-medium text-slate-700">b</th>
                    <th className="text-right p-2 font-medium text-slate-700">mi</th>
                  </tr>
                </thead>
                <tbody>
                  {(stMi.length ? stMi : rawMi).slice(0, 6).map((r, i) => (
                    <tr key={`${String(r.a ?? '')}_${String(r.b ?? '')}_${i}`} className="border-t">
                      <td className="p-2 text-slate-800">{String(r.a ?? '-')}</td>
                      <td className="p-2 text-slate-700">{String(r.b ?? '-')}</td>
                      <td className="p-2 text-right text-slate-700">{r.mi == null ? '-' : String(r.mi)}</td>
                    </tr>
                  ))}
                  {((stMi.length ? stMi : rawMi).length === 0) ? (
                    <tr>
                      <td className="p-2 text-slate-600" colSpan={3}>no rows</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-2">
            <div className="text-xs text-slate-500">VIF（优先 strength.vif）</div>
            <div className="rounded border bg-white overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left p-2 font-medium text-slate-700">feature</th>
                    <th className="text-right p-2 font-medium text-slate-700">vif</th>
                  </tr>
                </thead>
                <tbody>
                  {vifRows.slice(0, 10).map((r) => (
                    <tr key={r.key} className="border-t">
                      <td className="p-2 text-slate-800">{r.key}</td>
                      <td className="p-2 text-right text-slate-700">{String(r.vif)}</td>
                    </tr>
                  ))}
                  {vifRows.length === 0 ? (
                    <tr>
                      <td className="p-2 text-slate-600" colSpan={2}>no rows</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-xs text-slate-500">PCA（优先 strength.pca）</div>
            <div className="rounded border bg-white p-3 space-y-2">
              {pcaRep?.ok ? (
                <>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">n_rows={pcaRep.nRows == null ? '-' : String(pcaRep.nRows)}</Badge>
                    <Badge variant="outline">evr={pcaRep.evr.length ? pcaRep.evr.slice(0, 5).map((x) => x.toFixed(3)).join(',') : '-'}</Badge>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    {pcaCards.map((c) => (
                      <div key={c.pc} className="rounded border bg-slate-50 p-2">
                        <div className="text-xs text-slate-700 flex items-center justify-between">
                          <span>{c.pc}</span>
                          <span className="text-slate-500">{c.evr == null ? '-' : c.evr.toFixed(3)}</span>
                        </div>
                        <div className="mt-1 space-y-1">
                          {c.top.length ? (
                            c.top.map((it) => (
                              <div key={it.k} className="text-[11px] text-slate-700 flex items-center justify-between gap-2">
                                <span className="truncate">{it.k}</span>
                                <span className="text-slate-500">{it.v.toFixed(3)}</span>
                              </div>
                            ))
                          ) : (
                            <div className="text-xs text-slate-500">no loadings</div>
                          )}
                        </div>
                      </div>
                    ))}
                    {pcaCards.length === 0 ? <div className="text-xs text-slate-500">no components</div> : null}
                  </div>
                </>
              ) : (
                <div className="text-xs text-slate-600">
                  {pcaRep ? `pca_error=${String(pcaRep.error ?? 'not_ok')}` : 'no data'}
                </div>
              )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
