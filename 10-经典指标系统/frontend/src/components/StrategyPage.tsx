import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import type { AxiosError } from 'axios';
import {
  appendStrategyRegistryEvent,
  api,
  buildStrategyBundle,
  fetchBacktestResults,
  fetchAutomationStrategiesState,
  fetchStrategyFeederCapabilities,
  fetchStrategyBundles,
  fetchStrategyLibrarySnapshot,
  fetchStrategyRegistry,
  fetchStrategySearch,
  fetchStrategyRegistryEvents,
  importActiveStrategiesToRegistry,
  repoFetchStrategyStub,
  runAutomationBacktest,
  runAndSyncStrategyRegistry,
  syncStrategyRegistryFromZip,
  strategyBundleDownloadUrl,
  upsertStrategyRegistry,
} from '../lib/api';
import type {
  BacktestResultsResponse,
  AutomationStrategiesConfigResponse,
  StrategyFeederCapabilitiesResponse,
  AutomationBacktestRunResponse,
  RepoFetchStrategyResponse,
  StrategyBundleBuildResponse,
  StrategyLibrarySnapshotResponse,
  StrategyLibrarySnapshotRow,
  StrategyRegistryEvent,
  StrategyRegistryEntry,
  StrategyRegistryRunAndSyncResponse,
  StrategyRegistryResponse,
  StrategySearchResponse,
} from '../lib/api';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Input } from './ui/input';

function _errText(err: unknown): string {
  const axiosErr = err as AxiosError<unknown>;
  const data = axiosErr?.response?.data;
  try {
    if (typeof data === 'string' && data.trim()) return data;
    if (data && typeof data === 'object') {
      const obj = data as Record<string, unknown>;
      const e = String(obj.error ?? '').trim();
      if (e) return e;
      const s = JSON.stringify(data);
      if (s.length <= 1600) return s;
      return `${s.slice(0, 1600)}...(truncated)`;
    }
  } catch {
    return String(axiosErr?.message ?? err);
  }
  const msg = String(axiosErr?.message ?? '').trim();
  if (msg) return msg;
  return String(err);
}

function _toNum(v: unknown, d = NaN): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

function _uniqTags(items: string[]): string[] {
  const out: string[] = [];
  for (const it of items) {
    const s = String(it ?? '').trim();
    if (!s) continue;
    if (!out.includes(s)) out.push(s);
  }
  return out;
}

function _autoTagsFromSnapshotRow(row: StrategyLibrarySnapshotRow): string[] {
  const pf = _toNum(row.metrics?.profit_factor, NaN);
  const dd = _toNum(row.metrics?.max_drawdown_pct, NaN);
  const wr = _toNum(row.metrics?.winrate, NaN);
  const trades = _toNum(row.metrics?.trades, NaN);
  const sd = _toNum(row.extras?.signal_density, NaN);
  const out: string[] = [];
  if (Number.isFinite(pf)) out.push(pf >= 1.5 ? 'pf_1p5' : pf >= 1.2 ? 'pf_1p2' : pf >= 1.0 ? 'pf_1p0' : 'pf_lt_1');
  if (Number.isFinite(dd)) out.push(dd <= 0.08 ? 'dd_0p08' : dd <= 0.12 ? 'dd_0p12' : dd <= 0.20 ? 'dd_0p20' : 'dd_gt_0p20');
  if (Number.isFinite(wr)) out.push(wr >= 0.60 ? 'wr_0p60' : wr >= 0.55 ? 'wr_0p55' : wr >= 0.50 ? 'wr_0p50' : 'wr_lt_0p50');
  if (Number.isFinite(trades)) out.push(trades >= 500 ? 'n_500' : trades >= 200 ? 'n_200' : trades >= 50 ? 'n_50' : 'n_lt_50');
  if (Number.isFinite(sd)) out.push(sd >= 5 ? 'dense_5pd' : sd >= 2 ? 'dense_2pd' : sd >= 0.5 ? 'dense_0p5pd' : 'dense_lt_0p5pd');
  return _uniqTags(out);
}

function _autoTagsFromMetricsObj(ms: Record<string, unknown> | null | undefined): string[] {
  if (!ms) return [];
  const pf = _toNum(ms.profit_factor, NaN);
  const dd = _toNum(ms.max_drawdown_pct ?? ms.max_drawdown_account, NaN);
  const wr = _toNum(ms.winrate, NaN);
  const trades = _toNum(ms.trades, NaN);
  const days = _toNum(ms.backtest_days, NaN);
  const density = Number.isFinite(trades) && Number.isFinite(days) && days > 0 ? (trades / days) : NaN;
  const out: string[] = [];
  if (Number.isFinite(pf)) out.push(pf >= 1.5 ? 'pf_1p5' : pf >= 1.2 ? 'pf_1p2' : pf >= 1.0 ? 'pf_1p0' : 'pf_lt_1');
  if (Number.isFinite(dd)) out.push(dd <= 0.08 ? 'dd_0p08' : dd <= 0.12 ? 'dd_0p12' : dd <= 0.20 ? 'dd_0p20' : 'dd_gt_0p20');
  if (Number.isFinite(wr)) out.push(wr >= 0.60 ? 'wr_0p60' : wr >= 0.55 ? 'wr_0p55' : wr >= 0.50 ? 'wr_0p50' : 'wr_lt_0p50');
  if (Number.isFinite(trades)) out.push(trades >= 500 ? 'n_500' : trades >= 200 ? 'n_200' : trades >= 50 ? 'n_50' : 'n_lt_50');
  if (Number.isFinite(density)) out.push(density >= 5 ? 'dense_5pd' : density >= 2 ? 'dense_2pd' : density >= 0.5 ? 'dense_0p5pd' : 'dense_lt_0p5pd');
  const tf = String(ms.timeframe ?? '').trim().toLowerCase();
  if (tf) out.push(`tf_${tf}`);
  return _uniqTags(out);
}

function _suggestStageFromTier(tierRaw: unknown): 'research' | 'model' | 'deployment' {
  const t = String(tierRaw ?? '').trim().toUpperCase();
  if (t === 'A' || t === 'B') return 'model';
  return 'research';
}

function _inferFamilyFromSnapshotRow(row: StrategyLibrarySnapshotRow): { family: 'trend' | 'mean_reversion' | 'breakout' | 'carry'; score: number; reason: string } {
  const pf = _toNum(row.metrics?.profit_factor, NaN);
  const dd = _toNum(row.metrics?.max_drawdown_pct, NaN);
  const wr = _toNum(row.metrics?.winrate, NaN);
  const trades = _toNum(row.metrics?.trades, NaN);
  const days = _toNum(row.metrics?.backtest_days, NaN);
  const density = Number.isFinite(trades) && Number.isFinite(days) && days > 0 ? (trades / days) : NaN;
  const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
  const sPf = Number.isFinite(pf) ? clamp01((pf - 1.0) / 0.8) : 0;
  const sDdLow = Number.isFinite(dd) ? clamp01((0.20 - dd) / 0.20) : 0;
  const sWinHigh = Number.isFinite(wr) ? clamp01((wr - 0.52) / 0.10) : 0;
  const sWinLow = Number.isFinite(wr) ? clamp01((0.56 - wr) / 0.10) : 0;
  const sDenseHigh = Number.isFinite(density) ? clamp01((density - 1.0) / 4.0) : 0;
  const sDenseLow = Number.isFinite(density) ? clamp01((0.8 - density) / 0.8) : 0;

  const scoreMR = 0.35 * sWinHigh + 0.35 * sDenseHigh + 0.15 * sDdLow + 0.15 * sPf;
  const scoreTrend = 0.40 * sPf + 0.30 * sDdLow + 0.20 * sWinLow + 0.10 * (1 - sDenseHigh);
  const scoreBO = 0.45 * sDenseLow + 0.30 * sPf + 0.25 * sDdLow;
  const scoreCarry = 0.45 * sDdLow + 0.35 * sWinHigh + 0.20 * sPf;

  const cands: Array<{ family: 'trend' | 'mean_reversion' | 'breakout' | 'carry'; score: number }> = [
    { family: 'mean_reversion', score: scoreMR },
    { family: 'trend', score: scoreTrend },
    { family: 'breakout', score: scoreBO },
    { family: 'carry', score: scoreCarry },
  ];
  cands.sort((a, b) => b.score - a.score);
  const best = cands[0] ?? { family: 'trend' as const, score: 0 };
  const reason = `pf=${Number.isFinite(pf) ? pf.toFixed(2) : '-'}, dd=${Number.isFinite(dd) ? (dd * 100).toFixed(1) + '%' : '-'}, wr=${Number.isFinite(wr) ? (wr * 100).toFixed(1) + '%' : '-'}, dens=${Number.isFinite(density) ? density.toFixed(2) + '/d' : '-'}`;
  return { family: best.family, score: Math.max(0, Math.min(1, best.score)), reason };
}

function _inferFamilyFromMetricsObj(ms: Record<string, unknown> | null | undefined): { family: 'trend' | 'mean_reversion' | 'breakout' | 'carry'; score: number; reason: string } {
  const pf = _toNum(ms?.profit_factor, NaN);
  const dd = _toNum((ms?.max_drawdown_pct ?? (ms as Record<string, unknown> | undefined)?.max_drawdown_account), NaN);
  const wr = _toNum(ms?.winrate, NaN);
  const trades = _toNum(ms?.trades, NaN);
  const days = _toNum(ms?.backtest_days, NaN);
  const density = Number.isFinite(trades) && Number.isFinite(days) && days > 0 ? (trades / days) : NaN;
  const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
  const sPf = Number.isFinite(pf) ? clamp01((pf - 1.0) / 0.8) : 0;
  const sDdLow = Number.isFinite(dd) ? clamp01((0.20 - dd) / 0.20) : 0;
  const sWinHigh = Number.isFinite(wr) ? clamp01((wr - 0.52) / 0.10) : 0;
  const sWinLow = Number.isFinite(wr) ? clamp01((0.56 - wr) / 0.10) : 0;
  const sDenseHigh = Number.isFinite(density) ? clamp01((density - 1.0) / 4.0) : 0;
  const sDenseLow = Number.isFinite(density) ? clamp01((0.8 - density) / 0.8) : 0;
  const scoreMR = 0.35 * sWinHigh + 0.35 * sDenseHigh + 0.15 * sDdLow + 0.15 * sPf;
  const scoreTrend = 0.40 * sPf + 0.30 * sDdLow + 0.20 * sWinLow + 0.10 * (1 - sDenseHigh);
  const scoreBO = 0.45 * sDenseLow + 0.30 * sPf + 0.25 * sDdLow;
  const scoreCarry = 0.45 * sDdLow + 0.35 * sWinHigh + 0.20 * sPf;
  const cands: Array<{ family: 'trend' | 'mean_reversion' | 'breakout' | 'carry'; score: number }> = [
    { family: 'mean_reversion', score: scoreMR },
    { family: 'trend', score: scoreTrend },
    { family: 'breakout', score: scoreBO },
    { family: 'carry', score: scoreCarry },
  ];
  cands.sort((a, b) => b.score - a.score);
  const best = cands[0] ?? { family: 'trend' as const, score: 0 };
  const reason = `pf=${Number.isFinite(pf) ? pf.toFixed(2) : '-'}, dd=${Number.isFinite(dd) ? (dd * 100).toFixed(1) + '%' : '-'}, wr=${Number.isFinite(wr) ? (wr * 100).toFixed(1) + '%' : '-'}, dens=${Number.isFinite(density) ? density.toFixed(2) + '/d' : '-'}`;
  return { family: best.family, score: Math.max(0, Math.min(1, best.score)), reason };
}

