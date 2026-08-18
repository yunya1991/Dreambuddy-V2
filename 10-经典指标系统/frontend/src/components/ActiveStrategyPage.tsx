import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  api,
  fetchAutomationStrategiesState,
  fetchAgentObservabilityParamoptRecent,
  fetchAgentParamoptTemplates,
  fetchAgentParamoptSearchSpace,
  fetchStrategyFeederCapabilities,
  fetchStrategyParams,
  fetchTrackerStats,
  setStrategyFeederConfig,
  setStrategyFeederUseCore,
  triggerBreakout,
  triggerMultiGroup,
  triggerRegimeHybrid,
  triggerStrategy005,
  triggerOtt,
  triggerAdaptiveVolatility,
} from '../lib/api';
import type {
  AgentObservabilityParamoptRecentItem,
  AgentParamoptSearchSpaceItem,
  AutomationStrategiesConfigResponse,
  StrategyFeederCapabilitiesResponse,
  StrategyParamsResponse,
  TrackerStats,
} from '../lib/api';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
import { Link } from 'react-router-dom';

function _fmt2(x: number, digits = 2): string {
  if (!Number.isFinite(x)) return '-';
  return x.toFixed(digits);
}

function _fmtPct(x: number, digits = 2): string {
  if (!Number.isFinite(x)) return '-';
  return `${(x * 100).toFixed(digits)}%`;
}

function _asNum(v: unknown, d = NaN): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

function _fmtDateTimeFromMs(ts: number): string {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return '-';
  const ms = n < 1e11 ? n * 1000 : n;
  return new Date(ms).toLocaleString();
}

function _ms(ts: unknown): number {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return n < 1e11 ? n * 1000 : n;
}

function _apiErrText(err: unknown): string {
  const e = err as {
    message?: string;
    response?: { status?: number; data?: unknown };
  };
  const st = Number(e?.response?.status);
  const data = e?.response?.data as Record<string, unknown> | undefined;
  const code = String(data?.reason_code ?? data?.error ?? '').trim();
  const stage = String(data?.failed_stage ?? '').trim();
  const msg = String(e?.message ?? err ?? '').trim();
  if (code && stage) return `${msg} | ${code} / ${stage}`;
  if (code) return `${msg} | ${code}`;
  if (Number.isFinite(st) && st > 0) return `${msg} | status=${st}`;
  return msg || 'request_failed';
}

function _utcYmd(tsMs: number): string {
  const d = new Date(Number.isFinite(tsMs) && tsMs > 0 ? tsMs : Date.now());
  return d.toISOString().slice(0, 10).replace(/-/g, '');
}

