import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Link, useNavigate } from 'react-router-dom';
import {
  fetchAgentGovernancePolicy,
  fetchAgentObservabilityDaily,
  fetchAgentObservabilityParamoptRecent,
  fetchApprovalsSummary,
  fetchBacktestReportByZip,
  fetchConfig,
  fetchRolloutFreeze,
  fetchServingPipelineGuardEval,
  fetchServingPipelineState,
  fetchTrackerStats,
  fetchStrategyLibrarySnapshot,
  fetchAutomationCardsState,
  scanAgentGovernanceContamination,
} from '../lib/api';
import type {
  AgentGovernancePolicyResponse,
  AgentGovernanceScanContaminationResponse,
  AgentObservabilityDailyRow,
  AgentObservabilityParamoptRecentItem,
  ApprovalsSummaryResponse,
  BacktestReportResponse,
  Config,
  RolloutFreezeGetResponse,
  ServingPipelineGuardEvalResponse,
  ServingPipelineStateResponse,
  StrategyLibrarySnapshotRow,
  TrackerStats,
  AutomationCardsStateResponse,
  AutomationCardStateV1,
} from '../lib/api';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';
 
function _num(v: unknown, d = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}
 
function _fmt2(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined) return '-';
  const n = Number(x);
  if (!Number.isFinite(n)) return '-';
  return n.toFixed(digits);
}
 
function _countBy<T>(items: T[], getKey: (it: T) => string): Array<{ key: string; n: number }> {
  const m = new Map<string, number>();
  for (const it of items) {
    const k = String(getKey(it) || '').trim() || '-';
    m.set(k, (m.get(k) ?? 0) + 1);
  }
  return Array.from(m.entries())
    .map(([key, n]) => ({ key, n }))
    .sort((a, b) => b.n - a.n);
}
 
function _extractBacktestMetrics(rep: BacktestReportResponse | null | undefined): Record<string, number | null> {
  const aligned = (rep as { aligned_metrics?: Record<string, unknown> | null } | null | undefined)?.aligned_metrics ?? null;
  if (aligned && typeof aligned === 'object') {
    return {
      total_pct: aligned.total_pct == null ? null : _num(aligned.total_pct, 0),
      maxdd_pct: aligned.maxdd_pct == null ? null : _num(aligned.maxdd_pct, 0),
      calmar: aligned.calmar == null ? null : _num(aligned.calmar, 0),
      pf: aligned.pf == null ? null : _num(aligned.pf, 0),
      winrate: aligned.winrate == null ? null : _num(aligned.winrate, 0),
      trades: aligned.trades == null ? null : _num(aligned.trades, 0),
    };
  }
  const sum = (rep as { metrics_summary?: Record<string, unknown> | null } | null | undefined)?.metrics_summary ?? null;
  if (sum && typeof sum === 'object') {
    return {
      total_pct: sum.profit_total_pct == null ? null : _num(sum.profit_total_pct, 0),
      maxdd_pct: sum.max_drawdown_account == null ? null : _num(sum.max_drawdown_account, 0),
      calmar: sum.calmar == null ? null : _num(sum.calmar, 0),
      pf: sum.profit_factor == null ? null : _num(sum.profit_factor, 0),
      winrate: sum.winrate == null ? null : _num(sum.winrate, 0),
      trades: sum.trades == null ? null : _num(sum.trades, 0),
    };
  }
  return { total_pct: null, maxdd_pct: null, calmar: null, pf: null, winrate: null, trades: null };
}

function _extractEquity(rep: BacktestReportResponse | null | undefined): Array<{ ts: number; equity_u: number }> {
  const anyRep = rep as Record<string, unknown> | null | undefined;
  const candidates: unknown[] = [];
  if (anyRep && typeof anyRep === 'object') {
    candidates.push(anyRep['equity_curve'], anyRep['equity']);
    const aligned = anyRep['aligned_metrics'];
    if (aligned && typeof aligned === 'object') {
      candidates.push((aligned as Record<string, unknown>)['equity_curve'], (aligned as Record<string, unknown>)['equity']);
    }
  }
  for (const c of candidates) {
    if (!Array.isArray(c)) continue;
    const out: Array<{ ts: number; equity_u: number }> = [];
    for (const it of c) {
      if (!it || typeof it !== 'object') continue;
      const o = it as Record<string, unknown>;
      const ts = Number(o.ts);
      const eq = Number(o.equity_u);
      if (!Number.isFinite(ts) || !Number.isFinite(eq)) continue;
      out.push({ ts, equity_u: eq });
    }
    if (out.length >= 2) {
      out.sort((a, b) => a.ts - b.ts);
      return out;
    }
  }
  return [];
}
 