function _fmtPct(x: number, digits = 1): string {
  if (!Number.isFinite(x)) return '-';
  return `${(x * 100).toFixed(digits)}%`;
}

function _fmt2(x: number, digits = 2): string {
  if (!Number.isFinite(x)) return '-';
  return x.toFixed(digits);
}

function _fmtTs(ms: number): string {
  const t = Number(ms);
  if (!Number.isFinite(t) || t <= 0) return '';
  const d = new Date(t);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${y}-${m}-${day} ${hh}:${mm}`;
}

function _normRobust(v: unknown): string {
  const s = String(v ?? '').trim().toLowerCase();
  if (!s) return 'unknown';
  if (s === 'unknown' || s === 'na' || s === 'n/a') return 'unknown';
  if (s === 'pass' || s === 'ok' || s === 'good' || s === 'success') return 'pass';
  if (s === 'warn' || s === 'warning') return 'warn';
  if (s === 'fail' || s === 'failed' || s === 'bad') return 'fail';
  return s;
}

function _registryKey(strategyId: string, sourceZip: string): string {
  return `${String(strategyId || '').trim()}|${String(sourceZip || '').trim()}`;
}

function _pickRegistryEntry(entries: StrategyRegistryEntry[], strategyId: string, sourceZip: string): StrategyRegistryEntry | undefined {
  const sid = String(strategyId || '').trim();
  const z = String(sourceZip || '').trim();
  if (!sid) return undefined;
  if (z) {
    const exact = entries.find((e) => String(e.strategy_id || '').trim() === sid && String(e.source_zip || '').trim() === z);
    if (exact) return exact;
  }
  const anyZip = entries.find((e) => String(e.strategy_id || '').trim() === sid && String(e.source_zip || '').trim() === '*');
  if (anyZip) return anyZip;
  let best: StrategyRegistryEntry | undefined;
  let bestTs = '';
  for (const e of entries) {
    if (String(e.strategy_id || '').trim() !== sid) continue;
    const ts = String(e.updated_at || '');
    if (!best || ts > bestTs) {
      best = e;
      bestTs = ts;
    }
  }
  return best;
}

type RegistryDraft = {
  family: string;
  stage: string;
  robustness: string;
  tagsText: string;
  econDriver: string;
  evalPolicyRef: string;
  owner: string;
  approvedBy: string;
  approvedAt: string;
  lifecycleState: string;
  rolloutStatus: string;
  rollbackToBundleId: string;
  tierOverride: string;
  deprecateReason: string;
  traceId: string;
  actor: string;
  note: string;
};

type BundleBuildState = {
  bundle?: string;
  downloadUrl?: string;
  bundleId?: string;
  tier?: string;
  tierReason?: string;
  error?: string;
};

type VerifyState = {
  ok?: boolean;
  error?: string;
};

type RepoSupplyChainStep = 'fetch' | 'backtest' | 'registry' | 'bundle' | 'approval';

type RepoSupplyChainProgress = {
  trace_id?: string;
  approval_id?: string | null;
  steps: Record<RepoSupplyChainStep, 'idle' | 'running' | 'ok' | 'fail'>;
  ts: Partial<Record<RepoSupplyChainStep, number>>;
  error?: string;
};

export const StrategyPage: React.FC = () => {
  const location = useLocation();
  const [btResultsLimit, setBtResultsLimit] = useState<number>(50);
  const [zip, setZip] = useState<string>('');
  const [q, setQ] = useState<string>('');
  const [family, setFamily] = useState<string>('all');
  const [stage, setStage] = useState<string>('all');
  const [tier, setTier] = useState<string>('all');
  const [sort, setSort] = useState<string>('density_asc');
  const [runConfig, setRunConfig] = useState<string>('user_data/config_local_backtest.json');
  const [runTimerange, setRunTimerange] = useState<string>('');
  const [runTimeoutSec, setRunTimeoutSec] = useState<number>(1800);
  const [deepRobustness, setDeepRobustness] = useState<boolean>(false);
  const [bulkSelected, setBulkSelected] = useState<Record<string, boolean>>({});
  const [bulkAutoTag, setBulkAutoTag] = useState<boolean>(true);
  const [bulkAutoFamily, setBulkAutoFamily] = useState<boolean>(true);
  const [bulkAutoStage, setBulkAutoStage] = useState<boolean>(false);
  const [bulkMaxN, setBulkMaxN] = useState<number>(8);
  const [bulkBusy, setBulkBusy] = useState<boolean>(false);
  const [bulkProgress, setBulkProgress] = useState<{ total: number; done: number; current?: string; mode?: string; error?: string } | null>(null);
  const bulkCancelRef = useRef<boolean>(false);

  const [repoUrl, setRepoUrl] = useState<string>('');
  const [repoBranch, setRepoBranch] = useState<string>('');
  const [repoCommit, setRepoCommit] = useState<string>('');
  const [repoPath, setRepoPath] = useState<string>('');
  const [repoStrategyName, setRepoStrategyName] = useState<string>('');
  const [repoFamily, setRepoFamily] = useState<string>('trend');
  const [repoStage, setRepoStage] = useState<string>('research');
  const [repoTagsText, setRepoTagsText] = useState<string>('');
  const [repoEconDriver, setRepoEconDriver] = useState<string>('');
  const [repoEvalPolicyRef, setRepoEvalPolicyRef] = useState<string>('p3_default');
  const [repoOwner, setRepoOwner] = useState<string>('');
  const [repoBuildBundle, setRepoBuildBundle] = useState<boolean>(true);
  const [repoBusy, setRepoBusy] = useState<boolean>(false);
  const [repoState, setRepoState] = useState<{ ok?: boolean; error?: string; zip?: string; bundle?: string } | null>(null);
  const [repoProgress, setRepoProgress] = useState<RepoSupplyChainProgress | null>(null);
  const [drafts, setDrafts] = useState<Record<string, RegistryDraft>>({});
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [saveState, setSaveState] = useState<Record<string, 'idle' | 'ok' | 'error'>>({});
  const [saveError, setSaveError] = useState<Record<string, string | undefined>>({});
  const [builds, setBuilds] = useState<Record<string, BundleBuildState>>({});
  const [building, setBuilding] = useState<Record<string, boolean>>({});
  const [verifying, setVerifying] = useState<Record<string, boolean>>({});
  const [verifyState, setVerifyState] = useState<Record<string, VerifyState>>({});
  const [running, setRunning] = useState<Record<string, boolean>>({});
  const [runState, setRunState] = useState<Record<string, VerifyState>>({});
  const [govBusy, setGovBusy] = useState<Record<string, boolean>>({});
  const [eventsOpen, setEventsOpen] = useState<Record<string, boolean>>({});
  const [eventsLoading, setEventsLoading] = useState<Record<string, boolean>>({});
  const [eventsByKey, setEventsByKey] = useState<Record<string, StrategyRegistryEvent[]>>({});

  const [importActiveBusy, setImportActiveBusy] = useState<boolean>(false);
  const [importActiveState, setImportActiveState] = useState<{ ok?: boolean; error?: string; saved?: number; trace_id?: string } | null>(null);

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
  const feederDirectionById = useMemo(() => {
    const caps = feederCaps as StrategyFeederCapabilitiesResponse | undefined;
    const out: Record<string, 'long_only' | 'long_short'> = {};
    const items = Array.isArray(caps?.strategies) ? caps.strategies : [];
    for (const it of items) {
      const sid = String(it?.strategy_id || '').trim();
      if (!sid) continue;
      const raw = String((it as { direction_capability?: unknown })?.direction_capability ?? '').trim().toLowerCase();
      if (raw === 'long_short') out[sid] = 'long_short';
      else if (raw === 'long_only') out[sid] = 'long_only';
    }
    const fallbackLongShort = ['Strategy005', 'RegimeHybridStrategy', 'BreakoutStrategy', 'MultiGroupStrategy', 'OttStrategy'];
    for (const sid of fallbackLongShort) {
      if (!out[sid]) out[sid] = 'long_short';
    }
    if (!out.Bot2Strategy) out.Bot2Strategy = 'long_only';
    return out;
  }, [feederCaps]);
  const [feederCtlOpen, setFeederCtlOpen] = useState<boolean>(false);
  const [feederCtlSource, setFeederCtlSource] = useState<{ strategy_id: string; source_zip: string } | null>(null);
  const [feederCtlRuntimeKey, setFeederCtlRuntimeKey] = useState<string>('Strategy005');
  const [feederCtlToken, setFeederCtlToken] = useState<string>('');
  const [feederCtlConfirm, setFeederCtlConfirm] = useState<string>('');
  const [feederCtlBusy, setFeederCtlBusy] = useState<boolean>(false);
  const [feederCtlState, setFeederCtlState] = useState<{ ok?: boolean; error?: string; before?: string; after?: string } | null>(null);

  useEffect(() => {
    const raw = String(location.search || '').trim();
    if (!raw) return;
    let sp: URLSearchParams;
    try {
      sp = new URLSearchParams(raw.startsWith('?') ? raw.slice(1) : raw);
    } catch {
      return;
    }

    const z0 = String(sp.get('zip') || '').trim();
    const q0 = String(sp.get('q') || '').trim();
    const fam0 = String(sp.get('family') || '').trim();
    const st0 = String(sp.get('stage') || '').trim();
    const tier0 = String(sp.get('tier') || '').trim();
    const sort0 = String(sp.get('sort') || '').trim();

    if (z0) setZip(z0);
    if (q0) setQ(q0);
    if (fam0) setFamily(fam0);
    if (st0) setStage(st0);
    if (tier0) setTier(tier0);
    if (sort0) setSort(sort0);
  }, [location.search]);

  const { data: btResults, refetch: refetchBtResults } = useQuery({
    queryKey: ['backtest', 'results', btResultsLimit],
    queryFn: () => fetchBacktestResults({ limit: btResultsLimit }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });

  const { data: automation, refetch: refetchAutomation } = useQuery({
    queryKey: ['automation', 'state'],
    queryFn: fetchAutomationStrategiesState,
    refetchInterval: 10000,
    refetchOnWindowFocus: false,
  });

  const latestZip = useMemo(() => {
    const r = btResults as BacktestResultsResponse | undefined;
    const z = r?.latest;
    const s = z === null || z === undefined ? '' : String(z).trim();
    return s;
  }, [btResults]);

  const repoProgressView = useMemo(() => {
    if (!repoProgress) return null;
    const order: RepoSupplyChainStep[] = ['fetch', 'backtest', 'registry', 'bundle', 'approval'];
    const doneN = order.filter((k) => repoProgress.steps[k] === 'ok').length;
    const pct = Math.round((doneN / order.length) * 100);
    return { order, pct, doneN };
  }, [repoProgress]);

  const effectiveZip = useMemo(() => {
    const s = zip.trim();
    return s || latestZip || '';
  }, [zip, latestZip]);

  const { data: registry, refetch: refetchRegistry } = useQuery({
    queryKey: ['strategy', 'registry', effectiveZip || ''],
    queryFn: async () => {
      const z = String(effectiveZip || '').trim();
      if (z) {
        try {
          return await fetchStrategySearch({ zip: z, limit: 500, offset: 0, sort: 'updated_desc' });
        } catch {
          return await fetchStrategyRegistry();
        }
      }
      return await fetchStrategyRegistry();
    },
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });

  const { data: snapshot, isFetching: snapshotFetching, refetch: refetchSnapshot } = useQuery({
    queryKey: ['strategy', 'library', effectiveZip || 'latest'],
    queryFn: async () => {
      const z = effectiveZip.trim();
      return await fetchStrategyLibrarySnapshot(z ? { zip: z } : undefined);
    },
    enabled: Boolean(effectiveZip),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });

  const snapshotZip = useMemo(() => {
    const resp = snapshot as StrategyLibrarySnapshotResponse | undefined;
    const z = String(resp?.zip ?? '').trim();
    return z || effectiveZip || '';
  }, [snapshot, effectiveZip]);

  const autoCfg = useMemo(() => {
    const a = automation as AutomationStrategiesConfigResponse | undefined;
    return a?.automation ?? null;
  }, [automation]);

  const { data: bundles } = useQuery({
    queryKey: ['strategy', 'bundles'],
    queryFn: () => fetchStrategyBundles({ limit: 20 }),
    refetchInterval: 30000,
    refetchOnWindowFocus: false,
  });

  const regEntries = useMemo(() => {
    const r = registry as (StrategyRegistryResponse | StrategySearchResponse) | undefined;
    const entries = (r as StrategyRegistryResponse | undefined)?.entries;
    if (Array.isArray(entries)) return entries as StrategyRegistryEntry[];
    const rows = (r as StrategySearchResponse | undefined)?.rows;
    if (Array.isArray(rows)) return rows as StrategyRegistryEntry[];
    return [] as StrategyRegistryEntry[];
  }, [registry]);

  const rows = useMemo(() => {
    const resp = snapshot as StrategyLibrarySnapshotResponse | undefined;
    const rs = (resp?.rows ?? []) as StrategyLibrarySnapshotRow[];
    const query = q.trim().toLowerCase();
    const filtered = rs.filter((r) => {
      const sid = String(r.strategy_id ?? '').trim();
      if (!sid) return false;
      if (family !== 'all' && String(r.family ?? '').toLowerCase() !== family) return false;
      if (stage !== 'all' && String(r.stage ?? '').toLowerCase() !== stage) return false;
      if (tier !== 'all' && String(r.tier ?? '').toUpperCase() !== tier.toUpperCase()) return false;
      if (!query) return true;
      const tags = Array.isArray(r.tags) ? r.tags.join(',').toLowerCase() : '';
      const reason = String(r.tier_reason ?? '').toLowerCase();
      return sid.toLowerCase().includes(query) || tags.includes(query) || reason.includes(query);
    });

    const tierRank: Record<string, number> = { A: 3, B: 2, C: 1, UNRATED: 0 };
    const out = [...filtered];
    out.sort((a, b) => {
      const apf = _toNum(a.metrics?.profit_factor, NaN);
      const bpf = _toNum(b.metrics?.profit_factor, NaN);
      const add = _toNum(a.metrics?.max_drawdown_pct, NaN);
      const bdd = _toNum(b.metrics?.max_drawdown_pct, NaN);
      const asd = _toNum(a.extras?.signal_density, NaN);
      const bsd = _toNum(b.extras?.signal_density, NaN);
      const at = tierRank[String(a.tier ?? 'UNRATED').toUpperCase()] ?? 0;
      const bt = tierRank[String(b.tier ?? 'UNRATED').toUpperCase()] ?? 0;

      if (sort === 'tier_desc') {
        if (at !== bt) return bt - at;
      }
      if (sort === 'density_asc') {
        if (Number.isFinite(asd) && Number.isFinite(bsd) && asd !== bsd) return asd - bsd;
      }
      if (sort === 'dd_asc') {
        if (Number.isFinite(add) && Number.isFinite(bdd) && add !== bdd) return add - bdd;
      }
      if (Number.isFinite(apf) && Number.isFinite(bpf) && apf !== bpf) return bpf - apf;
      return bt - at;
    });
    return out;
  }, [snapshot, q, family, stage, tier, sort]);

  const bulkSelectedCount = useMemo(() => Object.values(bulkSelected).filter(Boolean).length, [bulkSelected]);

  const bulkSelectAllVisible = () => {
    const next: Record<string, boolean> = {};
    for (const r of rows) {
      const sid = String(r.strategy_id ?? '').trim();
      if (!sid) continue;
      next[sid] = true;
    }
    setBulkSelected(next);
  };

  const bulkClearSelection = () => setBulkSelected({});

  const bulkStop = () => {
    bulkCancelRef.current = true;
    setBulkBusy(false);
  };

  const bulkClassifyFromSnapshot = async () => {
    const z = snapshotZip.trim();
    if (!z) {
      setBulkProgress({ total: 0, done: 0, error: 'missing_snapshot_zip', mode: 'classify' });
      return;
    }
    const selectedSids = Object.entries(bulkSelected).filter(([, v]) => Boolean(v)).map(([k]) => k).filter(Boolean);
    const total = selectedSids.length;
    if (!total) {
      setBulkProgress({ total: 0, done: 0, error: 'no_selected', mode: 'classify' });
      return;
    }
    bulkCancelRef.current = false;
    setBulkBusy(true);
    setBulkProgress({ total, done: 0, mode: 'classify' });
    try {
      const items: StrategyRegistryEntry[] = [];
      for (const sid of selectedSids) {
        if (bulkCancelRef.current) break;
        setBulkProgress((p) => (p ? { ...p, current: sid } : { total, done: 0, current: sid, mode: 'classify' }));
        const row = rows.find((r) => String(r.strategy_id ?? '').trim() === sid);
        if (!row) continue;
        const fam = bulkAutoFamily ? _inferFamilyFromSnapshotRow(row).family : String(row.family ?? 'trend');
        const stg = bulkAutoStage ? _suggestStageFromTier(row.tier) : String(row.stage ?? 'research');
        const tags = bulkAutoTag ? _autoTagsFromSnapshotRow(row) : (Array.isArray(row.tags) ? row.tags.map((x) => String(x ?? '').trim()).filter(Boolean) : []);
        items.push({ strategy_id: sid, source_zip: z, family: fam, stage: stg, tags });
        setBulkProgress((p) => (p ? { ...p, done: Math.min(total, p.done + 1) } : { total, done: 1, mode: 'classify' }));
      }
      if (items.length) {
        await upsertStrategyRegistry(items);
      }
    } catch (e) {
      setBulkProgress((p) => (p ? { ...p, error: _errText(e) } : { total, done: 0, error: _errText(e), mode: 'classify' }));
    } finally {
      setBulkBusy(false);
      bulkCancelRef.current = false;
      await refetchRegistry();
      await refetchSnapshot();
    }
  };

  const bulkRebacktestAndClassify = async () => {
    const selectedSids0 = Object.entries(bulkSelected).filter(([, v]) => Boolean(v)).map(([k]) => k).filter(Boolean);
    const maxN = Math.max(1, Math.min(100, Math.floor(bulkMaxN || 0) || 1));
    const selectedSids = selectedSids0.slice(0, maxN);
    const total = selectedSids.length;
    if (!total) {
      setBulkProgress({ total: 0, done: 0, error: 'no_selected', mode: 'rebacktest' });
      return;
    }
    bulkCancelRef.current = false;
    setBulkBusy(true);
    setBulkProgress({ total, done: 0, mode: 'rebacktest' });
    try {
      for (const sid of selectedSids) {
        if (bulkCancelRef.current) break;
        setBulkProgress((p) => (p ? { ...p, current: sid } : { total, done: 0, current: sid, mode: 'rebacktest' }));
        const resp = (await runAndSyncStrategyRegistry({
          strategy_id: sid,
          config: runConfig.trim() || undefined,
          timerange: runTimerange.trim() || undefined,
          timeout_sec: runTimeoutSec,
          deep_robustness: deepRobustness,
        })) as StrategyRegistryRunAndSyncResponse;
        if (!resp.ok) {
          setBulkProgress((p) => (p ? { ...p, done: Math.min(total, p.done + 1), error: String(resp.error || 'run_and_sync_failed') } : { total, done: 1, mode: 'rebacktest', error: String(resp.error || 'run_and_sync_failed') }));
          continue;
        }
        const zipName = String((resp.backtest as Record<string, unknown> | undefined)?.result_zip ?? '').trim();
        const entry = ((resp.sync as { entry?: unknown } | undefined)?.entry as StrategyRegistryEntry | undefined) ?? undefined;
        const tier0 = entry?.tier;
        const msObj = ((resp.backtest as { metrics_summary?: unknown } | undefined)?.metrics_summary && typeof (resp.backtest as { metrics_summary?: unknown }).metrics_summary === 'object')
          ? ((resp.backtest as { metrics_summary?: unknown }).metrics_summary as Record<string, unknown>)
          : undefined;
        if (zipName) {
          const fam = bulkAutoFamily ? _inferFamilyFromMetricsObj(msObj ?? null).family : String(entry?.family ?? 'trend');
          const stg = bulkAutoStage ? _suggestStageFromTier(tier0) : String(entry?.stage ?? 'research');
          const tags = bulkAutoTag ? _autoTagsFromMetricsObj(msObj ?? null) : (Array.isArray(entry?.tags) ? entry?.tags : []);
          await upsertStrategyRegistry([{ strategy_id: sid, source_zip: zipName, family: fam, stage: stg, tags }]);
        }
        setBulkProgress((p) => (p ? { ...p, done: Math.min(total, p.done + 1) } : { total, done: 1, mode: 'rebacktest' }));
      }
    } catch (e) {
      setBulkProgress((p) => (p ? { ...p, error: _errText(e) } : { total, done: 0, error: _errText(e), mode: 'rebacktest' }));
    } finally {
      setBulkBusy(false);
      bulkCancelRef.current = false;
      await refetchBtResults();
      await refetchRegistry();
      await refetchSnapshot();
    }
  };

  const getDraft = (sid: string, row: StrategyLibrarySnapshotRow): RegistryDraft => {
    const k = _registryKey(sid, snapshotZip);
    const existing = drafts[k];
    if (existing) return existing;
    const reg = _pickRegistryEntry(regEntries, sid, snapshotZip);
    const mergedFamily = String(reg?.family ?? row.family ?? 'trend');
    const mergedStage = String(reg?.stage ?? row.stage ?? 'research');
    const mergedRobust = _normRobust(reg?.robustness ?? row.robustness ?? 'unknown');
    const mergedTags = Array.isArray(reg?.tags) ? reg.tags : Array.isArray(row.tags) ? row.tags : [];
    const mergedEcon = String(reg?.econ_driver ?? '') || mergedFamily;
    const mergedLifecycle = String(reg?.lifecycle_state ?? '');
    const mergedRolloutStatus = String((reg?.rollout as Record<string, unknown> | undefined)?.status ?? '');
    const mergedRollbackTo = String((reg?.rollback as Record<string, unknown> | undefined)?.to_bundle_id ?? '');
    return {
      family: mergedFamily,
      stage: mergedStage,
      robustness: mergedRobust,
      tagsText: mergedTags.join(', '),
      econDriver: mergedEcon,
      evalPolicyRef: String(reg?.eval_policy_ref ?? ''),
      owner: String(reg?.owner ?? ''),
      approvedBy: String(reg?.approved_by ?? ''),
      approvedAt: String(reg?.approved_at ?? ''),
      lifecycleState: mergedLifecycle,
      rolloutStatus: mergedRolloutStatus,
      rollbackToBundleId: mergedRollbackTo,
      tierOverride: '',
      deprecateReason: '',
      traceId: '',
      actor: '',
      note: '',
    };
  };

  const ensureTraceId = (sid: string): string => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, { strategy_id: sid, family: 'trend', stage: 'research', tags: [], robustness: 'unknown', tier: 'unrated' });
    const existing = draft.traceId.trim();
    if (existing) return existing;
    const gen = `ui_${Date.now()}_${sid}`;
    setDrafts((p) => ({ ...p, [k]: { ...draft, traceId: gen } }));
    return gen;
  };

  const saveRow = async (sid: string, row: StrategyLibrarySnapshotRow) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, row);
    setSaving((p) => ({ ...p, [k]: true }));
    setSaveState((p) => ({ ...p, [k]: 'idle' }));
    setSaveError((p) => ({ ...p, [k]: undefined }));
    try {
      const tags = draft.tagsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const payload: StrategyRegistryEntry = {
        strategy_id: sid,
        source_zip: snapshotZip,
        family: draft.family.trim() || 'trend',
        stage: draft.stage.trim() || 'research',
        tags,
        robustness: draft.robustness.trim() || 'unknown',
        econ_driver: draft.econDriver.trim() || undefined,
        eval_policy_ref: draft.evalPolicyRef.trim() || undefined,
        owner: draft.owner.trim() || undefined,
      };
      const resp = await upsertStrategyRegistry([payload]);
      if (!resp.ok) {
        setSaveState((p) => ({ ...p, [k]: 'error' }));
        setSaveError((p) => ({ ...p, [k]: String(resp.error || 'save_failed') }));
        return;
      }
      setSaveState((p) => ({ ...p, [k]: 'ok' }));
      await refetchSnapshot();
    } catch {
      setSaveState((p) => ({ ...p, [k]: 'error' }));
      setSaveError((p) => ({ ...p, [k]: 'save_failed' }));
    } finally {
      setSaving((p) => ({ ...p, [k]: false }));
    }
  };

  const buildRow = async (sid: string, row: StrategyLibrarySnapshotRow) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, row);
    setBuilding((p) => ({ ...p, [k]: true }));
    setBuilds((p) => ({ ...p, [k]: { ...(p[k] ?? {}), error: undefined } }));
    try {
      const tags = draft.tagsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const resp = (await buildStrategyBundle({
        zip: effectiveZip || undefined,
        strategy_id: sid,
        family: draft.family.trim() || row.family,
        stage: draft.stage.trim() || row.stage,
        tags,
        eval_policy_ref: draft.evalPolicyRef.trim() || undefined,
      })) as StrategyBundleBuildResponse;
      if (!resp.ok) {
        setBuilds((p) => ({ ...p, [k]: { error: resp.error || 'build_failed' } }));
        return;
      }
      const dl = resp.bundle ? strategyBundleDownloadUrl(resp.bundle) : resp.download_url ? resp.download_url : undefined;
      setBuilds((p) => ({
        ...p,
        [k]: {
          bundle: resp.bundle,
          downloadUrl: dl,
          bundleId: resp.bundle_id,
          tier: resp.tier,
          tierReason: resp.tier_reason,
        },
      }));

      if (resp.bundle_id) {
        try {
          const tags2 = draft.tagsText
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean);
          await upsertStrategyRegistry([
            {
              strategy_id: sid,
              source_zip: snapshotZip,
              family: draft.family.trim() || 'trend',
              stage: draft.stage.trim() || 'research',
              tags: tags2,
              robustness: draft.robustness.trim() || 'unknown',
              eval_policy_ref: draft.evalPolicyRef.trim() || undefined,
              owner: draft.owner.trim() || undefined,
              bundle_id: String(resp.bundle_id),
              tier: resp.tier || undefined,
              tier_reason: resp.tier_reason || undefined,
            },
          ]);
          await refetchRegistry();
        } catch {
          setBuilds((p) => p);
        }
      }
    } catch (e) {
      setBuilds((p) => ({ ...p, [k]: { error: _errText(e) } }));
    } finally {
      setBuilding((p) => ({ ...p, [k]: false }));
    }
  };

  const verifyRow = async (sid: string, row: StrategyLibrarySnapshotRow) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, row);
    setVerifying((p) => ({ ...p, [k]: true }));
    setVerifyState((p) => ({ ...p, [k]: { ok: undefined, error: undefined } }));
    try {
      const tags = draft.tagsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const resp = await syncStrategyRegistryFromZip({
        zip: snapshotZip,
        strategy_id: sid,
        family: draft.family.trim() || row.family,
        stage: draft.stage.trim() || row.stage,
        tags,
        robustness: draft.robustness.trim() === 'unknown' ? undefined : draft.robustness.trim(),
        econ_driver: draft.econDriver.trim() || undefined,
        eval_policy_ref: draft.evalPolicyRef.trim() || undefined,
        owner: draft.owner.trim() || undefined,
      });
      if (!resp.ok) {
        setVerifyState((p) => ({ ...p, [k]: { ok: false, error: resp.error || 'verify_failed' } }));
        return;
      }
      setVerifyState((p) => ({ ...p, [k]: { ok: true } }));
      await refetchRegistry();
      await refetchSnapshot();
    } catch (e) {
      setVerifyState((p) => ({ ...p, [k]: { ok: false, error: _errText(e) } }));
    } finally {
      setVerifying((p) => ({ ...p, [k]: false }));
    }
  };

  const runAndVerifyRow = async (sid: string, row: StrategyLibrarySnapshotRow) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, row);
    setRunning((p) => ({ ...p, [k]: true }));
    setRunState((p) => ({ ...p, [k]: { ok: undefined, error: undefined } }));
    try {
      const tags = draft.tagsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const resp = (await runAndSyncStrategyRegistry({
        strategy_id: sid,
        family: draft.family.trim() || row.family,
        stage: draft.stage.trim() || row.stage,
        tags,
        robustness: draft.robustness.trim() === 'unknown' ? undefined : draft.robustness.trim(),
        econ_driver: draft.econDriver.trim() || undefined,
        eval_policy_ref: draft.evalPolicyRef.trim() || undefined,
        owner: draft.owner.trim() || undefined,
        config: runConfig.trim() || undefined,
        timerange: runTimerange.trim() || undefined,
        timeout_sec: runTimeoutSec,
        deep_robustness: deepRobustness,
      })) as StrategyRegistryRunAndSyncResponse;
      if (!resp.ok) {
        setRunState((p) => ({ ...p, [k]: { ok: false, error: resp.error || 'run_failed' } }));
        return;
      }
      const zipName = String((resp.backtest as Record<string, unknown> | undefined)?.result_zip ?? '').trim();
      if (zipName) {
        setZip(zipName);
      }
      const syncOk = Boolean((resp.sync as Record<string, unknown> | undefined)?.ok);
      if (!syncOk) {
        setRunState((p) => ({ ...p, [k]: { ok: false, error: String((resp.sync as Record<string, unknown> | undefined)?.error ?? 'sync_failed') } }));
        return;
      }
      setRunState((p) => ({ ...p, [k]: { ok: true } }));
      await refetchBtResults();
      await refetchRegistry();
      await refetchSnapshot();
    } catch (e) {
      setRunState((p) => ({ ...p, [k]: { ok: false, error: _errText(e) } }));
    } finally {
      setRunning((p) => ({ ...p, [k]: false }));
    }
  };

  const downloadVerifyFromRepo = async () => {
    const repo_url = repoUrl.trim();
    const strategyName = repoStrategyName.trim();
    if (!repo_url || !strategyName) {
      setRepoState({ ok: false, error: 'missing_repo_url_or_strategy_name' });
      return;
    }
    setRepoBusy(true);
    setRepoState(null);
    setRepoProgress({
      steps: { fetch: 'running', backtest: 'idle', registry: 'idle', bundle: 'idle', approval: 'idle' },
      ts: { fetch: Date.now() },
    });
    try {
      const fetchResp = (await repoFetchStrategyStub({
        repo_url,
        branch: repoBranch.trim() || undefined,
        commit: repoCommit.trim() || undefined,
        path: repoPath.trim() || undefined,
        strategy_name: strategyName,
      })) as RepoFetchStrategyResponse;
      if (!fetchResp.ok) {
        const err = String(fetchResp.error || fetchResp.detail || 'repo_fetch_failed');
        const errNice = err === 'duplicate_strategy_same_content' ? '同名策略已存在且内容一致，拒绝入库' : err;
        setRepoState({ ok: false, error: errNice });
        setRepoProgress((p) => (p ? { ...p, steps: { ...p.steps, fetch: 'fail' }, ts: { ...p.ts, fetch: Date.now() }, error: errNice } : p));
        return;
      }
      const effectiveName = String(fetchResp.strategy_name_effective ?? strategyName).trim() || strategyName;
      setRepoProgress((p) => {
        const traceId = String(fetchResp.trace_id ?? '').trim();
        const approvalId = fetchResp.approval_id == null ? null : String(fetchResp.approval_id);
        return p
          ? {
              ...p,
              trace_id: traceId || p.trace_id,
              approval_id: approvalId || p.approval_id || null,
              steps: { ...p.steps, fetch: 'ok', backtest: 'running', approval: approvalId ? 'ok' : p.steps.approval },
              ts: { ...p.ts, fetch: Date.now(), backtest: Date.now(), approval: approvalId ? Date.now() : p.ts.approval },
            }
          : p;
      });
      const sandboxPath = String(fetchResp.sandbox_path ?? '').trim();
      if (!sandboxPath) {
        setRepoState({ ok: false, error: 'missing_sandbox_path' });
        setRepoProgress((p) => (p ? { ...p, steps: { ...p.steps, backtest: 'fail' }, error: 'missing_sandbox_path', ts: { ...p.ts, backtest: Date.now() } } : p));
        return;
      }
      const btResp = (await runAutomationBacktest({
        config: runConfig.trim() || undefined,
        timerange: runTimerange.trim() || undefined,
        strategy: effectiveName,
        sandbox_path: sandboxPath,
        strategy_name: effectiveName,
        timeout_sec: runTimeoutSec,
      })) as AutomationBacktestRunResponse;
      if (!btResp.ok) {
        const e = String(btResp.error || '').trim();
        const stderr = String(btResp.stderr || '').trim();
        const stdout = String(btResp.stdout || '').trim();
        const detail = stderr || stdout;
        const msg = e || (detail ? detail.slice(-800) : 'backtest_failed');
        setRepoState({ ok: false, error: msg });
        setRepoProgress((p) => (p ? { ...p, steps: { ...p.steps, backtest: 'fail' }, error: msg, ts: { ...p.ts, backtest: Date.now() } } : p));
        return;
      }
      const zipName = String(btResp.result_zip ?? '').trim();
      if (!zipName) {
        setRepoState({ ok: false, error: 'missing_result_zip' });
        setRepoProgress((p) => (p ? { ...p, steps: { ...p.steps, backtest: 'fail' }, error: 'missing_result_zip', ts: { ...p.ts, backtest: Date.now() } } : p));
        return;
      }
      setZip(zipName);
      setRepoProgress((p) => (p ? { ...p, steps: { ...p.steps, backtest: 'ok', registry: 'running' }, ts: { ...p.ts, backtest: Date.now(), registry: Date.now() } } : p));

      const tags = repoTagsText
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      const syncResp = await syncStrategyRegistryFromZip({
        zip: zipName,
        strategy_id: effectiveName,
        family: repoFamily,
        stage: repoStage,
        tags,
        econ_driver: repoEconDriver.trim() || undefined,
        eval_policy_ref: repoEvalPolicyRef.trim() || undefined,
        owner: repoOwner.trim() || undefined,
        n_slices: 6,
        n_bootstrap: deepRobustness ? 200 : 0,
        n_shuffle: deepRobustness ? 200 : 0,
      });
      if (!syncResp.ok) {
        setRepoState({ ok: false, error: String(syncResp.error || 'sync_failed'), zip: zipName });
        setRepoProgress((p) => (p ? { ...p, steps: { ...p.steps, registry: 'fail' }, error: String(syncResp.error || 'sync_failed'), ts: { ...p.ts, registry: Date.now() } } : p));
        return;
      }
      setRepoProgress((p) => (p ? { ...p, steps: { ...p.steps, registry: 'ok', bundle: repoBuildBundle ? 'running' : 'ok' }, ts: { ...p.ts, registry: Date.now(), bundle: Date.now() } } : p));

      const srcCommit = String(fetchResp.commit ?? repoCommit).trim();
      const source: Record<string, unknown> = {
        kind: 'github',
        repo_url,
        branch: repoBranch.trim() || undefined,
        commit: srcCommit || undefined,
        path: repoPath.trim() || undefined,
        sandbox_path: sandboxPath,
        repo_id: fetchResp.repo_id,
      };
      await upsertStrategyRegistry([
        {
          strategy_id: effectiveName,
          source_zip: zipName,
          family: repoFamily,
          stage: repoStage,
          tags,
          robustness: _normRobust(syncResp.entry?.robustness ?? 'unknown'),
          econ_driver: repoEconDriver.trim() || undefined,
          eval_policy_ref: repoEvalPolicyRef.trim() || undefined,
          owner: repoOwner.trim() || undefined,
          source,
        },
      ]);

      let builtBundle: string | undefined;
      if (repoBuildBundle) {
        const b = (await buildStrategyBundle({
          zip: zipName,
          strategy_id: effectiveName,
          family: repoFamily,
          stage: repoStage,
          tags,
          eval_policy_ref: repoEvalPolicyRef.trim() || undefined,
        })) as StrategyBundleBuildResponse;
        if (b.ok && b.bundle) {
          builtBundle = b.bundle;
        }
      }

      setRepoState({ ok: true, zip: zipName, bundle: builtBundle });
      setRepoProgress((p) => (p ? { ...p, steps: { ...p.steps, bundle: 'ok' }, ts: { ...p.ts, bundle: Date.now() } } : p));
      await refetchBtResults();
      await refetchRegistry();
      await refetchSnapshot();
    } catch (e) {
      setRepoState({ ok: false, error: _errText(e) });
      setRepoProgress((p) => (p ? { ...p, error: _errText(e), steps: { ...p.steps, fetch: p.steps.fetch === 'running' ? 'fail' : p.steps.fetch } } : p));
    } finally {
      setRepoBusy(false);
    }
  };

  const rolloutRow = async (sid: string) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, { strategy_id: sid, family: 'trend', stage: 'research', tags: [], robustness: 'unknown', tier: 'unrated' });
    setGovBusy((p) => ({ ...p, [k]: true }));
    try {
      const traceId = ensureTraceId(sid);
      const resp = await appendStrategyRegistryEvent({
        strategy_id: sid,
        source_zip: snapshotZip,
        kind: 'rollout',
        trace_id: traceId,
        actor: draft.actor.trim() || undefined,
        note: draft.note.trim() || undefined,
        payload: {
          status: draft.rolloutStatus.trim() || 'planned',
          lifecycle_state: draft.lifecycleState.trim() || undefined,
          since_ts: Date.now(),
        },
      });
      if (!resp.ok) return;
      await refetchRegistry();
    } finally {
      setGovBusy((p) => ({ ...p, [k]: false }));
    }
  };

  const lifecycleRow = async (sid: string) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, { strategy_id: sid, family: 'trend', stage: 'research', tags: [], robustness: 'unknown', tier: 'unrated' });
    setGovBusy((p) => ({ ...p, [k]: true }));
    try {
      const to = draft.lifecycleState.trim();
      if (!to) return;
      const traceId = ensureTraceId(sid);
      const resp = await appendStrategyRegistryEvent({
        strategy_id: sid,
        source_zip: snapshotZip,
        kind: 'lifecycle',
        trace_id: traceId,
        actor: draft.actor.trim() || undefined,
        note: draft.note.trim() || undefined,
        payload: {
          lifecycle_state: to,
          approved_by: draft.approvedBy.trim() || undefined,
          approved_at: draft.approvedAt.trim() || undefined,
        },
      });
      if (!resp.ok) return;
      await refetchRegistry();
      await refetchSnapshot();
    } finally {
      setGovBusy((p) => ({ ...p, [k]: false }));
    }
  };

  const rollbackRow = async (sid: string) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, { strategy_id: sid, family: 'trend', stage: 'research', tags: [], robustness: 'unknown', tier: 'unrated' });
    setGovBusy((p) => ({ ...p, [k]: true }));
    try {
      const toBundleId = draft.rollbackToBundleId.trim();
      if (!toBundleId) return;
      const traceId = ensureTraceId(sid);
      const resp = await appendStrategyRegistryEvent({
        strategy_id: sid,
        source_zip: snapshotZip,
        kind: 'rollback',
        trace_id: traceId,
        actor: draft.actor.trim() || undefined,
        note: draft.note.trim() || undefined,
        payload: {
          to_bundle_id: toBundleId,
        },
      });
      if (!resp.ok) return;
      await refetchRegistry();
    } finally {
      setGovBusy((p) => ({ ...p, [k]: false }));
    }
  };

  const tierChangeRow = async (sid: string) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, { strategy_id: sid, family: 'trend', stage: 'research', tags: [], robustness: 'unknown', tier: 'unrated' });
    setGovBusy((p) => ({ ...p, [k]: true }));
    try {
      const t = draft.tierOverride.trim() || undefined;
      if (!t) return;
      const traceId = ensureTraceId(sid);
      const note = draft.note.trim() || `tier_change:${t}`;
      const resp = await appendStrategyRegistryEvent({
        strategy_id: sid,
        source_zip: snapshotZip,
        kind: 'tier_change',
        trace_id: traceId,
        actor: draft.actor.trim() || undefined,
        note,
        payload: {
          tier: t,
        },
      });
      if (!resp.ok) return;
      await refetchRegistry();
      await refetchSnapshot();
    } finally {
      setGovBusy((p) => ({ ...p, [k]: false }));
    }
  };

  const deprecateRow = async (sid: string) => {
    const k = _registryKey(sid, snapshotZip);
    const draft = getDraft(sid, { strategy_id: sid, family: 'trend', stage: 'research', tags: [], robustness: 'unknown', tier: 'unrated' });
    setGovBusy((p) => ({ ...p, [k]: true }));
    try {
      const reason = draft.deprecateReason.trim();
      if (!reason) return;
      const traceId = ensureTraceId(sid);
      const resp = await appendStrategyRegistryEvent({
        strategy_id: sid,
        source_zip: snapshotZip,
        kind: 'deprecate',
        trace_id: traceId,
        actor: draft.actor.trim() || undefined,
        note: draft.note.trim() || undefined,
        payload: {
          reason,
        },
      });
      if (!resp.ok) return;
      await refetchRegistry();
      await refetchSnapshot();
    } finally {
      setGovBusy((p) => ({ ...p, [k]: false }));
    }
  };

  const toggleEvents = async (sid: string) => {
    const k = _registryKey(sid, snapshotZip);
    const next = !eventsOpen[k];
    setEventsOpen((p) => ({ ...p, [k]: next }));
    if (!next) return;
    if (eventsByKey[k] && eventsByKey[k].length > 0) return;
    setEventsLoading((p) => ({ ...p, [k]: true }));
    try {
      const resp = await fetchStrategyRegistryEvents({ strategy_id: sid, source_zip: snapshotZip, limit: 50 });
      if (!resp.ok) return;
      setEventsByKey((p) => ({ ...p, [k]: (resp.events ?? []) as StrategyRegistryEvent[] }));
    } finally {
      setEventsLoading((p) => ({ ...p, [k]: false }));
    }
  };

  const zipList = useMemo(() => {
    const r = btResults as BacktestResultsResponse | undefined;
    return (r?.results ?? []).map((x) => x.name);
  }, [btResults]);

  const registryCount = regEntries.length;

  const feederCtlPhrase = useMemo(() => {
    const sid = String(feederCtlRuntimeKey || '').trim();
    return sid ? `ADD ${sid} TO FEEDER` : '';
  }, [feederCtlRuntimeKey]);

  const openFeederControlled = (row: StrategyLibrarySnapshotRow) => {
    const sid = String(row.strategy_id ?? '').trim();
    if (!sid) return;
    setFeederCtlSource({ strategy_id: sid, source_zip: String(snapshotZip || '').trim() });
    setFeederCtlRuntimeKey(feederSupported[0] ?? 'Strategy005');
    setFeederCtlToken('');
    setFeederCtlConfirm('');
    setFeederCtlState(null);
    setFeederCtlOpen(true);
  };

  const feederControlledApply = async (mode: 'enable' | 'disable' | 'remove') => {
    if (feederCtlBusy) return;
    const token = String(feederCtlToken || '').trim();
    if (!token) {
      setFeederCtlState({ ok: false, error: 'missing_token' });
      return;
    }
    const phrase = feederCtlPhrase;
    if (!phrase || String(feederCtlConfirm || '').trim() !== phrase) {
      setFeederCtlState({ ok: false, error: 'confirm_phrase_mismatch' });
      return;
    }
    const runtimeKey = String(feederCtlRuntimeKey || '').trim();
    if (!runtimeKey || !feederSupported.includes(runtimeKey)) {
      setFeederCtlState({ ok: false, error: 'invalid_runtime_strategy' });
      return;
    }
    const current = (autoCfg?.strategy_feeders ?? []) as Array<{ strategy_id?: unknown; coins?: unknown; trigger_decision?: unknown; emit?: unknown }>;
    const beforeList = current.map((x) => `${String(x.strategy_id ?? '').trim()}:${x.emit ? 'on' : 'off'}`).filter(Boolean);
    const before = beforeList.join(', ');
    const next: Array<{ strategy_id: string; coins: string[]; trigger_decision: boolean; emit: boolean }> = [];
    for (const x of current) {
      const sid = String(x.strategy_id ?? '').trim();
      if (!sid) continue;
      next.push({
        strategy_id: sid,
        coins: Array.isArray(x.coins) ? (x.coins as unknown[]).map((c) => String(c ?? '').trim()).filter(Boolean) : [],
        trigger_decision: Boolean(x.trigger_decision),
        emit: Boolean(x.emit),
      });
    }
    const idx = next.findIndex((x) => x.strategy_id === runtimeKey);
    if (mode === 'enable') {
      if (idx >= 0) next[idx] = { ...next[idx], emit: true, trigger_decision: true };
      else next.push({ strategy_id: runtimeKey, coins: [], trigger_decision: true, emit: true });
    } else if (mode === 'disable') {
      if (idx >= 0) next[idx] = { ...next[idx], emit: false };
      else next.push({ strategy_id: runtimeKey, coins: [], trigger_decision: true, emit: false });
    } else if (mode === 'remove') {
      if (idx >= 0) next.splice(idx, 1);
    }
    const afterList = next.map((x) => `${x.strategy_id}:${x.emit ? 'on' : 'off'}`).filter(Boolean);
    const after = afterList.join(', ');
    const payload = {
      trace_id: `ui_${Date.now()}_library_feeder_ctl_${runtimeKey}_${mode}`,
      confirm_live: true,
      enable_strategy_feeders: mode === 'enable' ? true : Boolean(autoCfg?.enable_strategy_feeders),
      feeders_period_seconds: Number(autoCfg?.feeders_period_seconds ?? 30) || 30,
      strategy_feeders: next,
    };
    setFeederCtlBusy(true);
    setFeederCtlState(null);
    try {
      const res = await api.post('/automation/strategies/config', payload, {
        headers: {
          'X-Webhook-Token': token,
          'X-Execute-Token': token,
          'X-Config-Token': token,
        },
      });
      const ok = Boolean((res.data as { ok?: unknown } | undefined)?.ok);
      if (!ok) {
        const err = String((res.data as { error?: unknown } | undefined)?.error ?? 'apply_failed');
        setFeederCtlState({ ok: false, error: err, before, after });
        return;
      }
      setFeederCtlState({ ok: true, before, after });
      await refetchAutomation();
    } catch (e) {
      setFeederCtlState({ ok: false, error: _errText(e ?? 'apply_failed'), before, after });
    } finally {
      setFeederCtlBusy(false);
      setFeederCtlToken('');
      setFeederCtlConfirm('');
    }
  };

  const importActive = async () => {
    setImportActiveBusy(true);
    setImportActiveState(null);
    try {
      const traceId = `ui_${Date.now()}_import_active`;
      const resp = await importActiveStrategiesToRegistry({ source_zip: '*', stage: 'deployment', trace_id: traceId });
      if (!resp.ok) {
        setImportActiveState({ ok: false, error: String(resp.error || 'import_failed'), trace_id: resp.trace_id });
        return;
      }
      setImportActiveState({ ok: true, saved: Number(resp.saved ?? 0), trace_id: resp.trace_id });
      await refetchRegistry();
      await refetchSnapshot();
    } catch (e) {
      setImportActiveState({ ok: false, error: _errText(e || 'import_failed') });
    } finally {
      setImportActiveBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>策略资产库</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-6 gap-4">
            <div className="md:col-span-2">
              <div className="text-xs text-slate-500 mb-1">Backtest zip</div>
              <select
                className="w-full border rounded h-10 px-3 bg-white"
                value={effectiveZip}
                onChange={(e) => setZip(e.target.value)}
              >
                {latestZip ? <option value={latestZip}>{latestZip} (latest)</option> : null}
                {zipList
                  .filter((x) => x !== latestZip)
                  .map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))}
              </select>
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">Zips limit</div>
              <select
                className="w-full border rounded h-10 px-3 bg-white"
                value={btResultsLimit}
                onChange={(e) => setBtResultsLimit(Number(e.target.value))}
              >
                <option value={10}>10</option>
                <option value={30}>30</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">Family</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={family} onChange={(e) => setFamily(e.target.value)}>
                <option value="all">all</option>
                <option value="trend">trend</option>
                <option value="mean_reversion">mean_reversion</option>
                <option value="carry">carry</option>
                <option value="breakout">breakout</option>
              </select>
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">Tier</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={tier} onChange={(e) => setTier(e.target.value)}>
                <option value="all">all</option>
                <option value="A">A</option>
                <option value="B">B</option>
                <option value="C">C</option>
                <option value="unrated">unrated</option>
              </select>
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">Stage</div>
              <select className="w-full border rounded h-10 px-3 bg-white" value={stage} onChange={(e) => setStage(e.target.value)}>
                <option value="all">all</option>
                <option value="research">research</option>
                <option value="model">model</option>
                <option value="deployment">deployment</option>
              </select>
            </div>

            <div>
              <div className="text-xs text-slate-500 mb-1">Search</div>
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="strategy_id / tags / tier_reason" />
            </div>

            <div className="md:col-span-6">
              <div className="grid grid-cols-1 md:grid-cols-6 gap-3">
                <div className="md:col-span-3">
                  <div className="text-xs text-slate-500 mb-1">Run config</div>
                  <Input value={runConfig} onChange={(e) => setRunConfig(e.target.value)} placeholder="user_data/config_local_backtest.json" />
                </div>
                <div className="md:col-span-2">
                  <div className="text-xs text-slate-500 mb-1">Run timerange</div>
                  <Input value={runTimerange} onChange={(e) => setRunTimerange(e.target.value)} placeholder="20240101-20250101" />
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">Timeout</div>
                  <Input
                    value={String(runTimeoutSec)}
                    onChange={(e) => setRunTimeoutSec(Number(e.target.value) || 1800)}
                    placeholder="1800"
                  />
                </div>
                <div className="md:col-span-6 flex items-center gap-2">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={deepRobustness}
                    onChange={(e) => setDeepRobustness(e.target.checked)}
                  />
                  <div className="text-xs text-slate-600">deep_robustness (bootstrap/shuffle)</div>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <div className="text-xs text-slate-500">registry: {registryCount}</div>
            <div className="text-xs text-slate-500">zip: {effectiveZip || '-'}</div>
            <div className="text-xs text-slate-500">rows: {rows.length}</div>
            <div className="text-xs text-slate-500">updated: {snapshotFetching ? 'fetching…' : _fmtTs((snapshot as StrategyLibrarySnapshotResponse | undefined)?.ts ?? 0)}</div>
            <div className="ml-auto flex items-center gap-2">
              <div className="text-xs text-slate-500">Sort</div>
              <select className="border rounded h-9 px-2 bg-white text-sm" value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="density_asc">signal_density ↑</option>
                <option value="dd_asc">max_dd ↑</option>
                <option value="tier_desc">tier ↓</option>
              </select>
              <Button variant="outline" onClick={() => void importActive()} disabled={importActiveBusy}>
                {importActiveBusy ? 'Importing…' : 'Import Active'}
              </Button>
              <Button variant="secondary" onClick={() => void refetchSnapshot()} disabled={snapshotFetching}>
                Refresh
              </Button>
            </div>
          </div>

          {importActiveState?.ok === true ? (
            <div className="mt-2 text-xs text-emerald-700">
              import_active ok: saved={String(importActiveState.saved ?? 0)} trace={String(importActiveState.trace_id ?? '')}
            </div>
          ) : null}
          {importActiveState?.ok === false ? (
            <div className="mt-2 text-xs text-rose-700">
              import_active error: {String(importActiveState.error || 'import_failed')}
              {importActiveState.trace_id ? ` trace=${String(importActiveState.trace_id)}` : ''}
            </div>
          ) : null}

          <details className="mt-4 border rounded bg-slate-50 px-3 py-2">
            <summary className="cursor-pointer text-sm text-slate-700 select-none">GitHub Download & Verify</summary>
            <div className="mt-3 grid grid-cols-1 md:grid-cols-6 gap-3">
              <div className="md:col-span-3">
                <div className="text-xs text-slate-500 mb-1">repo_url</div>
                <Input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/org/repo.git" />
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">branch</div>
                <Input value={repoBranch} onChange={(e) => setRepoBranch(e.target.value)} placeholder="main" />
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">commit</div>
                <Input value={repoCommit} onChange={(e) => setRepoCommit(e.target.value)} placeholder="(optional)" />
              </div>

              <div className="md:col-span-2">
                <div className="text-xs text-slate-500 mb-1">path</div>
                <Input value={repoPath} onChange={(e) => setRepoPath(e.target.value)} placeholder="strategies/" />
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">strategy_name</div>
                <Input value={repoStrategyName} onChange={(e) => setRepoStrategyName(e.target.value)} placeholder="Strategy005" />
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">family</div>
                <select className="w-full border rounded h-10 px-3 bg-white" value={repoFamily} onChange={(e) => setRepoFamily(e.target.value)}>
                  <option value="trend">trend</option>
                  <option value="mean_reversion">mean_reversion</option>
                  <option value="carry">carry</option>
                  <option value="breakout">breakout</option>
                </select>
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">stage</div>
                <select className="w-full border rounded h-10 px-3 bg-white" value={repoStage} onChange={(e) => setRepoStage(e.target.value)}>
                  <option value="research">research</option>
                  <option value="model">model</option>
                  <option value="deployment">deployment</option>
                </select>
              </div>

              <div className="md:col-span-2">
                <div className="text-xs text-slate-500 mb-1">tags</div>
                <Input value={repoTagsText} onChange={(e) => setRepoTagsText(e.target.value)} placeholder="mtf, vol_adj" />
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">econ_driver</div>
                <Input value={repoEconDriver} onChange={(e) => setRepoEconDriver(e.target.value)} placeholder="trend" />
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">eval_policy_ref</div>
                <Input value={repoEvalPolicyRef} onChange={(e) => setRepoEvalPolicyRef(e.target.value)} placeholder="p3_default" />
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">owner</div>
                <Input value={repoOwner} onChange={(e) => setRepoOwner(e.target.value)} placeholder="owner" />
              </div>

              <div className="md:col-span-6 flex items-center gap-2">
                <input type="checkbox" className="h-4 w-4" checked={repoBuildBundle} onChange={(e) => setRepoBuildBundle(e.target.checked)} />
                <div className="text-xs text-slate-600">build_bundle</div>
              </div>

              <div className="md:col-span-6 flex items-center gap-3">
                <Button onClick={() => void downloadVerifyFromRepo()} disabled={repoBusy}>
                  {repoBusy ? 'Working…' : 'Download & Verify'}
                </Button>
                {repoState?.ok === true ? (
                  <div className="text-xs text-emerald-700">
                    ok: {repoState.zip}
                    {repoState.bundle ? (
                      <a className="ml-2 underline" href={strategyBundleDownloadUrl(repoState.bundle)}>
                        bundle
                      </a>
                    ) : null}
                  </div>
                ) : null}
                {repoState?.ok === false ? <div className="text-xs text-rose-700">{repoState.error}</div> : null}
              </div>

              {repoProgress && repoProgressView ? (
                <div className="md:col-span-6 rounded border bg-slate-50 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="text-xs text-slate-500">供应链进度（拉取→入库→沙箱评估→分档→审批）</div>
                      <div className="text-sm font-semibold">
                        {repoProgressView.pct}%{repoProgress.trace_id ? ` · trace:${repoProgress.trace_id}` : ''}{repoProgress.approval_id ? ` · approval:${repoProgress.approval_id}` : ''}
                      </div>
                      {repoProgress.error ? <div className="text-xs text-rose-700 mt-1">{repoProgress.error}</div> : null}
                    </div>
                    {repoProgress.trace_id ? (
                      <Link className="text-xs underline" to={`/agent/ops?trace_id=${encodeURIComponent(repoProgress.trace_id)}#approvals`}>
                        去运维/审批观测
                      </Link>
                    ) : null}
                  </div>
                  <div className="mt-2 h-2 rounded bg-slate-200 overflow-hidden">
                    <div className="h-2 bg-emerald-500" style={{ width: `${repoProgressView.pct}%` }} />
                  </div>
                  <div className="mt-2 grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
                    {repoProgressView.order.map((k) => {
                      const label = k === 'fetch' ? '拉取/扫描' : k === 'backtest' ? '沙箱回测' : k === 'registry' ? '入库' : k === 'bundle' ? '产物打包' : '审批';
                      const st = repoProgress.steps[k];
                      const ts = Number(repoProgress.ts[k] ?? 0);
                      const badge = st === 'ok' ? 'secondary' : st === 'fail' ? 'destructive' : 'outline';
                      const stText = st === 'ok' ? 'DONE' : st === 'fail' ? 'FAIL' : st === 'running' ? 'RUN' : 'WAIT';
                      return (
                        <div key={k} className="flex items-center justify-between rounded border bg-white px-2 py-1">
                          <span className="truncate">{label}</span>
                          <span className="flex items-center gap-2">
                            {ts > 0 ? <Badge variant="outline">{_fmtTs(ts)}</Badge> : null}
                            <Badge variant={badge as 'outline' | 'secondary' | 'destructive'}>{stText}</Badge>
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </div>
          </details>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Library Rows</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded border bg-slate-50 p-3 mb-3 space-y-2 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Badge variant="outline">selected: {bulkSelectedCount}</Badge>
                <Badge variant="outline">zip: {snapshotZip || '-'}</Badge>
                {bulkProgress ? <Badge variant={bulkProgress.error ? 'destructive' : 'secondary'}>{bulkProgress.mode}:{bulkProgress.done}/{bulkProgress.total}{bulkProgress.current ? ` · ${bulkProgress.current}` : ''}</Badge> : null}
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => bulkSelectAllVisible()}>全选（当前列表）</Button>
                <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => bulkClearSelection()}>清空</Button>
                <Button size="sm" variant="outline" disabled={!bulkBusy} onClick={() => bulkStop()}>停止</Button>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-4 text-xs text-slate-700">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={bulkAutoTag} onChange={(e) => setBulkAutoTag(Boolean(e.target.checked))} />
                <span>智能标签</span>
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={bulkAutoFamily} onChange={(e) => setBulkAutoFamily(Boolean(e.target.checked))} />
                <span>智能 family</span>
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={bulkAutoStage} onChange={(e) => setBulkAutoStage(Boolean(e.target.checked))} />
                <span>智能 stage（按 tier）</span>
              </label>
              <div className="flex items-center gap-2">
                <span>max_n</span>
                <Input className="w-24" value={String(bulkMaxN)} onChange={(e) => setBulkMaxN(Number(e.target.value) || 1)} />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={bulkBusy || !snapshotZip} onClick={() => void bulkClassifyFromSnapshot()}>仅分类（用现有指标）</Button>
              <Button size="sm" variant="outline" disabled={bulkBusy} onClick={() => void bulkRebacktestAndClassify()}>复评回测并分类（耗时）</Button>
              {bulkProgress?.error ? <div className="text-xs text-rose-700 break-words">error: {bulkProgress.error}</div> : null}
            </div>
          </div>
          <div className="overflow-auto border rounded">
            <table className="min-w-[1400px] w-full text-sm">
              <thead className="bg-slate-50 text-slate-600">
                <tr>
                  <th className="text-left p-2">sel</th>
                  <th className="text-left p-2">strategy_id</th>
                  <th className="text-left p-2">source_zip</th>
                  <th className="text-left p-2">family</th>
                  <th className="text-left p-2">tier</th>
                  <th className="text-left p-2">stage</th>
                  <th className="text-left p-2">robust</th>
                  <th className="text-right p-2">pf</th>
                  <th className="text-right p-2">max_dd</th>
                  <th className="text-right p-2">winrate</th>
                  <th className="text-right p-2">trades</th>
                  <th className="text-right p-2">days</th>
                  <th className="text-right p-2">signal_density</th>
                  <th className="text-right p-2">p50</th>
                  <th className="text-left p-2">extras</th>
                  <th className="text-left p-2">tags</th>
                  <th className="text-left p-2">tier_reason</th>
                  <th className="text-left p-2">registry</th>
                  <th className="text-left p-2">bundle</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const sid = String(r.strategy_id);
                  const k = _registryKey(sid, snapshotZip);
                  const reg = _pickRegistryEntry(regEntries, sid, snapshotZip);
                  const draft = getDraft(sid, r);
                  const pf = _toNum(r.metrics?.profit_factor, NaN);
                  const dd = _toNum(r.metrics?.max_drawdown_pct, NaN);
                  const wr = _toNum(r.metrics?.winrate, NaN);
                  const trades = _toNum(r.metrics?.trades, NaN);
                  const days = _toNum(r.metrics?.backtest_days, NaN);
                  const sd = _toNum(r.extras?.signal_density, NaN);
                  const p50 = _toNum(r.signal_density_p50, NaN);
                  const tierUpper = String(r.tier ?? 'unrated').toUpperCase();
                  const tierBadge = tierUpper === 'A' ? 'bg-emerald-600 text-white' : tierUpper === 'B' ? 'bg-emerald-200 text-slate-900' : tierUpper === 'C' ? 'bg-amber-200 text-slate-900' : 'bg-slate-100 text-slate-700';
                  const build = builds[k];
                  const savingNow = Boolean(saving[k]);
                  const saveSt = saveState[k] ?? 'idle';
                  const saveErr = saveError[k];
                  const buildingNow = Boolean(building[k]);
                  const verifyingNow = Boolean(verifying[k]);
                  const runningNow = Boolean(running[k]);
                  const govNow = Boolean(govBusy[k]);
                  const vState = verifyState[k];
                  const rState = runState[k];
                  const extrasBits: string[] = [];
                  const fam = String(r.family ?? '').toLowerCase();
                  if (fam === 'mean_reversion') {
                    const tail = _toNum(r.extras?.tail_loss_ratio, NaN);
                    const mcl = _toNum(r.extras?.max_consecutive_losses, NaN);
                    if (Number.isFinite(tail)) extrasBits.push(`tail=${tail.toFixed(2)}`);
                    if (Number.isFinite(mcl)) extrasBits.push(`mcl=${Math.trunc(mcl)}`);
                  } else {
                    const awlr = _toNum(r.extras?.avg_win_loss_ratio, NaN);
                    if (Number.isFinite(awlr)) extrasBits.push(`awlr=${awlr.toFixed(2)}`);
                  }
                  const timeframe = String(reg?.timeframe ?? (reg?.backtest_spec as Record<string, unknown> | undefined)?.timeframe ?? '').trim();
                  const leverageMode = String(reg?.leverage_mode ?? '').trim();
                  const pu = reg?.pair_universe;
                  const pairN = Array.isArray(pu) ? pu.length : NaN;
                  const idxBits: string[] = [];
                  const feats = reg?.features as Record<string, unknown> | undefined;
                  const gid = String(feats?.group_id ?? '').trim();
                  const fsid = String(feats?.feature_set_id ?? '').trim();
                  if (gid) idxBits.push(`g=${gid}`);
                  if (fsid) idxBits.push(`fs=${fsid}`);
                  if (timeframe) idxBits.push(`tf=${timeframe}`);
                  if (Number.isFinite(pairN)) idxBits.push(`pairs=${Math.trunc(pairN)}`);
                  if (leverageMode) idxBits.push(`lev=${leverageMode}`);
                  const src = (reg?.source as Record<string, unknown> | undefined) ?? undefined;
                  const mirrorPath = String(src?.asset_mirror_path ?? '').trim();
                  const assetLinksRaw = src?.asset_links;
                  const assetLinks = Array.isArray(assetLinksRaw) ? assetLinksRaw.map((x) => String(x ?? '').trim()).filter(Boolean) : [];
                  const assetBucket = (src?.asset_bucket as Record<string, unknown> | undefined) ?? undefined;
                  const bucketText = assetBucket ? `bucket:${String(assetBucket.family ?? '-')}/${String(assetBucket.stage ?? '-')}/${String(assetBucket.tier ?? '-')}/${String(assetBucket.market ?? '-')}` : '';

                  return (
                    <tr key={k} className="border-t">
                      <td className="p-2">
                        <input
                          type="checkbox"
                          disabled={bulkBusy}
                          checked={Boolean(bulkSelected[sid])}
                          onChange={(e) => setBulkSelected((p) => ({ ...p, [sid]: Boolean(e.target.checked) }))}
                        />
                      </td>
                      <td className="p-2 font-mono text-xs">
                        <div className="flex items-center gap-2">
                          <span>{sid}</span>
                          {(() => {
                            const cap = feederDirectionById[sid];
                            if (cap === 'long_short') {
                              return <Badge className="text-[10px] leading-none px-1.5 py-0.5" variant="secondary">LONG/SHORT</Badge>;
                            }
                            if (cap === 'long_only') {
                              return <Badge className="text-[10px] leading-none px-1.5 py-0.5" variant="outline">LONG ONLY</Badge>;
                            }
                            return null;
                          })()}
                        </div>
                      </td>
                      <td className="p-2 font-mono text-xs">{snapshotZip || '-'}</td>
                      <td className="p-2">{String(r.family)}</td>
                      <td className="p-2">
                        <span className={`inline-flex px-2 py-0.5 rounded text-xs ${tierBadge}`}>{String(r.tier)}</span>
                      </td>
                      <td className="p-2">{String(r.stage)}</td>
                      <td className="p-2">{_normRobust(r.robustness)}</td>
                      <td className="p-2 text-right font-mono text-xs">{_fmt2(pf, 2)}</td>
                      <td className="p-2 text-right font-mono text-xs">{_fmtPct(dd, 1)}</td>
                      <td className="p-2 text-right font-mono text-xs">{_fmtPct(wr, 1)}</td>
                      <td className="p-2 text-right font-mono text-xs">{Number.isFinite(trades) ? Math.trunc(trades) : '-'}</td>
                      <td className="p-2 text-right font-mono text-xs">{Number.isFinite(days) ? Math.trunc(days) : '-'}</td>
                      <td className="p-2 text-right font-mono text-xs">{_fmt2(sd, 2)}</td>
                      <td className="p-2 text-right font-mono text-xs">{_fmt2(p50, 2)}</td>
                      <td className="p-2 text-xs text-slate-700">{[...extrasBits, ...idxBits].join(' ') || '-'}</td>
                      <td className="p-2">
                        {(Array.isArray(r.tags) ? r.tags : []).slice(0, 4).map((t) => (
                          <Badge key={t} className="mr-1" variant="secondary">
                            {t}
                          </Badge>
                        ))}
                      </td>
                      <td className="p-2 text-xs text-slate-600 max-w-[360px] truncate" title={String(r.tier_reason ?? '')}>
                        {String(r.tier_reason ?? '-')}
                      </td>
                      <td className="p-2">
                        <div className="grid grid-cols-1 gap-2 min-w-[420px]">
                          <div className="flex flex-wrap items-center gap-2">
                            {String(reg?.lifecycle_state ?? '').trim() ? (
                              <Badge variant="secondary">lc:{String(reg?.lifecycle_state)}</Badge>
                            ) : null}
                            {String((reg?.rollout as Record<string, unknown> | undefined)?.status ?? '').trim() ? (
                              <Badge variant="secondary">roll:{String((reg?.rollout as Record<string, unknown> | undefined)?.status)}</Badge>
                            ) : null}
                            {String(reg?.bundle_id ?? '').trim() ? <Badge variant="secondary">bundle</Badge> : null}
                            {String(reg?.deprecated_reason ?? '').trim() ? <Badge variant="secondary">deprecated</Badge> : null}
                          </div>
                          {mirrorPath ? (
                            <div className="text-xs text-slate-500 font-mono truncate" title={mirrorPath}>
                              mirror: {mirrorPath}
                            </div>
                          ) : null}
                          {bucketText ? (
                            <div className="text-xs text-slate-500 truncate" title={bucketText}>
                              {bucketText}
                            </div>
                          ) : null}
                          {assetLinks.length ? (
                            <div className="text-xs text-slate-500 truncate" title={assetLinks.join('\n')}>
                              links: {assetLinks.slice(0, 2).join(' · ')}{assetLinks.length > 2 ? ` · +${assetLinks.length - 2}` : ''}
                            </div>
                          ) : null}
                          <div className="grid grid-cols-2 gap-2">
                            <select
                              className="border rounded h-9 px-2 bg-white text-sm"
                              value={draft.family}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, family: e.target.value } }))}
                            >
                              <option value="trend">trend</option>
                              <option value="mean_reversion">mean_reversion</option>
                              <option value="carry">carry</option>
                              <option value="breakout">breakout</option>
                            </select>
                            <select
                              className="border rounded h-9 px-2 bg-white text-sm"
                              value={draft.stage}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, stage: e.target.value } }))}
                            >
                              <option value="research">research</option>
                              <option value="model">model</option>
                              <option value="deployment">deployment</option>
                            </select>
                            <select
                              className="border rounded h-9 px-2 bg-white text-sm"
                              value={draft.robustness}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, robustness: e.target.value } }))}
                            >
                              <option value="unknown">unknown</option>
                              <option value="pass">pass</option>
                              <option value="warn">warn</option>
                              <option value="fail">fail</option>
                            </select>
                            <Input
                              value={draft.tagsText}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, tagsText: e.target.value } }))}
                              placeholder="tags: mtf, vol_adj"
                            />
                            <Input
                              value={draft.econDriver}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, econDriver: e.target.value } }))}
                              placeholder="econ_driver"
                            />
                            <Input
                              value={draft.evalPolicyRef}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, evalPolicyRef: e.target.value } }))}
                              placeholder="eval_policy_ref"
                            />
                            <Input
                              value={draft.owner}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, owner: e.target.value } }))}
                              placeholder="owner"
                            />
                          </div>
                        </div>
                        <div className="mt-2 flex items-center gap-2">
                          <Button onClick={() => void saveRow(sid, r)} disabled={savingNow}>
                            {savingNow ? 'Saving…' : 'Save'}
                          </Button>
                          <Button variant="secondary" onClick={() => void verifyRow(sid, r)} disabled={verifyingNow || !snapshotZip}>
                            {verifyingNow ? 'Verifying…' : 'Verify'}
                          </Button>
                          <Button variant="secondary" onClick={() => void runAndVerifyRow(sid, r)} disabled={runningNow}>
                            {runningNow ? 'Running…' : 'Run&Verify'}
                          </Button>
                          <Button variant="secondary" onClick={() => void toggleEvents(sid)} disabled={eventsLoading[k] || !snapshotZip}>
                            {eventsOpen[k] ? 'Hide Events' : 'Events'}
                          </Button>
                          <div className="text-xs text-slate-500">{saveSt === 'ok' ? 'Saved.' : saveSt === 'error' ? 'Save failed.' : ''}</div>
                          {saveSt === 'error' && saveErr ? <div className="text-xs text-rose-700">{saveErr}</div> : null}
                          <div className="text-xs text-slate-500">
                            {vState?.ok === true ? 'Verified.' : vState?.ok === false ? `Verify failed: ${vState.error || ''}` : ''}
                          </div>
                          <div className="text-xs text-slate-500">
                            {rState?.ok === true ? 'Run OK.' : rState?.ok === false ? `Run failed: ${rState.error || ''}` : ''}
                          </div>
                        </div>

                        <details className="mt-2 border rounded bg-slate-50 px-2 py-1">
                          <summary className="cursor-pointer text-xs text-slate-600 select-none">Governance</summary>
                          <div className="mt-2 grid grid-cols-2 gap-2">
                            <select
                              className="border rounded h-9 px-2 bg-white text-sm"
                              value={draft.lifecycleState}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, lifecycleState: e.target.value } }))}
                            >
                              <option value="">lifecycle_state</option>
                              <option value="research_draft">research_draft</option>
                              <option value="research_validated">research_validated</option>
                              <option value="model_candidate">model_candidate</option>
                              <option value="approved">approved</option>
                              <option value="deployed_canary">deployed_canary</option>
                              <option value="deployed_full">deployed_full</option>
                              <option value="deprecated">deprecated</option>
                              <option value="rolled_back">rolled_back</option>
                            </select>
                            <select
                              className="border rounded h-9 px-2 bg-white text-sm"
                              value={draft.rolloutStatus}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, rolloutStatus: e.target.value } }))}
                            >
                              <option value="">rollout_status</option>
                              <option value="planned">planned</option>
                              <option value="canary">canary</option>
                              <option value="full">full</option>
                              <option value="paused">paused</option>
                              <option value="completed">completed</option>
                              <option value="failed">failed</option>
                            </select>
                            <Input
                              value={draft.approvedBy}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, approvedBy: e.target.value } }))}
                              placeholder="approved_by"
                            />
                            <Input
                              value={draft.approvedAt}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, approvedAt: e.target.value } }))}
                              placeholder="approved_at (ISO)"
                            />
                            <Input
                              value={draft.rollbackToBundleId}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, rollbackToBundleId: e.target.value } }))}
                              placeholder="rollback to bundle_id"
                            />
                            <select
                              className="border rounded h-9 px-2 bg-white text-sm"
                              value={draft.tierOverride}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, tierOverride: e.target.value } }))}
                            >
                              <option value="">tier_override</option>
                              <option value="A">A</option>
                              <option value="B">B</option>
                              <option value="C">C</option>
                              <option value="unrated">unrated</option>
                            </select>
                            <Input
                              value={draft.deprecateReason}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, deprecateReason: e.target.value } }))}
                              placeholder="deprecate reason"
                            />
                            <Input
                              value={draft.traceId}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, traceId: e.target.value } }))}
                              placeholder="trace_id"
                            />
                            <Input
                              value={draft.actor}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, actor: e.target.value } }))}
                              placeholder="actor"
                            />
                            <Input
                              value={draft.note}
                              onChange={(e) => setDrafts((p) => ({ ...p, [k]: { ...draft, note: e.target.value } }))}
                              placeholder="note"
                            />
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-2">
                            <Button variant="secondary" onClick={() => void rolloutRow(sid)} disabled={govNow || !snapshotZip}>
                              Rollout
                            </Button>
                            <Button variant="secondary" onClick={() => void lifecycleRow(sid)} disabled={govNow || !snapshotZip}>
                              Lifecycle
                            </Button>
                            <Button variant="secondary" onClick={() => void rollbackRow(sid)} disabled={govNow || !snapshotZip}>
                              Rollback
                            </Button>
                            <Button variant="secondary" onClick={() => void tierChangeRow(sid)} disabled={govNow || !snapshotZip}>
                              Tier Change
                            </Button>
                            <Button variant="secondary" onClick={() => void deprecateRow(sid)} disabled={govNow || !snapshotZip}>
                              Deprecate
                            </Button>
                          </div>
                        </details>

                        {eventsOpen[k] ? (
                          <div className="mt-2 border rounded bg-slate-50 p-2 text-xs text-slate-700">
                            {eventsLoading[k] ? (
                              <div className="text-slate-500">Loading…</div>
                            ) : (
                              <div className="space-y-1">
                                {(eventsByKey[k] ?? []).slice(-20).map((ev, i) => (
                                  <div key={String(ev.id ?? ev.ts ?? i)} className="font-mono">
                                    {_fmtTs(_toNum(ev.ts, 0))} {String(ev.kind)} {String(ev.trace_id ?? '')} {String(ev.actor ?? '')} {String(ev.note ?? '')}
                                  </div>
                                ))}
                                {(eventsByKey[k] ?? []).length === 0 ? <div className="text-slate-500">No events.</div> : null}
                              </div>
                            )}
                          </div>
                        ) : null}
                      </td>
                      <td className="p-2">
                        <div className="flex items-center gap-2">
                          <Button variant="secondary" onClick={() => void buildRow(sid, r)} disabled={buildingNow}>
                            {buildingNow ? 'Building…' : 'Build'}
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => openFeederControlled(r)} disabled={feederCtlBusy}>
                            加入Feeder（受控）
                          </Button>
                          {build?.bundle ? (
                            <a className="text-sm text-emerald-700 underline" href={strategyBundleDownloadUrl(build.bundle)}>
                              Download
                            </a>
                          ) : null}
                        </div>
                        {build?.bundleId ? <div className="text-xs text-slate-500 mt-1">bundle_id: {String(build.bundleId).slice(0, 10)}…</div> : null}
                        {build?.tier ? <div className="text-xs text-slate-500 mt-1">tier: {build.tier}</div> : null}
                        {build?.tierReason ? <div className="text-xs text-slate-500 mt-1 truncate" title={build.tierReason}>reason: {build.tierReason}</div> : null}
                        {build?.error ? <div className="text-xs text-rose-700 mt-1">{build.error}</div> : null}
                      </td>
                    </tr>
                  );
                })}
                {rows.length === 0 ? (
                  <tr>
                    <td className="p-3 text-slate-500" colSpan={17}>
                      No rows.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Bundles</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {(((bundles as { bundles?: Array<{ name: string; mtime_ms?: number }> } | undefined)?.bundles ?? []) as Array<{ name: string; mtime_ms?: number }>).map((b) => (
              <a key={b.name} className="border rounded px-2 py-1 text-xs bg-slate-50 text-slate-900" href={strategyBundleDownloadUrl(String(b.name))}>
                {b.name}
              </a>
            ))}
            {(((bundles as { bundles?: Array<{ name: string }> } | undefined)?.bundles ?? []) as Array<{ name: string }>).length === 0 ? (
              <div className="text-xs text-slate-500">No bundles yet.</div>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {feederCtlOpen ? (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
          <div className="w-full max-w-2xl rounded border bg-white p-4 space-y-4">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-semibold">加入 Feeder（受控）</div>
              <Button variant="outline" size="sm" onClick={() => setFeederCtlOpen(false)} disabled={feederCtlBusy}>
                关闭
              </Button>
            </div>
            <div className="text-xs text-slate-600">
              source: {feederCtlSource ? `${feederCtlSource.strategy_id} @ ${feederCtlSource.source_zip || '-'}` : '-'}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <div className="text-xs text-slate-500 mb-1">runtime_strategy_key</div>
                <select
                  className="w-full border rounded h-10 px-3 bg-white"
                  value={feederCtlRuntimeKey}
                  onChange={(e) => setFeederCtlRuntimeKey(String(e.target.value || '').trim())}
                  disabled={feederCtlBusy}
                >
                  {feederSupported.map((sid) => (
                    <option key={sid} value={sid}>
                      {sid}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-1">二次输入密钥（不会保存）</div>
                <Input type="password" value={feederCtlToken} onChange={(e) => setFeederCtlToken(e.target.value)} placeholder="CONFIG_TOKEN / EXECUTE_TOKEN" />
              </div>
              <div className="md:col-span-2">
                <div className="text-xs text-slate-500 mb-1">二次确认短语</div>
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <Badge variant="outline">{feederCtlPhrase || '-'}</Badge>
                </div>
                <Input value={feederCtlConfirm} onChange={(e) => setFeederCtlConfirm(e.target.value)} placeholder={feederCtlPhrase || 'ADD <strategy> TO FEEDER'} />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => void feederControlledApply('enable')} disabled={feederCtlBusy}>
                启用（emit=true）
              </Button>
              <Button variant="secondary" onClick={() => void feederControlledApply('disable')} disabled={feederCtlBusy}>
                禁用（emit=false）
              </Button>
              <Button variant="outline" onClick={() => void feederControlledApply('remove')} disabled={feederCtlBusy}>
                移除
              </Button>
              {feederCtlBusy ? <div className="text-xs text-slate-500">Applying…</div> : null}
            </div>
            {feederCtlState ? (
              <div className={`rounded border p-3 text-xs ${feederCtlState.ok ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-rose-50 border-rose-200 text-rose-800'}`}>
                <div>{feederCtlState.ok ? 'ok' : 'error'}{feederCtlState.error ? `: ${feederCtlState.error}` : ''}</div>
                {feederCtlState.before !== undefined ? <div className="mt-1 break-words">before: {feederCtlState.before || '-'}</div> : null}
                {feederCtlState.after !== undefined ? <div className="mt-1 break-words">after: {feederCtlState.after || '-'}</div> : null}
              </div>
            ) : null}
            <div className="text-xs text-slate-500">
              提示：该动作会直接写入 /automation/strategies/config；为了防串味，必须手动输入密钥并匹配确认短语。
              coins 字段仅在手工 tick/调试路径可能生效；周期 Feeder 默认按 Universe core 扫描。
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};