function _cooldownText(msRemain: number): string {
  const ms = Math.max(0, Math.trunc(msRemain));
  const sec = Math.trunc(ms / 1000);
  const h = Math.trunc(sec / 3600);
  const m = Math.trunc((sec % 3600) / 60);
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}m`;
  return `${m}m`;
}

type FeederDraftRow = {
  strategy_id: string;
  coinsText: string;
  emit: boolean;
  trigger_decision: boolean;
};

type FeederDraft = {
  enabled: boolean;
  period: number;
  rows: FeederDraftRow[];
};

export const ActiveStrategyPage: React.FC = () => {
  const queryClient = useQueryClient();

  const { data: paramsResp } = useQuery({
    queryKey: ['strategy', 'params'],
    queryFn: fetchStrategyParams,
    refetchInterval: 10000,
    refetchOnWindowFocus: false,
  });

  const { data: tracker } = useQuery({
    queryKey: ['tracker', 'sync', false, 'ui'],
    queryFn: () => fetchTrackerStats({ sync: false, view: 'ui' }),
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  });

  const { data: automation } = useQuery({
    queryKey: ['automation', 'state'],
    queryFn: fetchAutomationStrategiesState,
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
  });

  const [triggerCoin, setTriggerCoin] = useState<string>('BTC');
  const [triggerEmit, setTriggerEmit] = useState<boolean>(true);
  const [triggerDecision, setTriggerDecision] = useState<boolean>(true);
  const [triggerResult, setTriggerResult] = useState<string>('');

  const { data: feederCaps } = useQuery({
    queryKey: ['strategy', 'feeder', 'capabilities'],
    queryFn: fetchStrategyFeederCapabilities,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: 0,
  });

  const feederSupported = useMemo(() => {
    const caps = feederCaps as StrategyFeederCapabilitiesResponse | undefined;
    const fromCaps = Array.isArray(caps?.supported_strategy_ids) ? caps?.supported_strategy_ids.map((s) => String(s || '').trim()).filter(Boolean) : [];
    const fallback = ['Strategy005', 'RegimeHybridStrategy', 'BreakoutStrategy', 'MultiGroupStrategy', 'OttStrategy', 'Bot2Strategy'];
    const merged = [...fromCaps];
    for (const sid of fallback) {
      if (!merged.includes(sid)) merged.push(sid);
    }
    return merged;
  }, [feederCaps]);

  const strategies = useMemo(() => {
    const resp = paramsResp as StrategyParamsResponse | undefined;
    const xs = Object.keys(resp?.strategies ?? {});
    xs.sort((a, b) => a.localeCompare(b));
    return xs;
  }, [paramsResp]);

  const feederStrategyOptions = useMemo(() => {
    const fromParams = strategies.filter((sid) => feederSupported.includes(sid));
    const merged = [...fromParams];
    for (const sid of feederSupported) {
      if (!merged.includes(sid)) merged.push(sid);
    }
    merged.sort((a, b) => a.localeCompare(b));
    return merged;
  }, [strategies, feederSupported]);

  const openByStrategy = useMemo(() => {
    const st = tracker as TrackerStats | undefined;
    const open = st?.open_positions ?? {};
    const out: Record<string, number> = {};
    for (const v of Object.values(open)) {
      const sid = String((v as Record<string, unknown> | undefined)?.strategy_id ?? '').trim();
      if (!sid) continue;
      out[sid] = (out[sid] ?? 0) + 1;
    }
    return out;
  }, [tracker]);

  const pickPnl = (m: Record<string, number> | undefined, strategyId: string, groupId: string) => {
    const map = m ?? {};
    const sid = String(strategyId || '').trim();
    const gid = String(groupId || '').trim();
    if (sid && map[sid] !== undefined) return { key: sid, v: Number(map[sid] ?? 0) };
    if (gid && map[gid] !== undefined) return { key: gid, v: Number(map[gid] ?? 0) };
    return { key: '', v: NaN };
  };

  const feederStatsByStrategy = useMemo(() => {
    const st = tracker as TrackerStats | undefined;
    const per = st?.feeders?.per_strategy ?? {};
    return per as Record<string, { calls?: number; emits?: number; ingested?: number; null_signals?: number; errors?: number }>;
  }, [tracker]);

  const stratPerfById = useMemo(() => {
    const st = tracker as TrackerStats | undefined;
    return (st?.strategy_perf ?? {}) as Record<string, { rets?: number[]; n?: number; pf?: number; maxdd?: number }>;
  }, [tracker]);

  const stratWeights = useMemo(() => {
    const st = tracker as TrackerStats | undefined;
    return (st?.strategy_weights ?? {}) as Record<string, number>;
  }, [tracker]);

  const dailyPnl = useMemo(() => {
    const st = tracker as TrackerStats | undefined;
    return (st?.daily_pnl ?? {}) as Record<string, number>;
  }, [tracker]);

  const weeklyPnl = useMemo(() => {
    const st = tracker as TrackerStats | undefined;
    return (st?.weekly_pnl ?? {}) as Record<string, number>;
  }, [tracker]);

  const autoCfg = useMemo(() => {
    const a = automation as AutomationStrategiesConfigResponse | undefined;
    return a?.automation ?? null;
  }, [automation]);

  const derivedFeederDraft = useMemo((): FeederDraft => {
    if (!autoCfg) return { enabled: false, period: 30, rows: [] };
    const rows = (autoCfg.strategy_feeders ?? []).map((r) => ({
      strategy_id: String(r.strategy_id ?? '').trim(),
      coinsText: Array.isArray(r.coins) ? r.coins.join(',') : '',
      emit: Boolean(r.emit),
      trigger_decision: Boolean(r.trigger_decision),
    })).filter((r) => Boolean(r.strategy_id));
    return {
      enabled: Boolean(autoCfg.enable_strategy_feeders),
      period: Number(autoCfg.feeders_period_seconds ?? 30) || 30,
      rows,
    };
  }, [autoCfg]);

  const [feederDraft, setFeederDraft] = useState<FeederDraft | null>(null);
  const feeder = feederDraft ?? derivedFeederDraft;

  const feederSaveMutation = useMutation({
    mutationFn: setStrategyFeederConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['automation', 'state'] });
      queryClient.invalidateQueries({ queryKey: ['tracker', 'sync', false] });
    },
  });

  const feederUseCoreMutation = useMutation({
    mutationFn: async (payload: { enabled: boolean; period: number }) => setStrategyFeederUseCore(payload.enabled, payload.period),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['automation', 'state'] });
    },
  });

  const normalizeCoins = (txt: string): string[] => {
    return String(txt || '')
      .split(',')
      .map((x) => x.trim())
      .filter((x) => x.length > 0);
  };

  const feederIssues = useMemo(() => {
    const counts: Record<string, number> = {};
    const invalid: string[] = [];
    for (const r of feeder.rows) {
      const sid = String(r.strategy_id || '').trim();
      if (!sid) continue;
      counts[sid] = (counts[sid] ?? 0) + 1;
      if (!feederSupported.includes(sid)) invalid.push(sid);
    }
    const dup = Object.entries(counts)
      .filter(([, n]) => n > 1)
      .map(([sid]) => sid);
    return { invalid: Array.from(new Set(invalid)), duplicates: dup };
  }, [feeder.rows, feederSupported]);

  const canSaveFeeder = feederIssues.invalid.length === 0 && feederIssues.duplicates.length === 0;

  const saveFeeder = () => {
    if (!canSaveFeeder) return;
    const payload = {
      trace_id: `ui_${Date.now()}_strategy_feeder_save`,
      enable_strategy_feeders: Boolean(feeder.enabled),
      feeders_period_seconds: Math.max(5, Math.trunc(Number(feeder.period) || 30)),
      strategy_feeders: feeder.rows
        .map((r) => ({
          strategy_id: String(r.strategy_id || '').trim(),
          coins: normalizeCoins(r.coinsText),
          trigger_decision: Boolean(r.trigger_decision),
          emit: Boolean(r.emit),
        }))
        .filter((r) => Boolean(r.strategy_id)),
    };
    feederSaveMutation.mutate(payload);
  };

  const triggerMutation = useMutation({
    mutationFn: async (payload: { strategy_id: string; coin: string }) => {
      const sid = payload.strategy_id;
      const coin = payload.coin;
      if (sid === 'Strategy005') return await triggerStrategy005(coin, triggerEmit, triggerDecision);
      if (sid === 'RegimeHybridStrategy') return await triggerRegimeHybrid(coin, triggerEmit, triggerDecision);
      if (sid === 'BreakoutStrategy') return await triggerBreakout(coin, triggerEmit, triggerDecision);
      if (sid === 'MultiGroupStrategy') return await triggerMultiGroup(coin, triggerEmit, triggerDecision);
      if (sid === 'OttStrategy') return await triggerOtt(coin, triggerEmit, triggerDecision);
      if (sid === 'Bot2Strategy') return await triggerAdaptiveVolatility(coin, triggerEmit, triggerDecision);
      throw new Error('no_trigger_endpoint');
    },
    onSuccess: (res) => {
      try {
        setTriggerResult(JSON.stringify(res));
      } catch {
        setTriggerResult(String(res));
      }
      queryClient.invalidateQueries({ queryKey: ['signals', 'recent', 50] });
    },
    onError: (err) => {
      setTriggerResult(String((err as Error)?.message ?? err));
    },
  });

  const canTrigger = (sid: string) => {
    return sid === 'Strategy005' || sid === 'RegimeHybridStrategy' || sid === 'BreakoutStrategy' || sid === 'MultiGroupStrategy' || sid === 'OttStrategy' || sid === 'Bot2Strategy';
  };
  const triggerPath = (sid: string): string => {
    if (sid === 'Strategy005') return '/signals/hyperliquid/strategy005';
    if (sid === 'RegimeHybridStrategy') return '/signals/hyperliquid/regime_hybrid';
    if (sid === 'BreakoutStrategy') return '/signals/hyperliquid/breakout';
    if (sid === 'MultiGroupStrategy') return '/signals/hyperliquid/multigroup';
    if (sid === 'OttStrategy') return '/signals/hyperliquid/ott';
    if (sid === 'Bot2Strategy') return '/signals/hyperliquid/adaptive_volatility';
    return `/signals/hyperliquid/${sid}`;
  };

  const useCore = Boolean(autoCfg?.use_universe_core);

  const [paramoptSelectedStrategy, setParamoptSelectedStrategy] = useState<string>('');
  const [paramoptMode, setParamoptMode] = useState<'suggest' | 'sandbox'>('suggest');
  const [paramoptEvalMode, setParamoptEvalMode] = useState<'rolling' | 'backtest'>('backtest');
  const [paramoptFamily, setParamoptFamily] = useState<string>('xgb');
  const [paramoptFolds, setParamoptFolds] = useState<number>(2);
  const [paramoptNInit, setParamoptNInit] = useState<number>(2);
  const [paramoptNIter, setParamoptNIter] = useState<number>(3);
  const [paramoptSkipRobustness, setParamoptSkipRobustness] = useState<boolean>(true);
  const [paramoptBacktestConfig, setParamoptBacktestConfig] = useState<string>('user_data/config_local_backtest.json');
  const [paramoptBacktestTimerange, setParamoptBacktestTimerange] = useState<string>('20251115-20260115');
  const [paramoptBacktestTimeoutSec, setParamoptBacktestTimeoutSec] = useState<number>(1800);
  const [paramoptDomainMain, setParamoptDomainMain] = useState<string>('BTC/USDT:USDT');
  const [paramoptChallengeSet, setParamoptChallengeSet] = useState<string>('ETH/USDT:USDT,SOL/USDT:USDT');
  const [paramoptMinTrades7d, setParamoptMinTrades7d] = useState<number>(0);
  const [paramoptMinEffectiveDays7d, setParamoptMinEffectiveDays7d] = useState<number>(0);
  const [paramoptResult, setParamoptResult] = useState<string>('');
  const [paramoptTraceId, setParamoptTraceId] = useState<string>('');
  const [paramoptDays, setParamoptDays] = useState<number>(7);
  const [paramoptCooldownHours, setParamoptCooldownHours] = useState<number>(24);
  const [paramoptIgnoreCooldown, setParamoptIgnoreCooldown] = useState<boolean>(false);
  const [paramoptForceNew, setParamoptForceNew] = useState<boolean>(false);
  const [paramoptTopN, setParamoptTopN] = useState<number>(3);
  const [paramoptBatchPlanId, setParamoptBatchPlanId] = useState<string>('');
  const [paramoptBatchItems, setParamoptBatchItems] = useState<Array<{ strategy_id: string; step_seq: number; step_id: string; trace_id: string; status: string; error?: string }>>([]);
  const [paramoptBatchResult, setParamoptBatchResult] = useState<string>('');
  const [showParamoptSpaceRaw, setShowParamoptSpaceRaw] = useState<boolean>(false);
  const [showParamContractHelp, setShowParamContractHelp] = useState<boolean>(false);
  const [paramoptTemplateKind, setParamoptTemplateKind] = useState<'base' | 'daily' | 'approval'>('base');

  const activeStrategyIds = useMemo(() => {
    const ids = new Set<string>();
    for (const [sid, w] of Object.entries(stratWeights ?? {})) {
      const x = Number(w);
      if (Number.isFinite(x) && x > 0) ids.add(String(sid));
    }
    for (const [sid, n] of Object.entries(openByStrategy ?? {})) {
      const x = Number(n);
      if (Number.isFinite(x) && x > 0) ids.add(String(sid));
    }
    for (const r of feeder.rows) {
      const sid = String(r.strategy_id ?? '').trim();
      if (sid) ids.add(sid);
    }
    return Array.from(ids).sort((a, b) => a.localeCompare(b));
  }, [stratWeights, openByStrategy, feeder.rows]);

  const paramoptStrategyOptions = useMemo(() => {
    const merged = Array.from(new Set([...(activeStrategyIds ?? []), ...(strategies ?? [])]));
    merged.sort((a, b) => a.localeCompare(b));
    return merged;
  }, [activeStrategyIds, strategies]);

  const effectiveParamoptStrategy = useMemo(() => {
    const cur = String(paramoptSelectedStrategy || '').trim();
    if (cur) return cur;
    if (activeStrategyIds.length > 0) return activeStrategyIds[0];
    return strategies[0] ?? '';
  }, [paramoptSelectedStrategy, activeStrategyIds, strategies]);

  const paramoptMeta = useMemo(() => {
    const resp = paramsResp as StrategyParamsResponse | undefined;
    const meta = effectiveParamoptStrategy ? resp?.strategies?.[effectiveParamoptStrategy] : undefined;
    const gid = String(meta?.group_id ?? '').trim();
    const params = (meta?.params ?? {}) as Record<string, unknown>;
    return { group_id: gid, params };
  }, [paramsResp, effectiveParamoptStrategy]);

  const paramoptRecentQuery = useQuery({
    queryKey: ['agent', 'observability', 'paramopt', 'recent', { days: paramoptDays, limit: 80 }],
    queryFn: () => fetchAgentObservabilityParamoptRecent({ days: paramoptDays, limit: 80 }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const paramoptTemplateQuery = useQuery({
    queryKey: ['agent', 'paramopt', 'templates', paramoptTemplateKind],
    queryFn: () => fetchAgentParamoptTemplates({ kind: paramoptTemplateKind }),
    refetchInterval: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const paramoptRecentRows = useMemo(() => {
    const items = (paramoptRecentQuery.data as { items?: AgentObservabilityParamoptRecentItem[] } | undefined)?.items;
    const xs = Array.isArray(items) ? items : [];
    const sid = String(effectiveParamoptStrategy || '').trim();
    const out = xs.filter((it) => String(it.opt_class ?? '').trim().toLowerCase() === 'strategy' && String(it.strategy_id ?? '').trim() === sid);
    out.sort((a, b) => Number(b.ts ?? 0) - Number(a.ts ?? 0));
    return out.slice(0, 20);
  }, [paramoptRecentQuery.data, effectiveParamoptStrategy]);

  const resolveParamoptErrorByTrace = React.useCallback(
    async (traceId: string, fallbackMsg: string): Promise<{ message: string; reason_code?: string; failed_stage?: string }> => {
      const tid = String(traceId || '').trim();
      if (!tid) return { message: fallbackMsg };
      try {
        const r = await fetchAgentObservabilityParamoptRecent({ days: Math.max(1, Math.trunc(Number(paramoptDays) || 7)), limit: 120 });
        const items = Array.isArray((r as { items?: AgentObservabilityParamoptRecentItem[] } | undefined)?.items)
          ? ((r as { items?: AgentObservabilityParamoptRecentItem[] }).items as AgentObservabilityParamoptRecentItem[])
          : [];
        const hit = items.find((it) => String(it.trace_id ?? '').trim() === tid);
        if (!hit) return { message: fallbackMsg };
        const rc = String(hit.reason_code ?? '').trim();
        const fs = String(hit.failed_stage ?? '').trim();
        if (rc && fs) return { message: `${fallbackMsg} | ${rc} / ${fs}`, reason_code: rc, failed_stage: fs };
        if (rc) return { message: `${fallbackMsg} | ${rc}`, reason_code: rc };
        if (fs) return { message: `${fallbackMsg} | failed_stage=${fs}`, failed_stage: fs };
        return { message: fallbackMsg };
      } catch {
        return { message: fallbackMsg };
      }
    },
    [paramoptDays],
  );

  const lastParamoptByStrategy = useMemo(() => {
    const items = (paramoptRecentQuery.data as { items?: AgentObservabilityParamoptRecentItem[] } | undefined)?.items;
    const xs = Array.isArray(items) ? items : [];
    const out = new Map<string, AgentObservabilityParamoptRecentItem>();
    for (const it of xs) {
      if (String(it.opt_class ?? '').trim().toLowerCase() !== 'strategy') continue;
      if (it.ok !== true) continue;
      const sid = String(it.strategy_id ?? '').trim();
      if (!sid) continue;
      const prev = out.get(sid);
      const ts = _ms(it.ts);
      const prevTs = _ms(prev?.ts);
      if (!prev || ts > prevTs) out.set(sid, it);
    }
    return out;
  }, [paramoptRecentQuery.data]);

  const nowMs = Date.now();
  const cooldownMs = Math.max(0, Number(paramoptCooldownHours) || 0) * 3600 * 1000;
  const selectedLast = lastParamoptByStrategy.get(String(effectiveParamoptStrategy || '').trim());
  const selectedLastTsMs = _ms(selectedLast?.ts);
  const selectedCooldownRemainMs = selectedLastTsMs > 0 ? (selectedLastTsMs + cooldownMs - nowMs) : 0;
  const selectedInCooldown = selectedCooldownRemainMs > 0;

  const selectedIdempotencyKey = useMemo(() => {
    const sid = String(effectiveParamoptStrategy || '').trim();
    const bucket = _utcYmd(nowMs);
    return `paramopt:strategy:${sid}:${bucket}:${paramoptMode}:${paramoptEvalMode}:${String(paramoptFamily || 'xgb').trim() || 'xgb'}`;
  }, [effectiveParamoptStrategy, nowMs, paramoptMode, paramoptEvalMode, paramoptFamily]);

  const selectedPlanId = useMemo(() => {
    const sid = String(effectiveParamoptStrategy || '').trim();
    const bucket = _utcYmd(nowMs);
    return `ui_paramopt_strategy_${sid}_${bucket}`;
  }, [effectiveParamoptStrategy, nowMs]);

  const topNByWeight = useMemo(() => {
    const rows: Array<{ strategy_id: string; w: number }> = [];
    for (const [sid, w0] of Object.entries(stratWeights ?? {})) {
      const w = Number(w0);
      if (!Number.isFinite(w) || w <= 0) continue;
      rows.push({ strategy_id: String(sid), w });
    }
    rows.sort((a, b) => b.w - a.w);
    const n = Math.max(1, Math.min(20, Math.trunc(Number(paramoptTopN) || 3)));
    const picked = rows.slice(0, n).map((r) => r.strategy_id);
    if (picked.length >= n) return picked;
    const fill = activeStrategyIds.filter((sid) => !picked.includes(sid)).slice(0, n - picked.length);
    return [...picked, ...fill];
  }, [stratWeights, paramoptTopN, activeStrategyIds]);

  const paramoptSearchSpaceQuery = useQuery({
    queryKey: ['agent', 'paramopt', 'search_space', { strategy_id: effectiveParamoptStrategy }],
    queryFn: () =>
      fetchAgentParamoptSearchSpace({
        include_suggest_only: true,
        opt_class: 'strategy',
        strategy_id: String(effectiveParamoptStrategy || '').trim() || undefined,
      }),
    refetchInterval: false,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const paramoptPrefixes = useMemo(() => {
    const sid = String(effectiveParamoptStrategy || '').trim();
    const gid = String(paramoptMeta.group_id || '').trim();
    const out: string[] = [];
    if (gid) out.push(gid.endsWith('_') ? gid : `${gid}_`);
    const m = sid.match(/^Strategy(\d+)$/i);
    if (m && m[1]) {
      const n = Number(m[1]);
      if (Number.isFinite(n)) out.push(`s${String(Math.trunc(n)).padStart(3, '0')}_`);
    }
    if (sid.toLowerCase() === 'regimehybridstrategy') out.push('rh_', 'regime_hybrid_');
    return Array.from(new Set(out)).filter(Boolean);
  }, [effectiveParamoptStrategy, paramoptMeta.group_id]);

  const paramoptSpaceItems = useMemo(() => {
    const items = (paramoptSearchSpaceQuery.data as { space?: { items?: AgentParamoptSearchSpaceItem[] } } | undefined)?.space?.items;
    const xs = Array.isArray(items) ? items : [];
    const prefixes = paramoptPrefixes;
    const exactKeys = Object.keys(paramoptMeta.params ?? {}).map((k) => String(k || '').trim()).filter(Boolean);
    if (xs.length === 0) return [];
    const byKey = new Map<string, AgentParamoptSearchSpaceItem>();
    for (const it of xs) {
      const k = String(it?.key ?? '').trim();
      if (!k) continue;
      byKey.set(k, it);
    }
    const keep: AgentParamoptSearchSpaceItem[] = [];
    for (const it of xs) {
      const k = String(it?.key ?? '').trim();
      if (!k) continue;
      if (prefixes.some((p) => k.startsWith(p))) keep.push(it);
    }
    for (const k of exactKeys) {
      const it = byKey.get(k);
      if (it) keep.push(it);
    }
    const uniq = new Map<string, AgentParamoptSearchSpaceItem>();
    for (const it of keep) {
      const k = String(it?.key ?? '').trim();
      if (!k) continue;
      uniq.set(k, it);
    }
    const out = Array.from(uniq.values());
    out.sort((a, b) => String(a.key).localeCompare(String(b.key)));
    return out;
  }, [paramoptSearchSpaceQuery.data, paramoptPrefixes, paramoptMeta.params]);

  const paramoptSpaceSelection = useMemo(() => {
    const sel = (paramoptSearchSpaceQuery.data as { selection?: { selected_n?: number; ignored_n?: number } } | undefined)?.selection;
    const selectedN = Number(sel?.selected_n);
    const ignoredN = Number(sel?.ignored_n);
    return {
      selected_n: Number.isFinite(selectedN) ? selectedN : undefined,
      ignored_n: Number.isFinite(ignoredN) ? ignoredN : undefined,
    };
  }, [paramoptSearchSpaceQuery.data]);

  const paramoptSpaceRaw = useMemo(() => {
    try {
      return JSON.stringify(paramoptSearchSpaceQuery.data ?? {}, null, 2);
    } catch {
      return '{}';
    }
  }, [paramoptSearchSpaceQuery.data]);

  const paramoptTemplateText = useMemo(() => {
    const d = paramoptTemplateQuery.data as { template?: string; templates?: Record<string, string> } | undefined;
    const one = String(d?.template ?? '').trim();
    if (one) return one;
    const all = d?.templates ?? {};
    const v = String((all as Record<string, unknown>)[paramoptTemplateKind] ?? '').trim();
    return v;
  }, [paramoptTemplateQuery.data, paramoptTemplateKind]);

  const paramoptTemplateVersionText = useMemo(() => {
    const d = paramoptTemplateQuery.data as { version?: string; updated_at?: string } | undefined;
    const v = String(d?.version ?? '').trim();
    const u = String(d?.updated_at ?? '').trim();
    if (v && u) return `${v} · ${u}`;
    if (v) return v;
    if (u) return u;
    return '';
  }, [paramoptTemplateQuery.data]);

  const paramoptRunMutation = useMutation({
    mutationFn: async () => {
      const sid = String(effectiveParamoptStrategy || '').trim();
      const traceId = paramoptForceNew ? `ui_bayes_strategy_${sid}_${Date.now()}` : `${selectedPlanId}__${sid}`;
      setParamoptTraceId(traceId);
      setParamoptResult('');
      const payload = {
        trace_id: traceId,
        mode: paramoptMode,
        opt_class: 'strategy',
        strategy_id: sid,
        family: String(paramoptFamily || 'xgb').trim() || 'xgb',
        eval_mode: paramoptEvalMode,
        folds: Math.max(1, Math.trunc(Number(paramoptFolds) || 2)),
        n_init: Math.max(0, Math.trunc(Number(paramoptNInit) || 2)),
        n_iter: Math.max(1, Math.trunc(Number(paramoptNIter) || 3)),
        skip_robustness: Boolean(paramoptSkipRobustness),
        include_suggest_only: true,
        min_trades_7d: Math.max(0, Math.trunc(Number(paramoptMinTrades7d) || 0)),
        min_effective_days_7d: Math.max(0, Math.trunc(Number(paramoptMinEffectiveDays7d) || 0)),
        fallback_backtest: true,
        backtest_strategy: sid || undefined,
        domain_main: String(paramoptDomainMain || '').trim() || undefined,
        challenge_set: String(paramoptChallengeSet || '').trim() || undefined,
        backtest_config: paramoptEvalMode === 'backtest' ? String(paramoptBacktestConfig || '').trim() || 'user_data/config_local_backtest.json' : undefined,
        backtest_timerange: paramoptEvalMode === 'backtest' ? String(paramoptBacktestTimerange || '').trim() || undefined : undefined,
        backtest_timeout_sec: paramoptEvalMode === 'backtest' ? Math.max(30, Math.trunc(Number(paramoptBacktestTimeoutSec) || 1800)) : undefined,
        plan_id: selectedPlanId,
        step_id: `strategy:${sid}`,
        step_seq: 1,
        plan: { plan_id: selectedPlanId, step_id: `strategy:${sid}`, step_seq: 1, created_by: 'ui.strategy', created_at: Date.now() },
        context: { idempotency_key: selectedIdempotencyKey },
      } as const;
      return (await api.post('/agent/paramopt/run', payload, { timeout: 300000 })).data;
    },
    onSuccess: (res) => {
      setParamoptResult(JSON.stringify(res ?? {}, null, 2));
      queryClient.invalidateQueries({ queryKey: ['agent', 'observability', 'paramopt', 'recent'] });
    },
    onError: async (err) => {
      const base = _apiErrText(err);
      const tid = String(paramoptTraceId || '').trim();
      const info = await resolveParamoptErrorByTrace(tid, base);
      setParamoptResult(String(info.message || base));
      queryClient.invalidateQueries({ queryKey: ['agent', 'observability', 'paramopt', 'recent'] });
    },
  });

  const paramoptBatchMutation = useMutation({
    mutationFn: async (runMode: 'qa' | 'full' = 'full') => {
      const isQa = runMode === 'qa';
      const bucket = _utcYmd(Date.now());
      const n = Math.max(1, Math.min(20, Math.trunc(Number(paramoptTopN) || 3)));
      const family = String(paramoptFamily || 'xgb').trim() || 'xgb';
      const evalMode = isQa ? 'backtest' : paramoptEvalMode;
      const nInit = isQa ? 0 : Math.max(0, Math.trunc(Number(paramoptNInit) || 2));
      const nIter = isQa ? 1 : Math.max(1, Math.trunc(Number(paramoptNIter) || 3));
      const minTrades7d = isQa ? 0 : Math.max(0, Math.trunc(Number(paramoptMinTrades7d) || 0));
      const minEffectiveDays7d = isQa ? 0 : Math.max(0, Math.trunc(Number(paramoptMinEffectiveDays7d) || 0));
      const runTs = Date.now();
      const planId = `ui_paramopt_topn_${bucket}_${paramoptMode}_${evalMode}_${family}_n${n}_${runMode}_${runTs}`;
      setParamoptBatchPlanId(planId);
      setParamoptBatchResult('');
      const selected = topNByWeight.slice(0, n);
      const initItems = selected.map((sid, idx) => {
        const seq = idx + 1;
        return {
          strategy_id: sid,
          step_seq: seq,
          step_id: `topn:${seq}:${sid}`,
          trace_id: `${planId}__${seq}__${sid}`,
          status: 'pending',
        };
      });
      setParamoptBatchItems(initItems);

      const reports: Array<Record<string, unknown>> = [];
      for (const it of initItems) {
        const sid = String(it.strategy_id || '').trim();
        const last = lastParamoptByStrategy.get(sid);
        const lastTs = _ms(last?.ts);
        const remain = lastTs > 0 ? (lastTs + cooldownMs - Date.now()) : 0;
        const inCooldown = remain > 0;
        if (inCooldown && !paramoptIgnoreCooldown) {
          setParamoptBatchItems((prev) => prev.map((x) => (x.trace_id === it.trace_id ? { ...x, status: 'skipped_cooldown', error: `cooldown:${_cooldownText(remain)}` } : x)));
          reports.push({ strategy_id: sid, trace_id: it.trace_id, skipped: true, reason: 'cooldown', remain_ms: remain });
          continue;
        }
        setParamoptBatchItems((prev) => prev.map((x) => (x.trace_id === it.trace_id ? { ...x, status: 'running' } : x)));
        const idem = `paramopt:topn:${planId}:${sid}`;
        const payload = {
          trace_id: it.trace_id,
          mode: paramoptMode,
          opt_class: 'strategy',
          strategy_id: sid,
          family,
          eval_mode: evalMode,
          folds: Math.max(1, Math.trunc(Number(paramoptFolds) || 2)),
          n_init: nInit,
          n_iter: nIter,
          skip_robustness: Boolean(paramoptSkipRobustness),
          include_suggest_only: true,
          min_trades_7d: minTrades7d,
          min_effective_days_7d: minEffectiveDays7d,
          fallback_backtest: true,
          backtest_strategy: sid || undefined,
          domain_main: String(paramoptDomainMain || '').trim() || undefined,
          challenge_set: String(paramoptChallengeSet || '').trim() || undefined,
          backtest_config: evalMode === 'backtest' ? String(paramoptBacktestConfig || '').trim() || 'user_data/config_local_backtest.json' : undefined,
          backtest_timerange: evalMode === 'backtest' ? String(paramoptBacktestTimerange || '').trim() || undefined : undefined,
          backtest_timeout_sec: evalMode === 'backtest' ? Math.max(30, Math.trunc(Number(paramoptBacktestTimeoutSec) || 1800)) : undefined,
          plan_id: planId,
          step_id: it.step_id,
          step_seq: it.step_seq,
          plan: { plan_id: planId, step_id: it.step_id, step_seq: it.step_seq, created_by: 'ui.strategy.topn', created_at: Date.now(), current_step_idx: it.step_seq },
          context: { idempotency_key: idem },
        } as const;
        try {
          const res = (await api.post('/agent/paramopt/run', payload, { timeout: 300000 })).data as Record<string, unknown>;
          const planIdRes = String((res as { plan_id?: unknown }).plan_id ?? '').trim() || planId;
          const reqPlanIdRes = String((res as { requested_plan_id?: unknown }).requested_plan_id ?? '').trim() || planId;
          reports.push({
            strategy_id: sid,
            trace_id: it.trace_id,
            ok: Boolean((res as { ok?: boolean }).ok),
            plan_id: planIdRes,
            requested_plan_id: reqPlanIdRes,
            retry_from_plan_id: (res as { retry_from_plan_id?: unknown }).retry_from_plan_id ?? null,
            response: res,
          });
          setParamoptBatchItems((prev) => prev.map((x) => (x.trace_id === it.trace_id ? { ...x, status: 'done' } : x)));
          setParamoptTraceId(String(it.trace_id));
        } catch (e) {
          const base = _apiErrText(e);
          const info = await resolveParamoptErrorByTrace(String(it.trace_id), base);
          const msg = String(info.message || base);
          const respData = (e as { response?: { data?: Record<string, unknown> } })?.response?.data;
          const planIdErr = String(respData?.plan_id ?? '').trim() || planId;
          const reqPlanIdErr = String(respData?.requested_plan_id ?? '').trim() || planId;
          reports.push({
            strategy_id: sid,
            trace_id: it.trace_id,
            ok: false,
            error: msg,
            reason_code: info.reason_code ?? (String(respData?.reason_code ?? '') || null),
            failed_stage: info.failed_stage ?? (String(respData?.failed_stage ?? '') || null),
            plan_id: planIdErr,
            requested_plan_id: reqPlanIdErr,
            retry_from_plan_id: (respData?.retry_from_plan_id ?? null),
          });
          setParamoptBatchItems((prev) => prev.map((x) => (x.trace_id === it.trace_id ? { ...x, status: 'error', error: msg } : x)));
        } finally {
          queryClient.invalidateQueries({ queryKey: ['agent', 'observability', 'paramopt', 'recent'] });
        }
      }
      setParamoptBatchResult(JSON.stringify({ ok: true, plan_id: planId, items: reports }, null, 2));
      return { ok: true, plan_id: planId, items: reports };
    },
  });

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>在用策略</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <div className="text-xs text-slate-500 mb-1">Trigger coin</div>
              <Input value={triggerCoin} onChange={(e) => setTriggerCoin(e.target.value)} placeholder="BTC" />
            </div>
            <div className="flex items-end gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={triggerEmit} onChange={(e) => setTriggerEmit(e.target.checked)} />
                emit
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={triggerDecision} onChange={(e) => setTriggerDecision(e.target.checked)} />
                trigger_decision
              </label>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">Last trigger result</div>
              <div className="text-xs text-slate-700 break-all border rounded bg-white p-2 min-h-10">
                {triggerResult || '-'}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Feeder</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant={feeder.enabled ? 'secondary' : 'outline'}>enabled: {feeder.enabled ? 'true' : 'false'}</Badge>
            <Badge variant={useCore ? 'secondary' : 'outline'}>use_core: {useCore ? 'true' : 'false'}</Badge>
            {feederIssues.invalid.length ? (
              <Badge variant="destructive">invalid_strategy: {feederIssues.invalid.join(',')}</Badge>
            ) : null}
            {feederIssues.duplicates.length ? (
              <Badge variant="destructive">duplicate_strategy: {feederIssues.duplicates.join(',')}</Badge>
            ) : null}
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">period_seconds</span>
              <Input
                className="w-24"
                type="number"
                value={String(feeder.period)}
                onChange={(e) => {
                  const v = Number(e.target.value) || 30;
                  setFeederDraft((prev) => ({ ...(prev ?? derivedFeederDraft), period: v }));
                }}
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={feeder.enabled}
                onChange={(e) => setFeederDraft((prev) => ({ ...(prev ?? derivedFeederDraft), enabled: e.target.checked }))}
              />
              开启 Feeder
            </label>
            <Button size="sm" onClick={saveFeeder} disabled={feederSaveMutation.isPending || !canSaveFeeder}>
              保存
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => feederUseCoreMutation.mutate({ enabled: !useCore, period: Math.max(5, Math.trunc(Number(feeder.period) || 30)) })}
              disabled={feederUseCoreMutation.isPending}
            >
              {useCore ? '关闭 core' : '启用 core'}
            </Button>
          </div>

          <div className="space-y-3">
            {feeder.rows.length ? feeder.rows.map((r, idx) => (
              <div key={`${r.strategy_id}_${idx}`} className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center">
                <div className="md:col-span-2">
                  <select
                    className="w-full rounded border px-2 py-1 text-sm"
                    value={r.strategy_id}
                    onChange={(e) => {
                      const v = String(e.target.value || '').trim();
                      setFeederDraft((prev) => {
                        const base = prev ?? derivedFeederDraft;
                        return { ...base, rows: base.rows.map((x, i) => (i === idx ? { ...x, strategy_id: v } : x)) };
                      });
                    }}
                  >
                    {feederStrategyOptions.map((sid) => (
                      <option key={sid} value={sid}>
                        {sid}
                      </option>
                    ))}
                    {!feederStrategyOptions.includes(r.strategy_id) && r.strategy_id ? (
                      <option value={r.strategy_id}>{r.strategy_id}</option>
                    ) : null}
                  </select>
                </div>
                <div className="md:col-span-6">
                  <Input
                    value={r.coinsText}
                    onChange={(e) => {
                      const v = e.target.value;
                      setFeederDraft((prev) => {
                        const base = prev ?? derivedFeederDraft;
                        return { ...base, rows: base.rows.map((x, i) => (i === idx ? { ...x, coinsText: v } : x)) };
                      });
                    }}
                    placeholder="BTC,ETH,SOL"
                  />
                </div>
                <div className="md:col-span-2 flex items-center gap-3">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={r.emit}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setFeederDraft((prev) => {
                          const base = prev ?? derivedFeederDraft;
                          return { ...base, rows: base.rows.map((x, i) => (i === idx ? { ...x, emit: checked } : x)) };
                        });
                      }}
                    />
                    emit
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={r.trigger_decision}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setFeederDraft((prev) => {
                          const base = prev ?? derivedFeederDraft;
                          return { ...base, rows: base.rows.map((x, i) => (i === idx ? { ...x, trigger_decision: checked } : x)) };
                        });
                      }}
                    />
                    decision
                  </label>
                </div>
                <div className="md:col-span-2 flex justify-end">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setFeederDraft((prev) => {
                      const base = prev ?? derivedFeederDraft;
                      return { ...base, rows: base.rows.filter((_, i) => i !== idx) };
                    })}
                  >
                    删除
                  </Button>
                </div>
              </div>
            )) : <div className="text-sm text-slate-500">暂无 feeder 规则</div>}
          </div>
          <div className="text-xs text-slate-500">
            coins 仅在手工 tick/调试路径可能生效；周期 Feeder 默认按 Universe core 扫描。以 tracker.feeders 为准。
          </div>

          <Button
            size="sm"
            variant="outline"
            onClick={() => setFeederDraft((prev) => {
              const base = prev ?? derivedFeederDraft;
              const sid0 = feederStrategyOptions[0] ?? 'Strategy005';
              return { ...base, rows: [...base.rows, { strategy_id: sid0, coinsText: '', emit: true, trigger_decision: true }] };
            })}
          >
            新增策略 feeder
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle>策略贝叶斯优化（Strategy-level）</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">/agent/paramopt/run</Badge>
            <Link to="/agent/observability"><Button size="sm" variant="outline">观测</Button></Link>
            {paramoptTraceId.trim() ? (
              <Link to={`/agent/ops?trace_id=${encodeURIComponent(paramoptTraceId)}#pipeline`}>
                <Button size="sm" variant="outline">Ops</Button>
              </Link>
            ) : null}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <div className="text-xs text-slate-500 mb-1">strategy_id</div>
              <select
                className="w-full rounded border px-2 py-2 text-sm bg-white"
                value={effectiveParamoptStrategy}
                onChange={(e) => setParamoptSelectedStrategy(String(e.target.value ?? '').trim())}
              >
                {paramoptStrategyOptions.map((sid) => (
                  <option key={sid} value={sid}>
                    {sid}{activeStrategyIds.includes(sid) ? ' (active)' : ''}
                  </option>
                ))}
              </select>
              <div className="mt-1 text-xs text-slate-500">group_id: {paramoptMeta.group_id || '-'}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">mode / eval_mode</div>
              <div className="flex gap-2">
                <select
                  className="w-1/2 rounded border px-2 py-2 text-sm bg-white"
                  value={paramoptMode}
                  onChange={(e) => setParamoptMode((String(e.target.value ?? 'suggest') as 'suggest' | 'sandbox'))}
                >
                  <option value="suggest">suggest</option>
                  <option value="sandbox">sandbox</option>
                </select>
                <select
                  className="w-1/2 rounded border px-2 py-2 text-sm bg-white"
                  value={paramoptEvalMode}
                  onChange={(e) => setParamoptEvalMode((String(e.target.value ?? 'rolling') as 'rolling' | 'backtest'))}
                >
                  <option value="rolling">rolling</option>
                  <option value="backtest">backtest</option>
                </select>
              </div>
              <label className="mt-2 flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4" checked={paramoptSkipRobustness} onChange={(e) => setParamoptSkipRobustness(e.target.checked)} />
                skip_robustness
              </label>
            </div>
            <div>
              <div className="text-xs text-slate-500 mb-1">family / folds</div>
              <div className="flex gap-2">
                <Input value={paramoptFamily} onChange={(e) => setParamoptFamily(String(e.target.value ?? ''))} placeholder="xgb" />
                <Input type="number" value={String(paramoptFolds)} onChange={(e) => setParamoptFolds(Number(e.target.value) || 2)} placeholder="2" />
              </div>
              <div className="mt-2 text-xs text-slate-500 mb-1">n_init / n_iter</div>
              <div className="flex gap-2">
                <Input type="number" value={String(paramoptNInit)} onChange={(e) => setParamoptNInit(Number(e.target.value) || 0)} />
                <Input type="number" value={String(paramoptNIter)} onChange={(e) => setParamoptNIter(Number(e.target.value) || 1)} />
              </div>
              <div className="mt-2 text-xs text-slate-500 mb-1">min_trades_7d / min_effective_days_7d</div>
              <div className="flex gap-2">
                <Input type="number" value={String(paramoptMinTrades7d)} onChange={(e) => setParamoptMinTrades7d(Math.max(0, Number(e.target.value) || 0))} />
                <Input type="number" value={String(paramoptMinEffectiveDays7d)} onChange={(e) => setParamoptMinEffectiveDays7d(Math.max(0, Number(e.target.value) || 0))} />
              </div>
              {paramoptEvalMode === 'backtest' ? (
                <>
                  <div className="mt-2 text-xs text-slate-500 mb-1">backtest_timerange / timeout_sec</div>
                  <div className="flex gap-2">
                    <Input value={paramoptBacktestTimerange} onChange={(e) => setParamoptBacktestTimerange(String(e.target.value ?? ''))} placeholder="20251115-20260115" />
                    <Input type="number" value={String(paramoptBacktestTimeoutSec)} onChange={(e) => setParamoptBacktestTimeoutSec(Number(e.target.value) || 1800)} />
                  </div>
                  <div className="mt-2 text-xs text-slate-500 mb-1">backtest_config</div>
                  <Input value={paramoptBacktestConfig} onChange={(e) => setParamoptBacktestConfig(String(e.target.value ?? ''))} placeholder="user_data/config_local_backtest.json" />
                  <div className="mt-2 text-xs text-slate-500 mb-1">domain_main / challenge_set</div>
                  <div className="flex gap-2">
                    <Input value={paramoptDomainMain} onChange={(e) => setParamoptDomainMain(String(e.target.value ?? ''))} placeholder="BTC/USDT:USDT" />
                    <Input value={paramoptChallengeSet} onChange={(e) => setParamoptChallengeSet(String(e.target.value ?? ''))} placeholder="ETH/USDT:USDT,SOL/USDT:USDT" />
                  </div>
                </>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              onClick={() => paramoptRunMutation.mutate()}
              disabled={paramoptRunMutation.isPending || !effectiveParamoptStrategy.trim() || (selectedInCooldown && !paramoptIgnoreCooldown)}
            >
              运行一次（贝叶斯优化）
            </Button>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4" checked={paramoptIgnoreCooldown} onChange={(e) => setParamoptIgnoreCooldown(e.target.checked)} />
              忽略冷却
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4" checked={paramoptForceNew} onChange={(e) => setParamoptForceNew(e.target.checked)} />
              强制新 trace
            </label>
            <Badge variant="outline">prefixes: {paramoptPrefixes.length ? paramoptPrefixes.join(', ') : '-'}</Badge>
            <Badge variant="outline">plan_id: {selectedPlanId}</Badge>
            <Badge variant="outline">idempotency: {selectedIdempotencyKey}</Badge>
            {selectedLastTsMs > 0 ? (
              <Badge variant={selectedInCooldown ? 'destructive' : 'secondary'}>
                last: {_fmtDateTimeFromMs(selectedLastTsMs)}{selectedInCooldown ? ` (cooldown ${_cooldownText(selectedCooldownRemainMs)})` : ''}
              </Badge>
            ) : (
              <Badge variant="outline">last: -</Badge>
            )}
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">recent_days</span>
              <Input className="w-24" type="number" value={String(paramoptDays)} onChange={(e) => setParamoptDays(Number(e.target.value) || 7)} />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">cooldown_h</span>
              <Input className="w-24" type="number" value={String(paramoptCooldownHours)} onChange={(e) => setParamoptCooldownHours(Number(e.target.value) || 0)} />
            </div>
          </div>

          <div className="border rounded bg-white">
            <div className="px-3 py-2 text-xs font-semibold text-slate-600 border-b">Top-N 批量队列（按权重）</div>
            <div className="px-3 py-2 space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-500">top_n</span>
                  <Input className="w-24" type="number" value={String(paramoptTopN)} onChange={(e) => setParamoptTopN(Number(e.target.value) || 3)} />
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => paramoptBatchMutation.mutate('qa')}
                  disabled={paramoptBatchMutation.isPending || topNByWeight.length === 0}
                >
                  链路验收 Top-N（backtest + n_iter=1）
                </Button>
                <Button
                  size="sm"
                  onClick={() => paramoptBatchMutation.mutate('full')}
                  disabled={paramoptBatchMutation.isPending || topNByWeight.length === 0}
                >
                  正式优化 Top-N（使用当前参数）
                </Button>
                {paramoptBatchPlanId.trim() ? <Badge variant="outline">plan_id: {paramoptBatchPlanId}</Badge> : null}
              </div>
              <div className="flex flex-wrap gap-2">
                {topNByWeight.map((sid) => {
                  const last = lastParamoptByStrategy.get(String(sid));
                  const lastTs = _ms(last?.ts);
                  const remain = lastTs > 0 ? (lastTs + cooldownMs - nowMs) : 0;
                  const inCd = remain > 0;
                  return (
                    <Badge key={sid} variant={inCd ? 'destructive' : 'secondary'}>
                      {sid}{inCd ? ` (${_cooldownText(remain)})` : ''}
                    </Badge>
                  );
                })}
              </div>

              {paramoptBatchItems.length ? (
                <div className="border rounded">
                  <div className="grid grid-cols-12 gap-2 px-2 py-2 text-xs text-slate-500 border-b">
                    <div className="col-span-2">seq</div>
                    <div className="col-span-3">strategy_id</div>
                    <div className="col-span-2">status</div>
                    <div className="col-span-3">trace_id</div>
                    <div className="col-span-2">error</div>
                  </div>
                  <div className="max-h-56 overflow-auto text-xs">
                    {paramoptBatchItems.map((it) => (
                      <div key={it.trace_id} className="grid grid-cols-12 gap-2 px-2 py-2 border-b last:border-b-0">
                        <div className="col-span-2">{String(it.step_seq)}</div>
                        <div className="col-span-3">{it.strategy_id}</div>
                        <div className="col-span-2">{it.status}</div>
                        <div className="col-span-3 truncate">
                          <Link to={`/agent/ops?trace_id=${encodeURIComponent(String(it.trace_id))}#pipeline`}>
                            {String(it.trace_id)}
                          </Link>
                        </div>
                        <div className="col-span-2 truncate">{String(it.error ?? '')}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {paramoptBatchResult.trim() ? (
                <div className="border rounded bg-white">
                  <div className="px-3 py-2 text-xs font-semibold text-slate-600 border-b">批量回执</div>
                  <pre className="px-3 py-2 text-xs overflow-auto max-h-56">{paramoptBatchResult}</pre>
                </div>
              ) : null}

              <div className="border rounded bg-white">
                <div className="px-3 py-2 text-xs font-semibold text-slate-600 border-b flex items-center justify-between gap-2">
                  <span>验收模板（空白表单块）</span>
                  {paramoptTemplateVersionText ? <Badge variant="outline">{paramoptTemplateVersionText}</Badge> : null}
                </div>
                <div className="px-3 py-2 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" variant={paramoptTemplateKind === 'base' ? 'default' : 'outline'} onClick={() => setParamoptTemplateKind('base')}>基础版</Button>
                    <Button size="sm" variant={paramoptTemplateKind === 'daily' ? 'default' : 'outline'} onClick={() => setParamoptTemplateKind('daily')}>日报简版</Button>
                    <Button size="sm" variant={paramoptTemplateKind === 'approval' ? 'default' : 'outline'} onClick={() => setParamoptTemplateKind('approval')}>审批详版</Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        const text = String(paramoptTemplateText || '').trim();
                        if (!text) return;
                        try {
                          await navigator.clipboard.writeText(text);
                          setParamoptResult('模板已复制到剪贴板');
                        } catch (e) {
                          setParamoptResult(String((e as Error)?.message ?? e));
                        }
                      }}
                    >
                      复制模板
                    </Button>
                  </div>
                  <pre className="text-xs overflow-auto max-h-48 border rounded bg-slate-50 p-2">{paramoptTemplateText || '模板加载中…'}</pre>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="border rounded bg-white">
              <div className="px-3 py-2 text-xs font-semibold text-slate-600 border-b">参数包预览（search_space 过滤）</div>
              <div className="px-3 py-2 text-sm">
                {paramoptSearchSpaceQuery.isFetching ? '加载中…' : null}
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                  <Badge variant="outline">selected_n: {paramoptSpaceSelection.selected_n == null ? '-' : String(paramoptSpaceSelection.selected_n)}</Badge>
                  <Badge variant="outline">ignored_n: {paramoptSpaceSelection.ignored_n == null ? '-' : String(paramoptSpaceSelection.ignored_n)}</Badge>
                </div>
                {!paramoptSearchSpaceQuery.isFetching && Number(paramoptSpaceSelection.selected_n) === 0 ? (
                  <div className="mb-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                    <div>缺少策略参数契约（search_space 未声明）</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setShowParamContractHelp(true)}
                      >
                        查看策略参数契约说明
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => setShowParamoptSpaceRaw((v) => !v)}>
                        {showParamoptSpaceRaw ? '收起 search_space 原始 JSON' : '打开 search_space 原始 JSON'}
                      </Button>
                    </div>
                  </div>
                ) : null}
                {showParamoptSpaceRaw ? (
                  <div className="mb-2 border rounded bg-slate-50">
                    <div className="px-2 py-1 text-xs text-slate-600 border-b">search_space 原始返回</div>
                    <pre className="px-2 py-2 text-xs overflow-auto max-h-56">{paramoptSpaceRaw}</pre>
                  </div>
                ) : null}
                {paramoptSpaceItems.length ? (
                  <div className="max-h-56 overflow-auto">
                    {paramoptSpaceItems.slice(0, 80).map((it) => (
                      <div key={it.key} className="flex justify-between gap-4 py-1 border-b last:border-b-0">
                        <span className="text-slate-700">{it.key}</span>
                        <span className="text-xs text-slate-500">
                          {String(it.apply_mode ?? '-')}{it.range?.min != null && it.range?.max != null ? ` [${String(it.range.min)}..${String(it.range.max)}]` : ''}
                        </span>
                      </div>
                    ))}
                    {paramoptSpaceItems.length > 80 ? <div className="text-xs text-slate-500 py-1">仅展示前 80 项</div> : null}
                  </div>
                ) : (
                  <div className="text-xs text-slate-500">无匹配项（可能该策略尚未映射到 search_space）</div>
                )}
              </div>
            </div>
            <div className="border rounded bg-white">
              <div className="px-3 py-2 text-xs font-semibold text-slate-600 border-b">最近 trace（opt_class=strategy）</div>
              <div className="px-3 py-2 text-sm">
                {paramoptRecentRows.length ? (
                  <div className="space-y-2">
                    {paramoptRecentRows.map((it) => (
                      <div key={it.trace_id} className="border rounded p-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-xs text-slate-500">{_fmtDateTimeFromMs(Number(it.ts || 0))}</div>
                          <div className="flex items-center gap-2">
                            <Link to={`/agent/ops?trace_id=${encodeURIComponent(String(it.trace_id))}#pipeline`}>
                              <Button size="sm" variant="outline">{String(it.trace_id).slice(0, 14)}</Button>
                            </Link>
                            {it.ok == null ? <Badge variant="outline">ok -</Badge> : <Badge variant={it.ok ? 'secondary' : 'destructive'}>{String(Boolean(it.ok))}</Badge>}
                            <Badge variant={it.has_suggestion ? 'secondary' : 'outline'}>{it.has_suggestion ? 'DONE' : 'RUNNING'}</Badge>
                          </div>
                        </div>
                        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                          <div className="flex justify-between"><span className="text-slate-500">n_init</span><span>{it.n_init == null ? '-' : String(it.n_init)}</span></div>
                          <div className="flex justify-between"><span className="text-slate-500">n_iter</span><span>{it.n_iter == null ? '-' : String(it.n_iter)}</span></div>
                          <div className="flex justify-between"><span className="text-slate-500">selected</span><span>{it.selected_patch_n == null ? '-' : String(it.selected_patch_n)}</span></div>
                          <div className="flex justify-between"><span className="text-slate-500">apply</span><span>{String(it.apply_mode ?? '-')}</span></div>
                        </div>
                        {String(it.reason_code ?? '').trim() ? (
                          <div className="mt-1 text-xs text-slate-500">reason: {String(it.reason_code)}{String(it.failed_stage ?? '').trim() ? ` / ${String(it.failed_stage)}` : ''}</div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-slate-500">暂无数据（可先运行一次）</div>
                )}
              </div>
            </div>
          </div>

          <div className="border rounded bg-white">
            <div className="px-3 py-2 text-xs font-semibold text-slate-600 border-b">运行回执</div>
            <pre className="px-3 py-2 text-xs overflow-auto max-h-56">{paramoptResult || '-'}</pre>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {strategies.map((sid) => {
          const resp = paramsResp as StrategyParamsResponse | undefined;
          const meta = resp?.strategies?.[sid];
          const gid = String(meta?.group_id ?? '').trim();
          const fsid = String(meta?.feature_set_id ?? '').trim();
          const params = (meta?.params ?? {}) as Record<string, unknown>;
          const weight = Number(stratWeights[sid] ?? NaN);
          const openN = Number(openByStrategy[sid] ?? 0);
          const daily = pickPnl(dailyPnl, sid, gid);
          const weekly = pickPnl(weeklyPnl, sid, gid);
          const perf = stratPerfById[sid] ?? {};
          const feeder = feederStatsByStrategy[sid] ?? {};

          const kvs = Object.entries(params)
            .filter(([k]) => k)
            .map(([k, v]) => ({ k, v }));

          return (
            <Card key={sid}>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2 justify-between">
                  <span>{sid}</span>
                  <span className="flex flex-wrap gap-2">
                    {gid ? <Badge variant="outline">group: {gid}</Badge> : null}
                    {fsid ? <Badge variant="outline">feature: {fsid}</Badge> : null}
                    {Number.isFinite(weight) ? <Badge variant="secondary">w: {_fmt2(weight, 3)}</Badge> : <Badge variant="outline">w: -</Badge>}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="outline">open_positions: {openN}</Badge>
                  <Badge variant="outline">pf: {_fmt2(_asNum(perf.pf, NaN), 2)}</Badge>
                  <Badge variant="outline">maxdd: {_fmtPct(_asNum(perf.maxdd, NaN), 2)}</Badge>
                  <Badge variant="outline">n: {_fmt2(_asNum(perf.n, NaN), 0)}</Badge>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
                  <div className="flex justify-between"><span className="text-slate-500">daily_pnl</span><span>{daily.key ? `${daily.key}: ${_fmt2(daily.v, 2)}` : '-'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">weekly_pnl</span><span>{weekly.key ? `${weekly.key}: ${_fmt2(weekly.v, 2)}` : '-'}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">feeder.calls</span><span>{Number(feeder.calls ?? 0)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">feeder.ingested</span><span>{Number(feeder.ingested ?? 0)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">feeder.errors</span><span>{Number(feeder.errors ?? 0)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">feeder.null</span><span>{Number(feeder.null_signals ?? 0)}</span></div>
                </div>

                {kvs.length ? (
                  <div className="border rounded bg-white">
                    <div className="px-3 py-2 text-xs font-semibold text-slate-600 border-b">params</div>
                    <div className="px-3 py-2 space-y-1 text-sm">
                      {kvs.map(({ k, v }) => (
                        <div key={k} className="flex justify-between gap-4">
                          <span className="text-slate-600">{k}</span>
                          <span className="font-mono text-xs break-all">{String(v ?? '')}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-slate-500">No params</div>
                )}

                {canTrigger(sid) ? (
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">{triggerPath(sid)}</span>
                    <Button
                      size="sm"
                      onClick={() => triggerMutation.mutate({ strategy_id: sid, coin: triggerCoin.trim() })}
                      disabled={triggerMutation.isPending || !triggerCoin.trim()}
                    >
                      触发
                    </Button>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          );
        })}
      </div>
      {showParamContractHelp ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4" onClick={() => setShowParamContractHelp(false)}>
          <div className="w-full max-w-3xl rounded border bg-white shadow-lg" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <div className="text-sm font-semibold text-slate-700">策略参数契约最小模板</div>
              <Button size="sm" variant="outline" onClick={() => setShowParamContractHelp(false)}>关闭</Button>
            </div>
            <div className="px-4 py-3 space-y-3 text-sm max-h-[70vh] overflow-auto">
              <div className="text-slate-600">目标：让策略参数可被 ParamOpt 识别并可审计优化。每个可优化参数至少声明 key/type/range(or choices)/apply_mode/tag。</div>
              <div className="text-xs text-slate-500">命名建议：优先使用 {"{strategy_id}_*"}，如需组级共享再使用 {"{group_id}_*"}。</div>
              <pre className="text-xs bg-slate-50 border rounded p-3 overflow-auto">{`[
  {
    "key": "multigroup_entry_adx_min",
    "type": "float",
    "range": [10, 40],
    "step": 1,
    "apply_mode": "auto",
    "tag": "trend"
  },
  {
    "key": "multigroup_stop_loss_pct",
    "type": "float",
    "range": [-0.12, -0.01],
    "step": 0.005,
    "apply_mode": "suggest-only",
    "tag": "protection"
  },
  {
    "key": "multigroup_confirm_bars",
    "type": "int",
    "range": [1, 6],
    "step": 1,
    "apply_mode": "auto-tighten-only",
    "tag": "filter"
  }
]`}</pre>
              <div className="text-xs text-slate-500">校验要点：key 必须进入 search_space；type 与 range/choices 一致；apply_mode 与风控级别一致；tag 用于分组与解释。</div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};