function _fmtPct(x: number | null | undefined, digits = 2): string {
  if (x === null || x === undefined) return '-';
  const n = Number(x);
  if (!Number.isFinite(n)) return '-';
  return `${(n * 100).toFixed(digits)}%`;
}

function _extractEval(rep: BacktestReportResponse | null | undefined): { score: number | null; hard_fails_n: number | null } {
  const ev = (rep as { eval?: unknown } | null | undefined)?.eval;
  if (!ev || typeof ev !== 'object') return { score: null, hard_fails_n: null };
  const o = ev as Record<string, unknown>;
  const score = o.score == null ? null : _num(o.score, NaN);
  const hf = Array.isArray(o.hard_fails) ? o.hard_fails.length : null;
  return { score: Number.isFinite(score as number) ? (score as number) : null, hard_fails_n: hf };
}

function _fmtDateFromMs(ts: number): string {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return '-';
  const ms = n < 1e11 ? n * 1000 : n;
  return new Date(ms).toISOString().slice(0, 10);
}

function _fmtDateTimeFromMs(ts: number): string {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return '-';
  const ms = n < 1e11 ? n * 1000 : n;
  return new Date(ms).toLocaleString();
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
 
export const AgentObservabilityPage: React.FC = () => {
  const nav = useNavigate();
  const [days, setDays] = useState<number>(30);
  const [baselineZip, setBaselineZip] = useState<string>('');
  const [exploreZip, setExploreZip] = useState<string>('');
  const [selectedDay, setSelectedDay] = useState<string>('');
  const [traceSearch, setTraceSearch] = useState<string>('');
 
  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: fetchConfig,
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const trackerQuery = useQuery({
    queryKey: ['tracker', 'stats', 'ui'],
    queryFn: () => fetchTrackerStats({ sync: false, view: 'ui' }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const approvalsQuery = useQuery({
    queryKey: ['approvals', 'summary', 'observability'],
    queryFn: () => fetchApprovalsSummary({ max_lines: 2000, max_bytes: 800000 }),
    refetchInterval: 20000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const freezeQuery = useQuery({
    queryKey: ['rollout', 'freeze'],
    queryFn: fetchRolloutFreeze,
    refetchInterval: 20000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const servingStateQuery = useQuery({
    queryKey: ['serving', 'pipeline', 'state'],
    queryFn: fetchServingPipelineState,
    refetchInterval: 20000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const servingGuardQuery = useQuery({
    queryKey: ['serving', 'guard', 'eval'],
    queryFn: fetchServingPipelineGuardEval,
    refetchInterval: 20000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const cardsStateQuery = useQuery({
    queryKey: ['automation', 'cards', 'state', 'observability'],
    queryFn: () => fetchAutomationCardsState({ details: false }),
    refetchInterval: 20000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const governancePolicyQuery = useQuery({
    queryKey: ['agent', 'governance', 'policy'],
    queryFn: fetchAgentGovernancePolicy,
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const contaminationQuery = useQuery({
    queryKey: ['agent', 'governance', 'contamination', { limit: 50 }],
    queryFn: () => scanAgentGovernanceContamination({ limit: 50 }),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const dailyQuery = useQuery({
    queryKey: ['agent', 'observability', 'daily', { days }],
    queryFn: () => fetchAgentObservabilityDaily({ days }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });
 
  const paramoptQuery = useQuery({
    queryKey: ['agent', 'observability', 'paramopt', { limit: 50, days }],
    queryFn: () => fetchAgentObservabilityParamoptRecent({ limit: 50, days }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });
 
  const strategyLibQuery = useQuery({
    queryKey: ['strategy', 'library', 'snapshot', 'observability'],
    queryFn: () => fetchStrategyLibrarySnapshot(),
    refetchInterval: 60000,
    refetchOnWindowFocus: false,
  });
 
  const baselineReportQuery = useQuery({
    queryKey: ['backtest', 'report', 'by_zip', { zip: baselineZip.trim() }],
    queryFn: () => fetchBacktestReportByZip({ zip: baselineZip.trim() }),
    enabled: Boolean(baselineZip.trim()),
    refetchOnWindowFocus: false,
    retry: false,
  });
 
  const exploreReportQuery = useQuery({
    queryKey: ['backtest', 'report', 'by_zip', { zip: exploreZip.trim() }],
    queryFn: () => fetchBacktestReportByZip({ zip: exploreZip.trim() }),
    enabled: Boolean(exploreZip.trim()),
    refetchOnWindowFocus: false,
    retry: false,
  });
 
  const dailyRows = useMemo(() => {
    const rows = (dailyQuery.data as { rows?: AgentObservabilityDailyRow[] } | undefined)?.rows;
    if (!Array.isArray(rows)) return [];
    return rows.map((r) => ({
      ...r,
      paramopt_runs_strategy: _num((r as Record<string, unknown>).paramopt_runs_strategy, 0),
      paramopt_runs_system: _num((r as Record<string, unknown>).paramopt_runs_system, 0),
      paramopt_suggestions_strategy: _num((r as Record<string, unknown>).paramopt_suggestions_strategy, 0),
      paramopt_suggestions_system: _num((r as Record<string, unknown>).paramopt_suggestions_system, 0),
      approvals_strategy: _num((r as Record<string, unknown>).approvals_strategy, 0),
      approvals_system: _num((r as Record<string, unknown>).approvals_system, 0),
    }));
  }, [dailyQuery.data]);

  const last24h = useMemo(() => {
    const x = (dailyQuery.data as { last_24h?: Record<string, unknown> } | undefined)?.last_24h ?? null;
    if (!x || typeof x !== 'object') {
      return {
        bugfix_ok: 0,
        bugfix_fail: 0,
        paramopt_runs: 0,
        paramopt_runs_strategy: 0,
        paramopt_runs_system: 0,
        paramopt_suggestions: 0,
        paramopt_suggestions_strategy: 0,
        paramopt_suggestions_system: 0,
        strategy_imports: 0,
        shadow_candidates: 0,
        rollbacks: 0,
        approvals: 0,
        approvals_strategy: 0,
        approvals_system: 0,
        closure_rate: 0,
        timeout_rate: 0,
        paramopt_timeouts: 0,
        mttr_minutes: 0,
        system_gate_kpi_block_count: 0,
        system_gate_plan_block_count: 0,
        top_reason_codes: [] as Array<{ reason_code: string; count: number }>,
      };
    }
    const o = x as Record<string, unknown>;
    return {
      bugfix_ok: _num(o.bugfix_ok, 0),
      bugfix_fail: _num(o.bugfix_fail, 0),
      paramopt_runs: _num(o.paramopt_runs, 0),
      paramopt_runs_strategy: _num(o.paramopt_runs_strategy, 0),
      paramopt_runs_system: _num(o.paramopt_runs_system, 0),
      paramopt_suggestions: _num(o.paramopt_suggestions, 0),
      paramopt_suggestions_strategy: _num(o.paramopt_suggestions_strategy, 0),
      paramopt_suggestions_system: _num(o.paramopt_suggestions_system, 0),
      strategy_imports: _num(o.strategy_imports, 0),
      shadow_candidates: _num(o.shadow_candidates, 0),
      rollbacks: _num(o.rollbacks, 0),
      approvals: _num(o.approvals, 0),
      approvals_strategy: _num(o.approvals_strategy, 0),
      approvals_system: _num(o.approvals_system, 0),
      closure_rate: Number(o.closure_rate ?? 0),
      timeout_rate: Number(o.timeout_rate ?? 0),
      paramopt_timeouts: _num(o.paramopt_timeouts, 0),
      mttr_minutes: Number(o.mttr_minutes ?? 0),
      system_gate_kpi_block_count: _num(o.system_gate_kpi_block_count, 0),
      system_gate_plan_block_count: _num(o.system_gate_plan_block_count, 0),
      top_reason_codes: Array.isArray(o.top_reason_codes) ? (o.top_reason_codes as Array<{ reason_code: string; count: number }>) : [],
    };
  }, [dailyQuery.data]);
 
  const paramoptItems: AgentObservabilityParamoptRecentItem[] = useMemo(() => {
    const items = (paramoptQuery.data as { items?: AgentObservabilityParamoptRecentItem[] } | undefined)?.items;
    if (!Array.isArray(items)) return [];
    return items;
  }, [paramoptQuery.data]);
 
  const strategyRows: StrategyLibrarySnapshotRow[] = useMemo(() => {
    const rows = (strategyLibQuery.data as { rows?: StrategyLibrarySnapshotRow[] } | undefined)?.rows;
    if (!Array.isArray(rows)) return [];
    return rows;
  }, [strategyLibQuery.data]);
 
  const familyDist = useMemo(() => {
    return _countBy(strategyRows, (r) => String((r as StrategyLibrarySnapshotRow).family ?? '-'));
  }, [strategyRows]);
 
  const stageDist = useMemo(() => {
    return _countBy(strategyRows, (r) => String((r as StrategyLibrarySnapshotRow).stage ?? '-'));
  }, [strategyRows]);

  const tierDist = useMemo(() => {
    return _countBy(strategyRows, (r) => String((r as StrategyLibrarySnapshotRow).tier ?? '-'));
  }, [strategyRows]);

  const tagDist = useMemo(() => {
    const tags: string[] = [];
    for (const r of strategyRows) {
      const arr = Array.isArray((r as StrategyLibrarySnapshotRow).tags) ? (r as StrategyLibrarySnapshotRow).tags : [];
      for (const t of arr) {
        const s = String(t ?? '').trim();
        if (s) tags.push(s);
      }
    }
    return _countBy(tags, (x) => String(x));
  }, [strategyRows]);

  const filteredParamoptItems = useMemo(() => {
    const day = selectedDay.trim();
    if (!day) return paramoptItems;
    return paramoptItems.filter((it) => _fmtDateFromMs(Number(it.ts || 0)) === day);
  }, [paramoptItems, selectedDay]);

  const cards = useMemo(() => {
    const res = cardsStateQuery.data as AutomationCardsStateResponse | undefined;
    const cards0 = res?.cards;
    if (!Array.isArray(cards0)) return [];
    return cards0 as AutomationCardStateV1[];
  }, [cardsStateQuery.data]);

  const stuckRows = useMemo(() => {
    const tsCard = _num((cardsStateQuery.data as { ts?: number } | undefined)?.ts, 0);
    const tsDaily = _num((dailyQuery.data as { ts?: number } | undefined)?.ts, 0);
    const raw = tsCard > 0 ? tsCard : tsDaily;
    const now = raw > 0 && raw < 1e11 ? raw * 1000 : raw;
    return cards
      .map((c) => {
        const since = Number(c.stuck?.stuck_since_ms ?? 0);
        const ms = since > 0 ? Math.max(0, now - since) : 0;
        return { card_id: String(c.card_id), stuck_ms: ms, stuck_for: ms > 0 ? ms / 60000 : 0, status: String(c.status) };
      })
      .filter((x) => x.stuck_ms > 0)
      .sort((a, b) => b.stuck_ms - a.stuck_ms);
  }, [cards, cardsStateQuery.data, dailyQuery.data]);

  const dailyThroughputRows = useMemo(() => {
    return dailyRows.map((r) => ({
      day: r.day,
      chain_supply: _num((r as Record<string, unknown>).chain_supply, 0),
      chain_shadow: _num((r as Record<string, unknown>).chain_shadow, 0),
      chain_paramopt: _num((r as Record<string, unknown>).chain_paramopt, 0),
    }));
  }, [dailyRows]);

  const weightRows = useMemo(() => {
    const w = (trackerQuery.data as TrackerStats | undefined)?.strategy_weights ?? {};
    const out: Array<{ strategy_id: string; weight: number }> = [];
    for (const [k, v] of Object.entries(w)) {
      const x = Number(v);
      if (!Number.isFinite(x)) continue;
      out.push({ strategy_id: String(k), weight: x });
    }
    out.sort((a, b) => b.weight - a.weight);
    return out.slice(0, 12);
  }, [trackerQuery.data]);
 
  const baselineMetrics = useMemo(() => _extractBacktestMetrics(baselineReportQuery.data), [baselineReportQuery.data]);
  const exploreMetrics = useMemo(() => _extractBacktestMetrics(exploreReportQuery.data), [exploreReportQuery.data]);
  const baselineEval = useMemo(() => _extractEval(baselineReportQuery.data), [baselineReportQuery.data]);
  const exploreEval = useMemo(() => _extractEval(exploreReportQuery.data), [exploreReportQuery.data]);
  const baselineEquity = useMemo(() => _extractEquity(baselineReportQuery.data), [baselineReportQuery.data]);
  const exploreEquity = useMemo(() => _extractEquity(exploreReportQuery.data), [exploreReportQuery.data]);
 
  const compareRows = useMemo(() => {
    const ks: Array<keyof typeof baselineMetrics> = ['total_pct', 'maxdd_pct', 'pf', 'calmar', 'winrate', 'trades'];
    return ks.map((k) => {
      const b = baselineMetrics[k];
      const e = exploreMetrics[k];
      const delta = (b != null && e != null) ? (e - b) : null;
      return { key: String(k), baseline: b, explore: e, delta };
    });
  }, [baselineMetrics, exploreMetrics]);
 
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="text-2xl font-bold">运行态观测</div>
          <div className="text-sm text-slate-600">自动化能力展示 + Explore 环境收益对比 + 策略资产分布</div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">/agent/observability</Badge>
          <Link to="/agent"><Button variant="outline" size="sm">返回</Button></Link>
        </div>
      </div>
 
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-lg font-medium">运行态摘要（KPI）</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant={days === 7 ? 'secondary' : 'outline'} size="sm" onClick={() => setDays(7)}>7D</Button>
            <Button variant={days === 30 ? 'secondary' : 'outline'} size="sm" onClick={() => setDays(30)}>30D</Button>
            <Button variant={days === 90 ? 'secondary' : 'outline'} size="sm" onClick={() => setDays(90)}>90D</Button>
            <div className="w-px h-6 bg-slate-200 mx-1" />
            <Input value={traceSearch} onChange={(e) => setTraceSearch(String(e.target.value ?? ''))} placeholder="trace_id 跳转 ops/pipeline" className="h-9 w-[240px]" />
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const t = traceSearch.trim();
                if (!t) return;
                nav(`/agent/ops?trace_id=${encodeURIComponent(t)}#pipeline`);
              }}
            >
              跳转
            </Button>
            {selectedDay.trim() ? (
              <>
                <Badge variant="secondary">Day {selectedDay.trim()}</Badge>
                <Button variant="outline" size="sm" onClick={() => setSelectedDay('')}>清除筛选</Button>
              </>
            ) : null}
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 text-sm">
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">风险 / 交易态</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge variant={((configQuery.data as Config | undefined)?.dry_run ?? false) ? 'secondary' : 'outline'}>dry_run {String((configQuery.data as Config | undefined)?.dry_run ?? false)}</Badge>
                <Badge variant={((configQuery.data as Config | undefined)?.live_trading_enabled ?? false) ? 'secondary' : 'outline'}>live {String((configQuery.data as Config | undefined)?.live_trading_enabled ?? false)}</Badge>
                <Badge variant="outline">venue {String((configQuery.data as Config | undefined)?.execution_venue ?? '-')}</Badge>
                <Badge variant={((freezeQuery.data as RolloutFreezeGetResponse | undefined)?.freeze ?? false) ? 'destructive' : 'outline'}>
                  freeze {String((freezeQuery.data as RolloutFreezeGetResponse | undefined)?.freeze ?? false)}
                </Badge>
                <Badge variant="outline">
                  serving {String((((servingStateQuery.data as ServingPipelineStateResponse | undefined)?.serving_pipeline as Record<string, unknown> | null | undefined) ?? null)?.phase ?? '-')}
                </Badge>
                <Badge variant={((servingGuardQuery.data as ServingPipelineGuardEvalResponse | undefined)?.pass ?? false) ? 'secondary' : 'destructive'}>
                  gate {String((servingGuardQuery.data as ServingPipelineGuardEvalResponse | undefined)?.pass ?? false)}
                </Badge>
              </div>
            </div>

            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">资产态</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="flex justify-between"><span className="text-slate-600">equity(HL)</span><span className="font-semibold">{_fmt2(_num(((trackerQuery.data as TrackerStats | undefined)?.hl as Record<string, unknown> | undefined)?.account_value, NaN), 2)}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">equity(Aster)</span><span className="font-semibold">{_fmt2(_num(((trackerQuery.data as TrackerStats | undefined)?.aster as Record<string, unknown> | undefined)?.account_value, NaN), 2)}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">open pos</span><span className="font-semibold">{Object.keys((trackerQuery.data as TrackerStats | undefined)?.open_positions ?? {}).length}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">weights</span><span className="font-semibold">{Object.keys((trackerQuery.data as TrackerStats | undefined)?.strategy_weights ?? {}).length}</span></div>
              </div>
            </div>

            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">自动化态（过去 24h）</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="flex justify-between"><span className="text-slate-600">bugfix ok</span><span className="font-semibold">{last24h.bugfix_ok}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">bugfix fail</span><span className="font-semibold">{last24h.bugfix_fail}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">paramopt.run</span><span className="font-semibold">{last24h.paramopt_runs}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">paramopt.run (strategy)</span><span className="font-semibold">{last24h.paramopt_runs_strategy}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">paramopt.run (system)</span><span className="font-semibold">{last24h.paramopt_runs_system}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">paramopt.suggestion</span><span className="font-semibold">{last24h.paramopt_suggestions}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">paramopt.suggestion (strategy)</span><span className="font-semibold">{last24h.paramopt_suggestions_strategy}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">paramopt.suggestion (system)</span><span className="font-semibold">{last24h.paramopt_suggestions_system}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">approvals</span><span className="font-semibold">{last24h.approvals}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">approvals (strategy)</span><span className="font-semibold">{last24h.approvals_strategy}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">approvals (system)</span><span className="font-semibold">{last24h.approvals_system}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">closure_rate</span><span className="font-semibold">{Number(last24h.closure_rate || 0).toFixed(3)}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">timeout_rate</span><span className="font-semibold">{Number(last24h.timeout_rate || 0).toFixed(3)}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">timeouts</span><span className="font-semibold">{last24h.paramopt_timeouts}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">system gate(kpi)</span><span className="font-semibold">{last24h.system_gate_kpi_block_count}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">system gate(plan)</span><span className="font-semibold">{last24h.system_gate_plan_block_count}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">mttr(min)</span><span className="font-semibold">{Number(last24h.mttr_minutes || 0).toFixed(2)}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">pending</span><span className="font-semibold">{_num(((approvalsQuery.data as ApprovalsSummaryResponse | undefined)?.counts as Record<string, unknown> | undefined)?.pending, 0)}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">ts</span><span className="font-semibold">{_fmtDateTimeFromMs(_num((dailyQuery.data as { ts?: number } | undefined)?.ts, 0))}</span></div>
              </div>
            </div>

            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">治理基线（Prod/Explore）</div>
              <div className="mt-2 grid grid-cols-1 gap-2">
                <div className="flex justify-between"><span className="text-slate-600">env</span><span className="font-semibold">{String((governancePolicyQuery.data as AgentGovernancePolicyResponse | undefined)?.env ?? '-')}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">contamination</span><span className="font-semibold">{_num((contaminationQuery.data as AgentGovernanceScanContaminationResponse | undefined)?.count, 0)}</span></div>
                <div className="flex justify-between"><span className="text-slate-600">skipped</span><span className="font-semibold">{String((contaminationQuery.data as AgentGovernanceScanContaminationResponse | undefined)?.skipped ?? false)}</span></div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
 
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-lg font-medium">资产分布（strategy_weights）</CardTitle>
          <div className="text-xs text-slate-500">来自 /tracker/stats?view=ui</div>
        </CardHeader>
        <CardContent className="h-72">
          {weightRows.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={weightRows} layout="vertical" margin={{ left: 50 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis type="category" dataKey="strategy_id" width={160} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v: unknown) => _fmt2(Number(v), 4)} />
                <Bar dataKey="weight" fill="#0ea5e9" name="weight" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-sm text-slate-600">当前 strategy_weights 为空</div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle>每日 Bugfix（成功/失败）</CardTitle>
            <div className="text-xs text-slate-500">点击柱子筛选 Day</div>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={dailyRows}
                onClick={(e: unknown) => {
                  const anyE = e as { activeLabel?: unknown } | null;
                  const day = String(anyE?.activeLabel ?? '').trim();
                  if (day) setSelectedDay(day);
                }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="day" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Bar dataKey="bugfix_ok" stackId="a" fill="#10b981" name="OK" />
                <Bar dataKey="bugfix_fail" stackId="a" fill="#ef4444" name="Fail" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle>每日策略优化量（堆叠）</CardTitle>
            <div className="text-xs text-slate-500">ParamOpt / Import / Shadow / Rollback</div>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={dailyRows}
                onClick={(e: unknown) => {
                  const anyE = e as { activeLabel?: unknown } | null;
                  const day = String(anyE?.activeLabel ?? '').trim();
                  if (day) setSelectedDay(day);
                }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="day" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Bar dataKey="paramopt_runs_strategy" stackId="a" fill="#0ea5e9" name="paramopt.run (strategy)" />
                <Bar dataKey="paramopt_runs_system" stackId="a" fill="#38bdf8" name="paramopt.run (system)" />
                <Bar dataKey="strategy_imports" stackId="a" fill="#f59e0b" name="strategy.import" />
                <Bar dataKey="shadow_candidates" stackId="a" fill="#6366f1" name="shadow.candidates" />
                <Bar dataKey="rollbacks" stackId="a" fill="#ef4444" name="rollbacks" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>链路吞吐（按 trace 聚合）</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={dailyThroughputRows}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="day" tick={{ fontSize: 12 }} />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="chain_supply" stroke="#f59e0b" name="supply_chain" dot={false} />
                <Line type="monotone" dataKey="chain_shadow" stroke="#6366f1" name="shadow_loop" dot={false} />
                <Line type="monotone" dataKey="chain_paramopt" stroke="#0ea5e9" name="paramopt" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>卡点时长（按链路卡片）</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stuckRows.slice(0, 12)} layout="vertical" margin={{ left: 50 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="card_id" width={170} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v: unknown) => _msToCompact(Number(v) * 60000)} />
                <Bar dataKey="stuck_for" fill="#ef4444" name="stuck_min" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
 
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-lg font-medium">Explore 收益对比（zip 对 zip）</CardTitle>
          <div className="text-xs text-slate-500">基于 /backtest/report 的 aligned_metrics / summary</div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-2">
              <div className="text-xs text-slate-500">Baseline zip</div>
              <Input value={baselineZip} onChange={(e) => setBaselineZip(String(e.target.value ?? ''))} placeholder="例如 2026-02-25_..._backtest.zip" />
              <div className="text-xs text-slate-500">{baselineReportQuery.isFetching ? '加载中…' : ''}</div>
            </div>
            <div className="space-y-2">
              <div className="text-xs text-slate-500">Explore zip</div>
              <Input value={exploreZip} onChange={(e) => setExploreZip(String(e.target.value ?? ''))} placeholder="例如 2026-02-26_..._backtest.zip" />
              <div className="text-xs text-slate-500">{exploreReportQuery.isFetching ? '加载中…' : ''}</div>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">治理入口</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <Badge variant="outline">env {String((governancePolicyQuery.data as AgentGovernancePolicyResponse | undefined)?.env ?? '-')}</Badge>
                <Badge variant={_num((contaminationQuery.data as AgentGovernanceScanContaminationResponse | undefined)?.count, 0) > 0 ? 'destructive' : 'secondary'}>
                  contamination {_num((contaminationQuery.data as AgentGovernanceScanContaminationResponse | undefined)?.count, 0)}
                </Badge>
              </div>
              <div className="mt-2 text-xs text-slate-500">对 Explore 扩张类变更先做污染扫描，再看收益对比。</div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">Baseline eval</div>
              <div className="mt-2 flex justify-between"><span className="text-slate-600">hard_fails</span><span className="font-semibold">{baselineEval.hard_fails_n == null ? '-' : String(baselineEval.hard_fails_n)}</span></div>
              <div className="flex justify-between"><span className="text-slate-600">score</span><span className="font-semibold">{_fmt2(baselineEval.score, 4)}</span></div>
            </div>
            <div className="border rounded p-3 bg-white">
              <div className="text-xs text-slate-500">Explore eval</div>
              <div className="mt-2 flex justify-between"><span className="text-slate-600">hard_fails</span><span className="font-semibold">{exploreEval.hard_fails_n == null ? '-' : String(exploreEval.hard_fails_n)}</span></div>
              <div className="flex justify-between"><span className="text-slate-600">score</span><span className="font-semibold">{_fmt2(exploreEval.score, 4)}</span></div>
            </div>
          </div>
          <div className="border rounded p-3 bg-white">
            <div className="text-xs text-slate-500 mb-2">Equity 曲线（若后端提供）</div>
            {baselineEquity.length >= 2 && exploreEquity.length >= 2 ? (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={baselineEquity.map((p, i) => ({
                      ts: p.ts,
                      baseline: p.equity_u,
                      explore: exploreEquity[i]?.equity_u ?? null,
                    }))}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="ts" tick={{ fontSize: 12 }} tickFormatter={(v: unknown) => _fmtDateFromMs(Number(v))} />
                    <YAxis />
                    <Tooltip labelFormatter={(v: unknown) => _fmtDateFromMs(Number(v))} />
                    <Legend />
                    <Line type="monotone" dataKey="baseline" stroke="#0ea5e9" name="baseline" dot={false} />
                    <Line type="monotone" dataKey="explore" stroke="#6366f1" name="explore" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="text-sm text-slate-600">当前 report 未包含 equity_curve 字段，已回退到指标对比。</div>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 text-sm">
            {compareRows.map((r) => (
              <div key={r.key} className="border rounded p-3 bg-white">
                <div className="text-xs text-slate-500">{r.key}</div>
                <div className="mt-1 flex justify-between">
                  <span className="text-slate-600">baseline</span>
                  <span className="font-semibold">
                    {r.key.endsWith('_pct') || r.key === 'winrate' ? _fmtPct(r.baseline as number | null) : _fmt2(r.baseline as number | null, 4)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">explore</span>
                  <span className="font-semibold">
                    {r.key.endsWith('_pct') || r.key === 'winrate' ? _fmtPct(r.explore as number | null) : _fmt2(r.explore as number | null, 4)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600">delta</span>
                  <span className="font-semibold">
                    {r.delta == null ? '-' : (r.key.endsWith('_pct') || r.key === 'winrate') ? _fmtPct(r.delta as number, 2) : _fmt2(r.delta as number, 4)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
 
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>策略库分布（family）</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={familyDist.slice(0, 18)} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="key" width={120} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="n" fill="#22c55e" name="count" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
 
        <Card>
          <CardHeader>
            <CardTitle>策略库分布（stage）</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stageDist.slice(0, 18)} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="key" width={120} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="n" fill="#0ea5e9" name="count" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>策略库分布（tier）</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={tierDist.slice(0, 18)} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="key" width={120} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="n" fill="#a855f7" name="count" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>策略库分布（tags Top）</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={tagDist.slice(0, 18)} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" allowDecimals={false} />
                <YAxis type="category" dataKey="key" width={140} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="n" fill="#22c55e" name="count" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
 
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-lg font-medium">参数优化详细列表（最近）</CardTitle>
          <div className="text-xs text-slate-500">点击 trace_id 跳转到 ops 流水线</div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="py-2 pr-4">day</th>
                  <th className="py-2 pr-4">trace_id</th>
                  <th className="py-2 pr-4">class</th>
                  <th className="py-2 pr-4">strategy_id</th>
                  <th className="py-2 pr-4">plan_id</th>
                  <th className="py-2 pr-4">step_id</th>
                  <th className="py-2 pr-4">status</th>
                  <th className="py-2 pr-4">ok</th>
                  <th className="py-2 pr-4">reason</th>
                  <th className="py-2 pr-4">gate</th>
                  <th className="py-2 pr-4">mode</th>
                  <th className="py-2 pr-4">preset</th>
                  <th className="py-2 pr-4">family</th>
                  <th className="py-2 pr-4">eval_mode</th>
                  <th className="py-2 pr-4">bayes</th>
                  <th className="py-2 pr-4">n_init</th>
                  <th className="py-2 pr-4">n_iter</th>
                  <th className="py-2 pr-4">selected_keys</th>
                  <th className="py-2 pr-4">selected_rank</th>
                  <th className="py-2 pr-4">selected_patch</th>
                  <th className="py-2 pr-4">apply</th>
                  <th className="py-2 pr-4">draft_id</th>
                  <th className="py-2 pr-4">approval_id</th>
                  <th className="py-2 pr-4">keys</th>
                </tr>
              </thead>
              <tbody>
                {filteredParamoptItems.map((it: AgentObservabilityParamoptRecentItem) => (
                  <tr key={it.trace_id} className="border-t">
                    <td className="py-2 pr-4 whitespace-nowrap">{_fmtDateFromMs(Number(it.ts || 0))}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      <Link to={`/agent/ops?trace_id=${encodeURIComponent(String(it.trace_id))}#pipeline`}>
                        <Button variant="outline" size="sm">{String(it.trace_id).slice(0, 14)}</Button>
                      </Link>
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap">{String(it.opt_class ?? '-')}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">{String(it.strategy_id ?? '-')}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">{String(it.plan_id ?? '-')}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">{String(it.step_id ?? '-')}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      {it.has_suggestion ? (
                        <Badge variant="secondary">DONE</Badge>
                      ) : (it.has_run ? (
                        <Badge variant="outline">RUNNING</Badge>
                      ) : '-')}
                    </td>
                    <td className="py-2 pr-4">
                      {it.ok == null ? '-' : (
                        <Badge variant={it.ok ? 'secondary' : 'destructive'}>{String(Boolean(it.ok))}</Badge>
                      )}
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      <div className="max-w-[180px] truncate">{String(it.reason_code ?? '-')}</div>
                    </td>
                    <td className="py-2 pr-4">
                      {it.gate_pass == null ? '-' : (
                        <Badge variant={it.gate_pass ? 'secondary' : 'destructive'}>
                          {it.gate_pass ? 'pass' : `fail(${_num(it.gate_fails_n, 0)})`}
                        </Badge>
                      )}
                    </td>
                    <td className="py-2 pr-4">{String(it.mode ?? '-')}</td>
                    <td className="py-2 pr-4">{String(it.preset ?? '-')}</td>
                    <td className="py-2 pr-4">{String(it.family ?? '-')}</td>
                    <td className="py-2 pr-4">{String(it.eval_mode ?? '-')}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      {String(it.optimizer_engine ?? '').trim() ? (
                        <Badge variant="secondary">{String(it.optimizer_engine)}</Badge>
                      ) : '-'}
                    </td>
                    <td className="py-2 pr-4">{it.n_init == null ? '-' : String(it.n_init)}</td>
                    <td className="py-2 pr-4">{it.n_iter == null ? '-' : String(it.n_iter)}</td>
                    <td className="py-2 pr-4">{it.selected_keys_n == null ? '-' : String(it.selected_keys_n)}</td>
                    <td className="py-2 pr-4">{it.selected_rank == null ? '-' : String(it.selected_rank)}</td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      {it.selected_patch_n == null ? '-' : (
                        <div className="max-w-[280px] truncate">
                          {String(it.selected_patch_n)}
                          {Array.isArray(it.selected_patch_keys) && it.selected_patch_keys.length > 0 ? ` (${it.selected_patch_keys.join(', ')})` : ''}
                        </div>
                      )}
                    </td>
                    <td className="py-2 pr-4 whitespace-nowrap">
                      {String(it.apply_mode ?? '').trim() ? (
                        <Badge variant={it.apply_ok ? 'secondary' : 'outline'}>
                          {String(it.apply_mode)} {it.apply_ok == null ? '' : `(${String(Boolean(it.apply_ok))})`}
                        </Badge>
                      ) : '-'}
                    </td>
                    <td className="py-2 pr-4">{String(it.draft_id ?? '-')}</td>
                    <td className="py-2 pr-4">{String(it.approval_id ?? '-')}</td>
                    <td className="py-2 pr-4">
                      <div className="max-w-[520px] truncate">{Array.isArray(it.keys) ? it.keys.join(', ') : '-'}</div>
                    </td>
                  </tr>
                ))}
                {filteredParamoptItems.length === 0 ? (
                  <tr className="border-t">
                    <td className="py-3 text-slate-500" colSpan={24}>暂无数据</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
