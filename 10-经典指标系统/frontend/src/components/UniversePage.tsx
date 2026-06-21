import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchCarryUniverse,
  fetchUniverseBtcCorrAbEval,
  fetchUniverseBtcCorrBucketEval,
  fetchUniverseBtcCorrResearch,
  fetchUniverseBtcCorrThresholdReview,
  fetchUniverseBtcCorrWalkforward,
  fetchUniverseStatus,
  triggerUniverseBuild,
  fetchUniversePairs,
  setStrategyFeederUseCore,
} from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { RefreshCw, Shield, TrendingUp, AlertTriangle, ListFilter } from 'lucide-react';

const toNum = (v: unknown): number | null => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

export const UniversePage: React.FC = () => {
  const queryClient = useQueryClient();
  const [btcCorrPool, setBtcCorrPool] = React.useState<string>('core');
  const [btcCorrMaxN, setBtcCorrMaxN] = React.useState<number>(200);
  const [btcCorrFilterMode, setBtcCorrFilterMode] = React.useState<'ge_thr' | 'all'>('ge_thr');
  const [btcCorrTimeframe, setBtcCorrTimeframe] = React.useState<'30m' | '1h'>('1h');
  const [btcCorrWindowBars, setBtcCorrWindowBars] = React.useState<number>(72);
  const [btcCorrMethod, setBtcCorrMethod] = React.useState<'pearson' | 'spearman'>('pearson');
  const [btcCorrEndTsRaw, setBtcCorrEndTsRaw] = React.useState<string>('');
  const [btcCorrSearch, setBtcCorrSearch] = React.useState<string>('');
  const [btcCorrReviewMonths, setBtcCorrReviewMonths] = React.useState<number>(6);
  const [btcCorrTargetAllowFrac, setBtcCorrTargetAllowFrac] = React.useState<number>(0.3);
  const [btcCorrEvalZip, setBtcCorrEvalZip] = React.useState<string>('');
  const [btcCorrEvalStrategy, setBtcCorrEvalStrategy] = React.useState<string>('');
  const [btcCorrEvalStartTsRaw, setBtcCorrEvalStartTsRaw] = React.useState<string>('');
  const [btcCorrEvalEndTsRaw, setBtcCorrEvalEndTsRaw] = React.useState<string>('');
  const [btcCorrEvalFeeRaw, setBtcCorrEvalFeeRaw] = React.useState<string>('');
  const [btcCorrEvalSlippageRaw, setBtcCorrEvalSlippageRaw] = React.useState<string>('');
  const [btcCorrAbThresholdsRaw, setBtcCorrAbThresholdsRaw] = React.useState<string>('0.3,0.5,0.7,0.9');
  const [btcCorrWfPeriod, setBtcCorrWfPeriod] = React.useState<'month' | 'quarter'>('month');
  const [btcCorrWfMinTrades, setBtcCorrWfMinTrades] = React.useState<number>(5);
  const [btcCorrWfTakeRateMin, setBtcCorrWfTakeRateMin] = React.useState<number>(0.1);
  const [btcCorrWfTakeRateMax, setBtcCorrWfTakeRateMax] = React.useState<number>(0.9);
  const [btcCorrSort, setBtcCorrSort] = React.useState<
    'corr_desc' | 'corr_asc' | 'beta_desc' | 'beta_asc' | 'resid_vol_desc' | 'resid_vol_asc' | 'coin_asc' | 'coin_desc'
  >('corr_desc');
  const [btcCorrResearchGroup, setBtcCorrResearchGroup] = React.useState<'basic' | 'advanced'>('basic');
  const [btcCorrResearchTab, setBtcCorrResearchTab] = React.useState<string>('snapshot');
  React.useEffect(() => {
    const allowed =
      btcCorrResearchGroup === 'basic'
        ? new Set(['snapshot', 'review'])
        : new Set(['ab', 'bucket', 'walkforward']);
    if (!allowed.has(btcCorrResearchTab)) {
      setBtcCorrResearchTab(btcCorrResearchGroup === 'basic' ? 'snapshot' : 'ab');
    }
  }, [btcCorrResearchGroup, btcCorrResearchTab]);
  const [universeTabGroup, setUniverseTabGroup] = React.useState<'basic' | 'advanced' | 'research'>('basic');
  const [universeTab, setUniverseTab] = React.useState<string>('issues');
  React.useEffect(() => {
    const allowed =
      universeTabGroup === 'basic'
        ? new Set(['issues', 'shadow', 'watchlist', 'candidates', 'snapshot', 'whitelist'])
        : universeTabGroup === 'advanced'
          ? new Set(['pools', 'clusters', 'hyperparams', 'monitoring'])
          : new Set(['btcCorr']);
    if (!allowed.has(universeTab)) {
      setUniverseTab(universeTabGroup === 'basic' ? 'issues' : universeTabGroup === 'advanced' ? 'pools' : 'btcCorr');
    }
  }, [universeTabGroup, universeTab]);
  const {
    data: universe,
    isLoading: universeLoading,
    error: universeError,
    isFetching: universeFetching,
  } = useQuery({
    queryKey: ['universe', 'status'],
    queryFn: fetchUniverseStatus,
    refetchInterval: 60000,
    retry: false,
  });
  const { data: pairs, isLoading: pairsLoading, error: pairsError } = useQuery({
    queryKey: ['universe', 'pairs'],
    queryFn: fetchUniversePairs,
    refetchInterval: 60000,
    retry: false,
  });

  const {
    data: btcCorr,
    isLoading: btcCorrLoading,
    error: btcCorrError,
    isFetching: btcCorrFetching,
    refetch: btcCorrRefetch,
  } = useQuery({
    queryKey: ['universe', 'btcCorrResearch', btcCorrPool, btcCorrMaxN, btcCorrTimeframe, btcCorrWindowBars, btcCorrMethod, btcCorrEndTsRaw],
    queryFn: () => {
      const raw = String(btcCorrEndTsRaw ?? '').trim();
      let end_ts: number | undefined = undefined;
      if (raw) {
        const n = Number(raw);
        if (Number.isFinite(n) && n > 0) {
          end_ts = n < 1e12 ? Math.floor(n * 1000) : Math.floor(n);
        } else {
          const ms = Date.parse(raw);
          if (Number.isFinite(ms) && ms > 0) end_ts = Math.floor(ms);
        }
      }
      return fetchUniverseBtcCorrResearch({
        pool: btcCorrPool,
        max_n: btcCorrMaxN,
        refresh: 0,
        end_ts,
        timeframe: btcCorrTimeframe,
        window_bars: btcCorrWindowBars,
        method: btcCorrMethod,
      });
    },
    refetchInterval: 60000,
    retry: false,
  });

  const { data: carryUniverse } = useQuery({
    queryKey: ['carry', 'universe'],
    queryFn: () => {
      const cached = queryClient.getQueryData(['carry', 'universe']) as { state?: { coins?: unknown } } | undefined;
      const coins = cached?.state?.coins;
      const hasCoins = Array.isArray(coins) && coins.length > 0;
      return fetchCarryUniverse({ refresh: hasCoins ? 0 : 1 });
    },
    refetchInterval: 300000,
    retry: false,
  });

  const {
    data: btcCorrReview,
    isFetching: btcCorrReviewFetching,
    error: btcCorrReviewError,
    refetch: btcCorrReviewRefetch,
  } = useQuery({
    queryKey: ['universe', 'btcCorrThresholdReview', btcCorrPool, btcCorrMaxN, btcCorrTimeframe, btcCorrWindowBars, btcCorrMethod, btcCorrEndTsRaw, btcCorrReviewMonths, btcCorrTargetAllowFrac],
    queryFn: () => {
      const raw = String(btcCorrEndTsRaw ?? '').trim();
      let end_ts: number | undefined = undefined;
      if (raw) {
        const n = Number(raw);
        if (Number.isFinite(n) && n > 0) {
          end_ts = n < 1e12 ? Math.floor(n * 1000) : Math.floor(n);
        } else {
          const ms = Date.parse(raw);
          if (Number.isFinite(ms) && ms > 0) end_ts = Math.floor(ms);
        }
      }
      return fetchUniverseBtcCorrThresholdReview({
        pool: btcCorrPool,
        max_n: btcCorrMaxN,
        months: btcCorrReviewMonths,
        target_allow_frac: btcCorrTargetAllowFrac,
        refresh: 0,
        end_ts,
        timeframe: btcCorrTimeframe,
        window_bars: btcCorrWindowBars,
        method: btcCorrMethod,
      });
    },
    enabled: false,
    retry: false,
  });

  const {
    data: btcCorrAb,
    isFetching: btcCorrAbFetching,
    error: btcCorrAbError,
    refetch: btcCorrAbRefetch,
  } = useQuery({
    queryKey: [
      'universe',
      'btcCorrAbEval',
      btcCorrEvalZip,
      btcCorrEvalStrategy,
      btcCorrEvalStartTsRaw,
      btcCorrEvalEndTsRaw,
      btcCorrEvalFeeRaw,
      btcCorrEvalSlippageRaw,
      btcCorrAbThresholdsRaw,
      btcCorrTimeframe,
      btcCorrWindowBars,
      btcCorrMethod,
    ],
    queryFn: () => {
      const start_ts = parseFlexibleTsMs(btcCorrEvalStartTsRaw);
      const end_ts = parseFlexibleTsMs(btcCorrEvalEndTsRaw);
      const fee = parseOptionalNumber(btcCorrEvalFeeRaw);
      const slippage = parseOptionalNumber(btcCorrEvalSlippageRaw);
      return fetchUniverseBtcCorrAbEval({
        zip: String(btcCorrEvalZip ?? '').trim() || undefined,
        strategy: String(btcCorrEvalStrategy ?? '').trim() || undefined,
        thresholds: String(btcCorrAbThresholdsRaw ?? '').trim() || undefined,
        start_ts,
        end_ts,
        fee,
        slippage,
        timeframe: btcCorrTimeframe,
        window_bars: btcCorrWindowBars,
        method: btcCorrMethod,
      });
    },
    enabled: false,
    retry: false,
  });

  const {
    data: btcCorrBucketEval,
    isFetching: btcCorrBucketFetching,
    error: btcCorrBucketError,
    refetch: btcCorrBucketRefetch,
  } = useQuery({
    queryKey: [
      'universe',
      'btcCorrBucketEval',
      btcCorrEvalZip,
      btcCorrEvalStrategy,
      btcCorrEvalStartTsRaw,
      btcCorrEvalEndTsRaw,
      btcCorrEvalFeeRaw,
      btcCorrEvalSlippageRaw,
      btcCorrTimeframe,
      btcCorrWindowBars,
      btcCorrMethod,
    ],
    queryFn: () => {
      const start_ts = parseFlexibleTsMs(btcCorrEvalStartTsRaw);
      const end_ts = parseFlexibleTsMs(btcCorrEvalEndTsRaw);
      const fee = parseOptionalNumber(btcCorrEvalFeeRaw);
      const slippage = parseOptionalNumber(btcCorrEvalSlippageRaw);
      return fetchUniverseBtcCorrBucketEval({
        zip: String(btcCorrEvalZip ?? '').trim() || undefined,
        strategy: String(btcCorrEvalStrategy ?? '').trim() || undefined,
        start_ts,
        end_ts,
        fee,
        slippage,
        timeframe: btcCorrTimeframe,
        window_bars: btcCorrWindowBars,
        method: btcCorrMethod,
      });
    },
    enabled: false,
    retry: false,
  });

  const {
    data: btcCorrWalkforward,
    isFetching: btcCorrWalkforwardFetching,
    error: btcCorrWalkforwardError,
    refetch: btcCorrWalkforwardRefetch,
  } = useQuery({
    queryKey: [
      'universe',
      'btcCorrWalkforward',
      btcCorrEvalZip,
      btcCorrEvalStrategy,
      btcCorrEvalStartTsRaw,
      btcCorrEvalEndTsRaw,
      btcCorrEvalFeeRaw,
      btcCorrEvalSlippageRaw,
      btcCorrAbThresholdsRaw,
      btcCorrWfPeriod,
      btcCorrWfMinTrades,
      btcCorrWfTakeRateMin,
      btcCorrWfTakeRateMax,
      btcCorrTimeframe,
      btcCorrWindowBars,
      btcCorrMethod,
    ],
    queryFn: () => {
      const start_ts = parseFlexibleTsMs(btcCorrEvalStartTsRaw);
      const end_ts = parseFlexibleTsMs(btcCorrEvalEndTsRaw);
      const fee = parseOptionalNumber(btcCorrEvalFeeRaw);
      const slippage = parseOptionalNumber(btcCorrEvalSlippageRaw);
      return fetchUniverseBtcCorrWalkforward({
        zip: String(btcCorrEvalZip ?? '').trim() || undefined,
        strategy: String(btcCorrEvalStrategy ?? '').trim() || undefined,
        thresholds: String(btcCorrAbThresholdsRaw ?? '').trim() || undefined,
        start_ts,
        end_ts,
        fee,
        slippage,
        period: btcCorrWfPeriod,
        min_trades: btcCorrWfMinTrades,
        take_rate_min: btcCorrWfTakeRateMin,
        take_rate_max: btcCorrWfTakeRateMax,
        timeframe: btcCorrTimeframe,
        window_bars: btcCorrWindowBars,
        method: btcCorrMethod,
      });
    },
    enabled: false,
    retry: false,
  });

  const buildMutation = useMutation({
    mutationFn: triggerUniverseBuild,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['universe'] });
    },
  });

  const core = universe?.core ?? [];
  const shadow = universe?.shadow ?? [];
  const watchlist = universe?.watchlist ?? [];
  const carryCoins = (carryUniverse?.state?.coins ?? []) as string[];
  const carryN = Array.isArray(carryCoins) ? carryCoins.length : 0;
  const meta = universe?.metadata ?? {};
  const issues = meta.stage_a_issues ?? {};
  const topScoresRaw = meta.top_scores;
  const topScores = Array.isArray(topScoresRaw) ? topScoresRaw : [];
  const weights = meta.scoring_weights ?? {};
  const candidates = meta.candidates ?? [];
  const clusters = meta.clusters ?? {};
  const pools = meta.pools ?? {};
  const selectionHints = meta.selection_hints ?? {};
  const consistency = meta.cluster_consistency;
  const marketSnapshot = (meta as Record<string, unknown>)?.market_snapshot as Record<string, unknown> | undefined;
  const clusteringHyperparams = (meta as Record<string, unknown>)?.clustering_hyperparams as Record<string, unknown> | undefined;
  const tradeWhitelistAuto = (meta as Record<string, unknown>)?.trade_whitelist_auto as Record<string, unknown> | undefined;
  const monitoringHints = (meta as Record<string, unknown>)?.monitoring_hints as Record<string, unknown> | undefined;
  const btcCorrReviewAuto = (meta as Record<string, unknown>)?.btc_corr_threshold_review_auto as Record<string, unknown> | undefined;

  const errText = (e: unknown): string => {
    try {
      if (!e) return '';
      if (e instanceof Error) return String(e.message || '');
      if (typeof e === 'string') return e;
      const maybe = e as { message?: unknown };
      if (typeof maybe?.message === 'string') return maybe.message;
      return JSON.stringify(e);
    } catch {
      return '';
    }
  };
  const fmtFixed = (v: unknown, digits: number): string => {
    const n = toNum(v);
    return n == null ? '-' : n.toFixed(digits);
  };
  const fmtUsd0 = (v: unknown): string => {
    const n = toNum(v);
    return n == null ? '-' : `$${Math.round(n).toLocaleString()}`;
  };
  const fmtPct = (v: unknown, digits: number = 2): string => {
    const n = toNum(v);
    return n == null ? '-' : `${(n * 100).toFixed(digits)}%`;
  };

  const downloadCsv = (filename: string, csv: string) => {
    try {
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      void 0;
    }
  };

  const parseFlexibleTsMs = (rawIn: unknown): number | undefined => {
    const raw = String(rawIn ?? '').trim();
    if (!raw) return undefined;
    const n = Number(raw);
    if (Number.isFinite(n) && n > 0) return n < 1e12 ? Math.floor(n * 1000) : Math.floor(n);
    const ms = Date.parse(raw);
    if (Number.isFinite(ms) && ms > 0) return Math.floor(ms);
    return undefined;
  };

  const parseOptionalNumber = (rawIn: unknown): number | undefined => {
    const raw = String(rawIn ?? '').trim();
    if (!raw) return undefined;
    const n = Number(raw);
    if (!Number.isFinite(n)) return undefined;
    return n;
  };

  const copyText = async (text: string): Promise<boolean> => {
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch {
      void 0;
    }
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  };

  const asStringList = (v: unknown): string[] => {
    try {
      if (Array.isArray(v)) {
        return v
          .map((x) => String(x ?? '').trim())
          .filter((x) => x.length > 0);
      }
      if (typeof v === 'string') {
        return v
          .split(/[,\s]+/g)
          .map((x) => x.trim())
          .filter((x) => x.length > 0);
      }
      if (v && typeof v === 'object') {
        const o = v as Record<string, unknown>;
        const arr = o.coins ?? o.members ?? o.items;
        if (Array.isArray(arr)) return asStringList(arr);
      }
      return [];
    } catch {
      return [];
    }
  };

  const pickFirst = (obj: unknown, keys: string[]): unknown => {
    if (!obj || typeof obj !== 'object') return undefined;
    const o = obj as Record<string, unknown>;
    for (const k of keys) {
      if (k in o) return o[k];
    }
    return undefined;
  };

  const failedCount = Object.keys(issues).length;
  const lastUpdate = universe?.last_update ? new Date(universe.last_update * (universe.last_update < 1e11 ? 1000 : 1)).toLocaleString() : 'Never';

  const coreCountText = universeLoading ? '…' : universeError ? '-' : String(core.length);
  const shadowCountText = universeLoading ? '…' : universeError ? '-' : String(shadow.length);
  const watchlistCountText = universeLoading ? '…' : universeError ? '-' : String(watchlist.length);
  const carryCountText = carryUniverse ? String(carryN) : '…';

  const badgeForConsistency = (status?: string) => {
    const s = String(status || '').toLowerCase();
    if (s === 'breakdown') return <Badge className="bg-red-600 hover:bg-red-600">breakdown</Badge>;
    if (s === 'warn') return <Badge className="bg-amber-500 hover:bg-amber-500">warn</Badge>;
    if (s === 'ok') return <Badge className="bg-green-600 hover:bg-green-600">ok</Badge>;
    return <Badge variant="outline">{status || 'unknown'}</Badge>;
  };

  const renderCoinBadges = (coins: string[] | undefined, variant: React.ComponentProps<typeof Badge>['variant'] = 'secondary') => {
    const arr = asStringList(coins);
    if (arr.length === 0) return <span className="text-sm text-gray-400">Empty</span>;
    return (
      <div className="flex flex-wrap gap-2">
        {arr.map((c) => (
          <Badge key={c} variant={variant}>
            {c}
          </Badge>
        ))}
      </div>
    );
  };

  const poolsLiq = (pools as Record<string, unknown>)?.liq;
  const poolsBeta = (pools as Record<string, unknown>)?.beta;
  const poolsQuality = (pools as Record<string, unknown>)?.quality;
  const poolsCluster = (pools as Record<string, unknown>)?.cluster;

  const btcCorrRows = (() => {
    let rows = (btcCorr?.rows ?? []).slice();
    if (btcCorrFilterMode !== 'all') {
      const thr = toNum(btcCorr?.enter_thr) ?? 0;
      rows = rows.filter((r) => typeof r.corr === 'number' && Number.isFinite(r.corr) && r.corr >= thr);
    }
    const q = String(btcCorrSearch || '').trim().toUpperCase();
    if (q) {
      rows = rows.filter((r) => String(r.coin || '').toUpperCase().includes(q) || String(r.pair || '').toUpperCase().includes(q));
    }

    const num = (v: unknown): number | null => {
      if (typeof v !== 'number') return null;
      return Number.isFinite(v) ? v : null;
    };
    const cmpNum = (a: unknown, b: unknown, dir: 1 | -1) => {
      const na = num(a);
      const nb = num(b);
      if (na == null && nb == null) return 0;
      if (na == null) return 1;
      if (nb == null) return -1;
      if (na === nb) return 0;
      return na > nb ? dir : -dir;
    };
    rows.sort((a, b) => {
      if (btcCorrSort === 'corr_desc') return cmpNum(a.corr, b.corr, -1);
      if (btcCorrSort === 'corr_asc') return cmpNum(a.corr, b.corr, 1);
      if (btcCorrSort === 'beta_desc') return cmpNum(a.beta, b.beta, -1);
      if (btcCorrSort === 'beta_asc') return cmpNum(a.beta, b.beta, 1);
      if (btcCorrSort === 'resid_vol_desc') return cmpNum(a.resid_vol, b.resid_vol, -1);
      if (btcCorrSort === 'resid_vol_asc') return cmpNum(a.resid_vol, b.resid_vol, 1);
      if (btcCorrSort === 'coin_desc') return String(b.coin || '').localeCompare(String(a.coin || ''));
      return String(a.coin || '').localeCompare(String(b.coin || ''));
    });
    return rows;
  })();

  const btcCorrBuckets = (() => {
    const rows = (btcCorr?.rows ?? []).filter((r) => typeof r.corr === 'number' && Number.isFinite(r.corr) && r.corr >= 0);
    const defs = [
      { label: '[0.0–0.3)', lo: 0.0, hi: 0.3, last: false },
      { label: '[0.3–0.5)', lo: 0.3, hi: 0.5, last: false },
      { label: '[0.5–0.7)', lo: 0.5, hi: 0.7, last: false },
      { label: '[0.7–0.9)', lo: 0.7, hi: 0.9, last: false },
      { label: '[0.9–1.0]', lo: 0.9, hi: 1.0, last: true },
    ];
    return defs.map((d) => {
      const members = rows.filter((r) => {
        if (typeof r.corr !== 'number' || !Number.isFinite(r.corr)) return false;
        if (d.last) return r.corr >= d.lo && r.corr <= d.hi;
        return r.corr >= d.lo && r.corr < d.hi;
      });
      const n = members.length;
      const nBlocked = members.filter((r) => Boolean(r.blocked_state)).length;
      const avgCorr = n ? members.reduce((acc, r) => acc + (typeof r.corr === 'number' ? r.corr : 0), 0) / n : null;
      return { label: d.label, n, nBlocked, avgCorr };
    });
  })();

  const liqHigh = asStringList(pickFirst(poolsLiq, ['HIGH', 'high', 'High']));
  const liqMed = asStringList(pickFirst(poolsLiq, ['MED', 'med', 'Med', 'MID', 'mid', 'Mid']));
  const liqLow = asStringList(pickFirst(poolsLiq, ['LOW', 'low', 'Low']));
  const betaHigh = asStringList(pickFirst(poolsBeta, ['HIGH', 'high', 'High']));
  const betaMid = asStringList(pickFirst(poolsBeta, ['MID', 'mid', 'Mid', 'MED', 'med', 'Med']));
  const betaLow = asStringList(pickFirst(poolsBeta, ['LOW', 'low', 'Low']));
  const qualityGood = asStringList(pickFirst(poolsQuality, ['GOOD', 'good', 'Good']));
  const qualityOk = asStringList(pickFirst(poolsQuality, ['OK', 'ok', 'Ok']));
  const qualityBad = asStringList(pickFirst(poolsQuality, ['BAD', 'bad', 'Bad']));
  const clusterEntries = Object.entries((poolsCluster && typeof poolsCluster === 'object' ? (poolsCluster as Record<string, unknown>) : {}) as Record<string, unknown>);

  const renderKv = (obj: Record<string, unknown> | undefined | null) => {
    const o = obj && typeof obj === 'object' ? obj : null;
    const rows = o ? Object.entries(o) : [];
    if (!rows.length) return <span className="text-sm text-gray-400">Empty</span>;
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
            <tr>
              <th className="px-3 py-2">Key</th>
              <th className="px-3 py-2">Value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows
              .slice()
              .sort((a, b) => a[0].localeCompare(b[0]))
              .map(([k, v]) => (
                <tr key={k} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{k}</td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-700 break-words">
                    {v == null
                      ? '-'
                      : typeof v === 'string'
                        ? v
                        : typeof v === 'number'
                          ? String(v)
                          : Array.isArray(v)
                            ? JSON.stringify(v)
                            : typeof v === 'object'
                              ? JSON.stringify(v)
                              : String(v)}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    );
  };

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Universe Manager</h1>
          <p className="text-muted-foreground mt-1">
            Strategy/Quant Pool — Core: {coreCountText} | Shadow: {shadowCountText} | Watchlist: {watchlistCountText} | CarryTrade Pool: {carryCountText} | Failed: {failedCount}
          </p>
          <div className="mt-1 text-xs text-slate-500">
            {universeLoading ? 'Loading…' : universeError ? `Failed to load universe${errText(universeError) ? `: ${errText(universeError)}` : ''}` : universeFetching ? 'Updating…' : null}
            {pairsLoading ? ' · Loading pairs…' : pairsError ? ` · Failed to load pairs${errText(pairsError) ? `: ${errText(pairsError)}` : ''}` : null}
          </div>
        </div>
        <div className="flex gap-3 items-center">
          <span className="text-sm text-gray-500">Last Update: {lastUpdate}</span>
          <Button 
            onClick={() => buildMutation.mutate(undefined)} 
            disabled={buildMutation.isPending}
            className="gap-2"
          >
            <RefreshCw className={`h-4 w-4 ${buildMutation.isPending ? 'animate-spin' : ''}`} />
            {buildMutation.isPending ? 'Building...' : 'Rebuild Universe'}
          </Button>
          <Button onClick={() => setStrategyFeederUseCore(true)} className="gap-2">
            Use Core Pool in Feeder
          </Button>
          <Button variant="outline" onClick={() => setStrategyFeederUseCore(false)}>
            Stop Using Core Pool
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-blue-500" />
              Top Candidates (Scoring Preview) ({topScores.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {topScores.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {topScores.map((s, idx) => {
                  const row = s as Record<string, unknown>;
                  const coin = String(row.coin ?? '').trim();
                  return (
                    <Badge key={coin || idx} variant="secondary">
                      {coin || '-'}
                    </Badge>
                  );
                })}
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                  <tr>
                    <th className="px-3 py-2">Coin</th>
                    <th className="px-3 py-2">Score</th>
                    <th className="px-3 py-2">Turnover (7d)</th>
                    <th className="px-3 py-2">ATR%</th>
                    <th className="px-3 py-2">Vol Ratio</th>
                    <th className="px-3 py-2">BTC Corr</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {topScores.length === 0 && (
                    <tr><td colSpan={6} className="px-3 py-4 text-center text-gray-500">No candidates scored yet</td></tr>
                  )}
                  {topScores.map((s, idx) => {
                    const row = s as Record<string, unknown>;
                    const coin = String(row.coin ?? '').trim();
                    return (
                      <tr key={coin || idx} className="hover:bg-slate-50">
                        <td className="px-3 py-2 font-medium">{coin || '-'}</td>
                        <td className="px-3 py-2 font-bold text-blue-600">{fmtFixed(row.score, 4)}</td>
                        <td className="px-3 py-2">{fmtUsd0(row.turnover)}</td>
                        <td className="px-3 py-2">{fmtPct(row.atr_pct, 2)}</td>
                        <td className="px-3 py-2">{toNum(row.vol_ratio) == null ? '-' : `${fmtFixed(row.vol_ratio, 2)}x`}</td>
                        <td className="px-3 py-2">{fmtFixed(row.btc_corr, 2)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="mt-4 text-xs text-gray-500 flex gap-4">
              <span>Weights:</span>
              {Object.entries(weights).map(([k, v]) => (
                <span key={k} className="bg-slate-100 px-2 py-1 rounded">{k}: {v}</span>
              ))}
              <span className="bg-slate-100 px-2 py-1 rounded">Algorithm: {meta.ranking_score}</span>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5 text-green-600" />
                Strategy/Quant Core ({core.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2 max-h-[200px] overflow-y-auto content-start">
                {core.length === 0 && <span className="text-sm text-gray-400">Empty Pool</span>}
                {core.map((c) => (
                  <Badge key={c} variant="default" className="bg-green-600 hover:bg-green-700">
                    {c}
                  </Badge>
                ))}
              </div>
              <div className="mt-3 text-xs text-slate-600">
                {Array.isArray(pairs?.pairs) && pairs?.pairs.length ? `Pairs: ${pairs.pairs.slice(0, 8).join(', ')} ...` : 'Pairs: -'}
              </div>
              {meta.churn_protection && (
                <div className="mt-4 text-xs bg-green-50 text-green-700 p-2 rounded flex items-center gap-2">
                  <Shield className="h-3 w-3" />
                  Churn Protection: {meta.churn_protection}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5 text-blue-600" />
                CarryTrade Universe ({carryN})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2 max-h-[200px] overflow-y-auto content-start">
                {carryN === 0 && <span className="text-sm text-gray-400">Empty Pool</span>}
                {carryCoins.slice(0, 120).map((c) => (
                  <Badge key={c} variant="secondary">
                    {c}
                  </Badge>
                ))}
                {carryN > 120 && <span className="text-xs text-slate-500">+{carryN - 120} more</span>}
              </div>
              <div className="mt-3 text-xs text-slate-600">
                venue: {String(carryUniverse?.venue ?? '-')}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-2">
        <Button
          variant={universeTabGroup === 'basic' ? 'secondary' : 'outline'}
          onClick={() => {
            setUniverseTabGroup('basic');
            setUniverseTab('issues');
          }}
          className="gap-2"
        >
          <ListFilter className="h-4 w-4" />
          基础功能
        </Button>
        <Button
          variant={universeTabGroup === 'advanced' ? 'secondary' : 'outline'}
          onClick={() => {
            setUniverseTabGroup('advanced');
            setUniverseTab('pools');
          }}
          className="gap-2"
        >
          <Shield className="h-4 w-4" />
          高级功能
        </Button>
        <Button
          variant={universeTabGroup === 'research' ? 'secondary' : 'outline'}
          onClick={() => {
            setUniverseTabGroup('research');
            setUniverseTab('btcCorr');
          }}
          className="gap-2"
        >
          <TrendingUp className="h-4 w-4" />
          研究/复核
        </Button>
      </div>

      <Tabs value={universeTab} onValueChange={setUniverseTab} className="w-full">
        <TabsList className="flex flex-wrap h-auto justify-start">
          {universeTabGroup === 'basic' ? (
            <>
              <TabsTrigger value="issues" className="gap-2">
                <AlertTriangle className="h-4 w-4" />
                Filtered Issues ({failedCount})
              </TabsTrigger>
              <TabsTrigger value="shadow" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Shadow Pool ({shadow.length})
              </TabsTrigger>
              <TabsTrigger value="watchlist" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Watchlist ({watchlist.length})
              </TabsTrigger>
              <TabsTrigger value="candidates" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Candidates ({candidates.length})
              </TabsTrigger>
              <TabsTrigger value="snapshot" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Snapshot
              </TabsTrigger>
              <TabsTrigger value="whitelist" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Whitelist
              </TabsTrigger>
            </>
          ) : universeTabGroup === 'advanced' ? (
            <>
              <TabsTrigger value="pools" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Pools
              </TabsTrigger>
              <TabsTrigger value="clusters" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Clusters ({Object.keys(clusters).length})
              </TabsTrigger>
              <TabsTrigger value="hyperparams" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Hyperparams
              </TabsTrigger>
              <TabsTrigger value="monitoring" className="gap-2">
                <ListFilter className="h-4 w-4" />
                Monitoring
              </TabsTrigger>
            </>
          ) : (
            <TabsTrigger value="btcCorr" className="gap-2">
              <TrendingUp className="h-4 w-4" />
              BTC Corr Research
            </TabsTrigger>
          )}
        </TabsList>
        
        <TabsContent value="issues">
          <Card>
            <CardContent className="pt-6">
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
                {Object.entries(issues).map(([coin, reasons]) => (
                  <div key={coin} className="text-xs bg-red-50 p-2 rounded border border-red-100">
                    <div className="font-bold text-red-700">{coin}</div>
                    <div
                      className="text-red-500 truncate"
                      title={asStringList(reasons).join(', ')}
                    >
                      {asStringList(reasons)[0] ?? '-'}
                    </div>
                  </div>
                ))}
                {failedCount === 0 && <div className="col-span-full text-center text-gray-500 py-4">No filtered assets</div>}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="shadow">
          <Card>
            <CardContent className="pt-6">
               <div className="flex flex-wrap gap-2">
                {shadow.map(c => (
                  <Badge key={c} variant="secondary">
                    {c}
                  </Badge>
                ))}
                {shadow.length === 0 && <span className="text-gray-400">No shadow assets</span>}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="watchlist">
           <Card>
            <CardContent className="pt-6">
               <div className="flex flex-wrap gap-2">
                {watchlist.map(c => (
                  <Badge key={c} variant="outline" className="text-gray-500 border-gray-300">
                    {c}
                  </Badge>
                ))}
                {watchlist.length === 0 && <span className="text-gray-400">No watchlist assets</span>}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="btcCorr">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <TrendingUp className="h-5 w-5 text-slate-700" />
                BTC Corr Research
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant={btcCorrResearchGroup === 'basic' ? 'secondary' : 'outline'}
                  onClick={() => {
                    setBtcCorrResearchGroup('basic');
                    setBtcCorrResearchTab('snapshot');
                  }}
                  className="gap-2"
                >
                  <ListFilter className="h-4 w-4" />
                  基础
                </Button>
                <Button
                  variant={btcCorrResearchGroup === 'advanced' ? 'secondary' : 'outline'}
                  onClick={() => {
                    setBtcCorrResearchGroup('advanced');
                    setBtcCorrResearchTab('ab');
                  }}
                  className="gap-2"
                >
                  <Shield className="h-4 w-4" />
                  高级
                </Button>
              </div>

              <Tabs value={btcCorrResearchTab} onValueChange={setBtcCorrResearchTab} className="w-full">
                <TabsList className="flex flex-wrap h-auto justify-start">
                  {btcCorrResearchGroup === 'basic' ? (
                    <>
                      <TabsTrigger value="snapshot" className="gap-2">
                        <ListFilter className="h-4 w-4" />
                        Snapshot
                      </TabsTrigger>
                      <TabsTrigger value="review" className="gap-2">
                        <Shield className="h-4 w-4" />
                        Threshold Review
                      </TabsTrigger>
                    </>
                  ) : (
                    <>
                      <TabsTrigger value="ab" className="gap-2">
                        <Shield className="h-4 w-4" />
                        A/B
                      </TabsTrigger>
                      <TabsTrigger value="bucket" className="gap-2">
                        <ListFilter className="h-4 w-4" />
                        Bucket
                      </TabsTrigger>
                      <TabsTrigger value="walkforward" className="gap-2">
                        <TrendingUp className="h-4 w-4" />
                        Walk-forward
                      </TabsTrigger>
                    </>
                  )}
                </TabsList>

                <TabsContent value="snapshot" className="space-y-4">
                  <div className="flex flex-wrap items-end gap-3">
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Pool</div>
                      <select
                        value={btcCorrPool}
                        onChange={(e) => setBtcCorrPool(String(e.target.value || 'core'))}
                        className="flex h-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                      >
                        <option value="core">core</option>
                        <option value="shadow">shadow</option>
                        <option value="watchlist">watchlist</option>
                        <option value="all">all</option>
                      </select>
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Timeframe</div>
                      <select
                        value={btcCorrTimeframe}
                        onChange={(e) => setBtcCorrTimeframe((String(e.target.value) as '30m' | '1h') || '1h')}
                        className="flex h-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                      >
                        <option value="1h">1h</option>
                        <option value="30m">30m</option>
                      </select>
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Window</div>
                      <select
                        value={btcCorrWindowBars}
                        onChange={(e) => setBtcCorrWindowBars(Math.max(10, Math.min(2000, Number(e.target.value || 72))))}
                        className="flex h-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                      >
                        <option value={48}>48</option>
                        <option value={72}>72</option>
                        <option value={96}>96</option>
                        <option value={144}>144</option>
                      </select>
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Method</div>
                      <select
                        value={btcCorrMethod}
                        onChange={(e) => setBtcCorrMethod((String(e.target.value) as 'pearson' | 'spearman') || 'pearson')}
                        className="flex h-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                      >
                        <option value="pearson">pearson</option>
                        <option value="spearman">spearman</option>
                      </select>
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">End TS</div>
                      <Input value={btcCorrEndTsRaw} onChange={(e) => setBtcCorrEndTsRaw(String(e.target.value ?? ''))} placeholder="(now)" className="w-44" />
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Max N</div>
                      <Input
                        type="number"
                        step="1"
                        value={btcCorrMaxN}
                        onChange={(e) => setBtcCorrMaxN(Math.max(1, Math.min(2000, Number(e.target.value || 200))))}
                        className="w-32"
                      />
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Filter</div>
                      <select
                        value={btcCorrFilterMode}
                        onChange={(e) => setBtcCorrFilterMode((String(e.target.value) as 'ge_thr' | 'all') || 'ge_thr')}
                        className="flex h-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                      >
                        <option value="ge_thr">{`corr >= enter_thr`}</option>
                        <option value="all">all</option>
                      </select>
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Search</div>
                      <Input value={btcCorrSearch} onChange={(e) => setBtcCorrSearch(String(e.target.value ?? ''))} placeholder="BTC, ETH, SOL…" className="w-44" />
                    </div>
                    <div className="space-y-1">
                      <div className="text-xs text-slate-500">Sort</div>
                      <select
                        value={btcCorrSort}
                        onChange={(e) =>
                          setBtcCorrSort(
                            (String(e.target.value) as
                              | 'corr_desc'
                              | 'corr_asc'
                              | 'beta_desc'
                              | 'beta_asc'
                              | 'resid_vol_desc'
                              | 'resid_vol_asc'
                              | 'coin_asc'
                              | 'coin_desc') || 'corr_desc',
                          )
                        }
                        className="flex h-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                      >
                        <option value="corr_desc">corr ↓</option>
                        <option value="corr_asc">corr ↑</option>
                        <option value="beta_desc">beta ↓</option>
                        <option value="beta_asc">beta ↑</option>
                        <option value="resid_vol_desc">resid vol ↓</option>
                        <option value="resid_vol_asc">resid vol ↑</option>
                        <option value="coin_asc">coin A→Z</option>
                        <option value="coin_desc">coin Z→A</option>
                      </select>
                    </div>
                    <Button variant="outline" onClick={() => btcCorrRefetch()} className="gap-2">
                      <RefreshCw className={`h-4 w-4 ${btcCorrFetching ? 'animate-spin' : ''}`} />
                      Refresh
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => {
                        const rows = btcCorrRows;
                        const header = ['coin', 'pair', 'corr', 'beta', 'resid_vol', 'prev_blocked', 'blocked_enter', 'blocked_exit', 'blocked_state', 'cache_hit'].join(',');
                        const body = rows
                          .map((r) =>
                            [
                              r.coin,
                              r.pair,
                              r.corr ?? '',
                              r.beta ?? '',
                              r.resid_vol ?? '',
                              r.prev_blocked ? 1 : 0,
                              r.blocked_enter ? 1 : 0,
                              r.blocked_exit ? 1 : 0,
                              r.blocked_state ? 1 : 0,
                              r.cache_hit ? 1 : 0,
                            ].join(','),
                          )
                          .join('\n');
                        downloadCsv(`btc_corr_research_${btcCorrPool}_${Date.now()}.csv`, `${header}\n${body}\n`);
                      }}
                    >
                      Export CSV
                    </Button>
                    <div className="text-xs text-slate-500">
                      {btcCorrLoading
                        ? 'Loading…'
                        : btcCorrError
                          ? `Failed to load: ${errText(btcCorrError)}`
                          : btcCorr
                            ? `tf=${String(btcCorr.timeframe || btcCorrTimeframe)} window=${btcCorr.window_bars} method=${String(btcCorr.method || btcCorrMethod)} · enter=${fmtFixed(btcCorr.enter_thr, 2)} exit=${fmtFixed(btcCorr.exit_thr, 2)} · missing=${btcCorr.n_total - btcCorr.n_corr}/${btcCorr.n_total} · blocked=${btcCorr.n_blocked_state}/${btcCorr.n_total} · ts=${new Date(btcCorr.ts).toLocaleTimeString()}`
                            : null}
                    </div>
                  </div>

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-base">Buckets</CardTitle>
                      </CardHeader>
                      <CardContent className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                            <tr>
                              <th className="px-3 py-2">Bucket</th>
                              <th className="px-3 py-2">N</th>
                              <th className="px-3 py-2">Blocked</th>
                              <th className="px-3 py-2">Avg Corr</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {btcCorrBuckets.map((b) => (
                              <tr key={b.label} className="hover:bg-slate-50">
                                <td className="px-3 py-2 font-mono text-xs text-slate-800">{b.label}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{b.n}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{b.nBlocked}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(b.avgCorr, 4)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </CardContent>
                    </Card>

                    <Card>
                      <CardHeader>
                        <CardTitle className="text-base">Snapshot</CardTitle>
                      </CardHeader>
                      <CardContent className="text-sm text-slate-700 space-y-1">
                        <div>Total: {btcCorr?.n_total ?? '-'}</div>
                        <div>Corr available: {btcCorr?.n_corr ?? '-'}</div>
                        <div>Blocked (enter): {btcCorr?.n_blocked_enter ?? '-'}</div>
                        <div>Blocked (state/hysteresis): {btcCorr?.n_blocked_state ?? '-'}</div>
                      </CardContent>
                    </Card>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-sm text-left">
                      <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                        <tr>
                          <th className="px-3 py-2">Coin</th>
                          <th className="px-3 py-2">Corr</th>
                          <th className="px-3 py-2">Beta</th>
                          <th className="px-3 py-2">ResidVol</th>
                          <th className="px-3 py-2">Gate</th>
                          <th className="px-3 py-2">Cache</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {btcCorrRows.map((r) => (
                          <tr key={r.coin} className="hover:bg-slate-50">
                            <td className="px-3 py-2 font-mono text-xs text-slate-800">{r.coin}</td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.corr, 4)}</td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.beta, 4)}</td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.resid_vol, 6)}</td>
                            <td className="px-3 py-2">
                              {r.blocked_state ? (
                                <Badge className="bg-red-600 hover:bg-red-600">blocked</Badge>
                              ) : (
                                <Badge className="bg-green-600 hover:bg-green-600">ok</Badge>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              {r.cache_hit ? <Badge variant="secondary">hit</Badge> : <Badge variant="outline">miss</Badge>}
                            </td>
                          </tr>
                        ))}
                        {!btcCorrLoading && !btcCorrError && btcCorrRows.length === 0 && (
                          <tr>
                            <td className="px-3 py-4 text-center text-slate-500" colSpan={6}>
                              Empty
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </TabsContent>

                <TabsContent value="review" className="space-y-4">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Monthly Threshold Review</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {btcCorrReviewAuto ? (
                        <div className="text-xs text-slate-500">
                          Auto cached: ts={String(btcCorrReviewAuto.ts ?? '-')} rec enter=[
                          {fmtFixed(btcCorrReviewAuto.recommended_enter_thr_low ?? null, 2)}, {fmtFixed(btcCorrReviewAuto.recommended_enter_thr_high ?? null, 2)}], mid=
                          {fmtFixed(btcCorrReviewAuto.recommended_enter_thr_mid ?? null, 2)} · tf={String(btcCorrReviewAuto.timeframe ?? '-')} window=
                          {String(btcCorrReviewAuto.window_bars ?? '-')} method={String(btcCorrReviewAuto.method ?? '-')}
                        </div>
                      ) : null}
                      <div className="flex flex-wrap items-end gap-3">
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Months</div>
                          <Input
                            type="number"
                            step="1"
                            value={btcCorrReviewMonths}
                            onChange={(e) => setBtcCorrReviewMonths(Math.max(1, Math.min(24, Number(e.target.value || 6))))}
                            className="w-28"
                          />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Target allow frac</div>
                          <Input
                            type="number"
                            step="0.01"
                            value={btcCorrTargetAllowFrac}
                            onChange={(e) => setBtcCorrTargetAllowFrac(Math.max(0.01, Math.min(0.99, Number(e.target.value || 0.3))))}
                            className="w-36"
                          />
                        </div>
                        <Button variant="outline" onClick={() => btcCorrReviewRefetch()} className="gap-2">
                          <RefreshCw className={`h-4 w-4 ${btcCorrReviewFetching ? 'animate-spin' : ''}`} />
                          Run Review
                        </Button>
                        <div className="text-xs text-slate-500">
                          {btcCorrReviewError
                            ? `Failed: ${errText(btcCorrReviewError)}`
                            : btcCorrReview
                              ? `rec enter=[${fmtFixed(btcCorrReview.recommended_enter_thr_low, 2)}, ${fmtFixed(btcCorrReview.recommended_enter_thr_high, 2)}], mid=${fmtFixed(btcCorrReview.recommended_enter_thr_mid, 2)} · current enter=${fmtFixed(btcCorrReview.current_enter_thr, 2)} · window=${btcCorrReview.window_bars}`
                              : null}
                        </div>
                      </div>

                      {btcCorrReview?.months?.length ? (
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm text-left">
                            <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                              <tr>
                                <th className="px-3 py-2">Month</th>
                                <th className="px-3 py-2">N</th>
                                <th className="px-3 py-2">Suggest enter</th>
                                <th className="px-3 py-2">Allow frac (current)</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                              {btcCorrReview.months.map((m) => (
                                <tr key={m.bucket_ts} className="hover:bg-slate-50">
                                  <td className="px-3 py-2 font-mono text-xs text-slate-800">{new Date(m.asof_ts).toLocaleDateString()}</td>
                                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{m.n_corr}</td>
                                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(m.suggest_enter_thr, 4)}</td>
                                  <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(m.current_allow_frac, 3)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : null}
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="ab" className="space-y-4">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">A/B: Gate OFF vs Gate ON (threshold list)</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="flex flex-wrap items-end gap-3">
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Zip (optional)</div>
                          <Input value={btcCorrEvalZip} onChange={(e) => setBtcCorrEvalZip(String(e.target.value ?? ''))} placeholder="(latest)" className="w-56" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Strategy (optional)</div>
                          <Input value={btcCorrEvalStrategy} onChange={(e) => setBtcCorrEvalStrategy(String(e.target.value ?? ''))} placeholder="(auto)" className="w-40" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Start TS</div>
                          <Input value={btcCorrEvalStartTsRaw} onChange={(e) => setBtcCorrEvalStartTsRaw(String(e.target.value ?? ''))} placeholder="(from zip)" className="w-44" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">End TS</div>
                          <Input value={btcCorrEvalEndTsRaw} onChange={(e) => setBtcCorrEvalEndTsRaw(String(e.target.value ?? ''))} placeholder="(from zip)" className="w-44" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Fee</div>
                          <Input value={btcCorrEvalFeeRaw} onChange={(e) => setBtcCorrEvalFeeRaw(String(e.target.value ?? ''))} placeholder="(from zip)" className="w-28" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Slippage</div>
                          <Input value={btcCorrEvalSlippageRaw} onChange={(e) => setBtcCorrEvalSlippageRaw(String(e.target.value ?? ''))} placeholder="(0)" className="w-28" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Thresholds</div>
                          <Input value={btcCorrAbThresholdsRaw} onChange={(e) => setBtcCorrAbThresholdsRaw(String(e.target.value ?? ''))} placeholder="0.5,0.7,0.9" className="w-56" />
                        </div>
                        <Button variant="outline" onClick={() => btcCorrAbRefetch()} className="gap-2">
                          <RefreshCw className={`h-4 w-4 ${btcCorrAbFetching ? 'animate-spin' : ''}`} />
                          Run A/B
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            const rows = btcCorrAb?.ab ?? [];
                            const header = [
                              'thr',
                              'n',
                              'coverage',
                              'take_rate',
                              'profit_total_pct',
                              'profit_total_abs',
                              'max_drawdown_account',
                              'winrate',
                              'profit_factor',
                              'sharpe',
                              'sortino',
                              'avg_trade_duration_min',
                            ].join(',');
                            const body = rows
                              .map((r) =>
                                [
                                  r.thr,
                                  r.n,
                                  r.coverage,
                                  r.take_rate,
                                  r.metrics?.profit_total_pct ?? '',
                                  r.metrics?.profit_total_abs ?? '',
                                  r.metrics?.max_drawdown_account ?? '',
                                  r.metrics?.winrate ?? '',
                                  r.metrics?.profit_factor ?? '',
                                  r.metrics?.sharpe ?? '',
                                  r.metrics?.sortino ?? '',
                                  r.metrics?.avg_trade_duration_min ?? '',
                                ].join(','),
                              )
                              .join('\n');
                            downloadCsv(`btc_corr_ab_${Date.now()}.csv`, `${header}\n${body}\n`);
                          }}
                          disabled={!btcCorrAb?.ab?.length}
                        >
                          Export CSV
                        </Button>
                        <div className="text-xs text-slate-500">
                          {btcCorrAbError
                            ? `Failed: ${errText(btcCorrAbError)}`
                            : btcCorrAb
                              ? `zip=${btcCorrAb.zip} strategy=${String(btcCorrAb.strategy ?? '-')} · base n=${btcCorrAb.base?.n ?? '-'} · tf=${String(btcCorrAb.corr?.timeframe ?? '-')} window=${btcCorrAb.corr?.window_bars ?? '-'} method=${String(btcCorrAb.corr?.method ?? '-')}`
                              : null}
                        </div>
                      </div>

                      <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                            <tr>
                              <th className="px-3 py-2">Thr</th>
                              <th className="px-3 py-2">N</th>
                              <th className="px-3 py-2">Coverage</th>
                              <th className="px-3 py-2">Take-rate</th>
                              <th className="px-3 py-2">Pnl%</th>
                              <th className="px-3 py-2">MaxDD</th>
                              <th className="px-3 py-2">Winrate</th>
                              <th className="px-3 py-2">PF</th>
                              <th className="px-3 py-2">Sharpe</th>
                              <th className="px-3 py-2">AvgDur(min)</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {(btcCorrAb?.ab ?? []).map((r) => (
                              <tr key={String(r.thr)} className="hover:bg-slate-50">
                                <td className="px-3 py-2 font-mono text-xs text-slate-800">{fmtFixed(r.thr, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{r.n}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.coverage, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.take_rate, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtPct(r.metrics?.profit_total_pct ?? null, 2)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.metrics?.max_drawdown_account ?? null, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.metrics?.winrate ?? null, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.metrics?.profit_factor ?? null, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.metrics?.sharpe ?? null, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(r.metrics?.avg_trade_duration_min ?? null, 0)}</td>
                              </tr>
                            ))}
                            {!btcCorrAbFetching && !btcCorrAbError && !(btcCorrAb?.ab ?? []).length && (
                              <tr>
                                <td className="px-3 py-4 text-center text-slate-500" colSpan={10}>
                                  Empty
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="bucket" className="space-y-4">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Bucket: corr bins explainability</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="flex flex-wrap items-end gap-3">
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Zip (optional)</div>
                          <Input value={btcCorrEvalZip} onChange={(e) => setBtcCorrEvalZip(String(e.target.value ?? ''))} placeholder="(latest)" className="w-56" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Strategy (optional)</div>
                          <Input value={btcCorrEvalStrategy} onChange={(e) => setBtcCorrEvalStrategy(String(e.target.value ?? ''))} placeholder="(auto)" className="w-40" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Start TS</div>
                          <Input value={btcCorrEvalStartTsRaw} onChange={(e) => setBtcCorrEvalStartTsRaw(String(e.target.value ?? ''))} placeholder="(from zip)" className="w-44" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">End TS</div>
                          <Input value={btcCorrEvalEndTsRaw} onChange={(e) => setBtcCorrEvalEndTsRaw(String(e.target.value ?? ''))} placeholder="(from zip)" className="w-44" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Fee</div>
                          <Input value={btcCorrEvalFeeRaw} onChange={(e) => setBtcCorrEvalFeeRaw(String(e.target.value ?? ''))} placeholder="(from zip)" className="w-28" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Slippage</div>
                          <Input value={btcCorrEvalSlippageRaw} onChange={(e) => setBtcCorrEvalSlippageRaw(String(e.target.value ?? ''))} placeholder="(0)" className="w-28" />
                        </div>
                        <Button variant="outline" onClick={() => btcCorrBucketRefetch()} className="gap-2">
                          <RefreshCw className={`h-4 w-4 ${btcCorrBucketFetching ? 'animate-spin' : ''}`} />
                          Run Bucket
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            const rows = btcCorrBucketEval?.buckets ?? [];
                            const header = ['bucket', 'lo', 'hi', 'n', 'coverage', 'profit_total_pct', 'profit_total_abs', 'max_drawdown_account', 'winrate', 'profit_factor'].join(',');
                            const body = rows
                              .map((r) =>
                                [
                                  r.bucket,
                                  r.lo,
                                  r.hi,
                                  r.n,
                                  r.coverage,
                                  r.metrics?.profit_total_pct ?? '',
                                  r.metrics?.profit_total_abs ?? '',
                                  r.metrics?.max_drawdown_account ?? '',
                                  r.metrics?.winrate ?? '',
                                  r.metrics?.profit_factor ?? '',
                                ].join(','),
                              )
                              .join('\n');
                            downloadCsv(`btc_corr_bucket_${Date.now()}.csv`, `${header}\n${body}\n`);
                          }}
                          disabled={!btcCorrBucketEval?.buckets?.length}
                        >
                          Export CSV
                        </Button>
                        <div className="text-xs text-slate-500">
                          {btcCorrBucketError
                            ? `Failed: ${errText(btcCorrBucketError)}`
                            : btcCorrBucketEval
                              ? `zip=${btcCorrBucketEval.zip} strategy=${String(btcCorrBucketEval.strategy ?? '-')} · with_corr n=${btcCorrBucketEval.with_corr?.n ?? '-'} · tf=${String(btcCorrBucketEval.corr?.timeframe ?? '-')} window=${btcCorrBucketEval.corr?.window_bars ?? '-'} method=${String(btcCorrBucketEval.corr?.method ?? '-')}`
                              : null}
                        </div>
                      </div>

                      <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                            <tr>
                              <th className="px-3 py-2">Bucket</th>
                              <th className="px-3 py-2">N</th>
                              <th className="px-3 py-2">Coverage</th>
                              <th className="px-3 py-2">Pnl%</th>
                              <th className="px-3 py-2">MaxDD</th>
                              <th className="px-3 py-2">Winrate</th>
                              <th className="px-3 py-2">PF</th>
                              <th className="px-3 py-2">AvgDur(min)</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {(btcCorrBucketEval?.buckets ?? []).map((b) => (
                              <tr key={b.bucket} className="hover:bg-slate-50">
                                <td className="px-3 py-2 font-mono text-xs text-slate-800">{b.bucket}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{b.n}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(b.coverage, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtPct(b.metrics?.profit_total_pct ?? null, 2)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(b.metrics?.max_drawdown_account ?? null, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(b.metrics?.winrate ?? null, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(b.metrics?.profit_factor ?? null, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(b.metrics?.avg_trade_duration_min ?? null, 0)}</td>
                              </tr>
                            ))}
                            {!btcCorrBucketFetching && !btcCorrBucketError && !(btcCorrBucketEval?.buckets ?? []).length && (
                              <tr>
                                <td className="px-3 py-4 text-center text-slate-500" colSpan={8}>
                                  Empty
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>

                <TabsContent value="walkforward" className="space-y-4">
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">Walk-forward: rolling recommend threshold range</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="flex flex-wrap items-end gap-3">
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Zip (optional)</div>
                          <Input value={btcCorrEvalZip} onChange={(e) => setBtcCorrEvalZip(String(e.target.value ?? ''))} placeholder="(latest)" className="w-56" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Strategy (optional)</div>
                          <Input value={btcCorrEvalStrategy} onChange={(e) => setBtcCorrEvalStrategy(String(e.target.value ?? ''))} placeholder="(auto)" className="w-40" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Start TS</div>
                          <Input value={btcCorrEvalStartTsRaw} onChange={(e) => setBtcCorrEvalStartTsRaw(String(e.target.value ?? ''))} placeholder="(auto)" className="w-44" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">End TS</div>
                          <Input value={btcCorrEvalEndTsRaw} onChange={(e) => setBtcCorrEvalEndTsRaw(String(e.target.value ?? ''))} placeholder="(auto)" className="w-44" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Fee</div>
                          <Input value={btcCorrEvalFeeRaw} onChange={(e) => setBtcCorrEvalFeeRaw(String(e.target.value ?? ''))} placeholder="(from zip)" className="w-28" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Slippage</div>
                          <Input value={btcCorrEvalSlippageRaw} onChange={(e) => setBtcCorrEvalSlippageRaw(String(e.target.value ?? ''))} placeholder="(0)" className="w-28" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Thresholds</div>
                          <Input value={btcCorrAbThresholdsRaw} onChange={(e) => setBtcCorrAbThresholdsRaw(String(e.target.value ?? ''))} placeholder="0.3,0.5,0.7,0.9" className="w-56" />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Period</div>
                          <select
                            value={btcCorrWfPeriod}
                            onChange={(e) => setBtcCorrWfPeriod((String(e.target.value) as 'month' | 'quarter') || 'month')}
                            className="flex h-10 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2"
                          >
                            <option value="month">month</option>
                            <option value="quarter">quarter</option>
                          </select>
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Min trades</div>
                          <Input
                            type="number"
                            step="1"
                            value={btcCorrWfMinTrades}
                            onChange={(e) => setBtcCorrWfMinTrades(Math.max(1, Math.min(200, Number(e.target.value || 5))))}
                            className="w-28"
                          />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Take-rate min</div>
                          <Input
                            type="number"
                            step="0.01"
                            value={btcCorrWfTakeRateMin}
                            onChange={(e) => setBtcCorrWfTakeRateMin(Math.max(0, Math.min(1, Number(e.target.value || 0.1))))}
                            className="w-28"
                          />
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-slate-500">Take-rate max</div>
                          <Input
                            type="number"
                            step="0.01"
                            value={btcCorrWfTakeRateMax}
                            onChange={(e) => setBtcCorrWfTakeRateMax(Math.max(0, Math.min(1, Number(e.target.value || 0.9))))}
                            className="w-28"
                          />
                        </div>
                        <Button variant="outline" onClick={() => btcCorrWalkforwardRefetch()} className="gap-2">
                          <RefreshCw className={`h-4 w-4 ${btcCorrWalkforwardFetching ? 'animate-spin' : ''}`} />
                          Run Walk-forward
                        </Button>
                        <Button
                          variant="outline"
                          onClick={async () => {
                            const s = btcCorrWalkforward?.summary;
                            const mid = s?.recommended_enter_thr_mid;
                            if (mid == null) return;
                            const obj = {
                              strategy_btc_corr_threshold: mid,
                              recommended_enter_thr_low: s?.recommended_enter_thr_low ?? null,
                              recommended_enter_thr_mid: s?.recommended_enter_thr_mid ?? null,
                              recommended_enter_thr_high: s?.recommended_enter_thr_high ?? null,
                            };
                            await copyText(JSON.stringify(obj));
                          }}
                          disabled={btcCorrWalkforward?.summary?.recommended_enter_thr_mid == null}
                        >
                          Copy Config
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => {
                            const rows = btcCorrWalkforward?.periods ?? [];
                            const header = ['period', 'start_ts', 'end_ts', 'n', 'with_corr_n', 'best_thr', 'best_n', 'best_take_rate', 'best_pnl_pct', 'best_max_dd'].join(',');
                            const body = rows
                              .map((p) => {
                                const best = p.best;
                                return [
                                  p.label,
                                  p.start_ts,
                                  p.end_ts,
                                  p.n,
                                  p.with_corr_n,
                                  p.best_thr ?? '',
                                  best?.n ?? '',
                                  best?.take_rate ?? '',
                                  best?.metrics?.profit_total_pct ?? '',
                                  best?.metrics?.max_drawdown_account ?? '',
                                ].join(',');
                              })
                              .join('\n');
                            downloadCsv(`btc_corr_walkforward_${Date.now()}.csv`, `${header}\n${body}\n`);
                          }}
                          disabled={!btcCorrWalkforward?.periods?.length}
                        >
                          Export CSV
                        </Button>
                        <div className="text-xs text-slate-500">
                          {btcCorrWalkforwardError
                            ? `Failed: ${errText(btcCorrWalkforwardError)}`
                            : btcCorrWalkforward
                              ? `zip=${btcCorrWalkforward.zip} strategy=${String(btcCorrWalkforward.strategy ?? '-')} · rec=[${fmtFixed(btcCorrWalkforward.summary?.recommended_enter_thr_low, 2)}, ${fmtFixed(btcCorrWalkforward.summary?.recommended_enter_thr_high, 2)}], mid=${fmtFixed(btcCorrWalkforward.summary?.recommended_enter_thr_mid, 2)} · periods=${btcCorrWalkforward.summary?.n_periods ?? '-'}`
                              : null}
                        </div>
                      </div>

                      <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                          <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                            <tr>
                              <th className="px-3 py-2">Period</th>
                              <th className="px-3 py-2">N</th>
                              <th className="px-3 py-2">WithCorr</th>
                              <th className="px-3 py-2">Best Thr</th>
                              <th className="px-3 py-2">Take-rate</th>
                              <th className="px-3 py-2">Pnl%</th>
                              <th className="px-3 py-2">MaxDD</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100">
                            {(btcCorrWalkforward?.periods ?? []).map((p) => (
                              <tr key={p.label} className="hover:bg-slate-50">
                                <td className="px-3 py-2 font-mono text-xs text-slate-800">{p.label}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{p.n}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{p.with_corr_n}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(p.best_thr, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(p.best?.take_rate ?? null, 3)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtPct(p.best?.metrics?.profit_total_pct ?? null, 2)}</td>
                                <td className="px-3 py-2 font-mono text-xs text-slate-700">{fmtFixed(p.best?.metrics?.max_drawdown_account ?? null, 3)}</td>
                              </tr>
                            ))}
                            {!btcCorrWalkforwardFetching && !btcCorrWalkforwardError && !(btcCorrWalkforward?.periods ?? []).length && (
                              <tr>
                                <td className="px-3 py-4 text-center text-slate-500" colSpan={7}>
                                  Empty
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="pools">
          <div className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <Card>
              <CardHeader>
                <CardTitle>Liquidity Buckets</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="text-xs text-slate-500 mb-2">HIGH ({liqHigh.length})</div>
                  {renderCoinBadges(liqHigh, 'default')}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-2">MED ({liqMed.length})</div>
                  {renderCoinBadges(liqMed, 'secondary')}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-2">LOW ({liqLow.length})</div>
                  {renderCoinBadges(liqLow, 'outline')}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Beta Buckets</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="text-xs text-slate-500 mb-2">HIGH ({betaHigh.length})</div>
                  {renderCoinBadges(betaHigh, 'default')}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-2">MID ({betaMid.length})</div>
                  {renderCoinBadges(betaMid, 'secondary')}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-2">LOW ({betaLow.length})</div>
                  {renderCoinBadges(betaLow, 'outline')}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Quality Buckets</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="text-xs text-slate-500 mb-2">GOOD ({qualityGood.length})</div>
                  {renderCoinBadges(qualityGood, 'default')}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-2">OK ({qualityOk.length})</div>
                  {renderCoinBadges(qualityOk, 'secondary')}
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-2">BAD ({qualityBad.length})</div>
                  {renderCoinBadges(qualityBad, 'outline')}
                </div>
              </CardContent>
            </Card>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Cluster Pools</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {clusterEntries.length === 0 && (
                    <div className="col-span-full text-sm text-gray-400">No cluster pools available</div>
                  )}
                  {clusterEntries
                    .sort((a, b) => a[0].localeCompare(b[0]))
                    .map(([cid, members]) => (
                      (() => {
                        const ms = asStringList(members);
                        return (
                      <div key={cid} className="border rounded p-4">
                        <div className="flex items-center justify-between">
                          <div className="font-semibold">{cid}</div>
                          <div className="text-xs text-slate-500">{ms.length}</div>
                        </div>
                        <div className="mt-3">{renderCoinBadges(ms.slice(0, 24), 'secondary')}</div>
                        {ms.length > 24 && (
                          <div className="mt-2 text-xs text-slate-500">+{ms.length - 24} more</div>
                        )}
                      </div>
                        );
                      })()
                    ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="clusters">
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>Cluster Consistency</span>
                  {badgeForConsistency(consistency?.status)}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  <div>
                    <div className="text-xs text-slate-500">timeframe</div>
                    <div className="font-medium">{consistency?.timeframe ?? '-'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500">window_bars</div>
                    <div className="font-medium">{consistency?.window_bars ?? '-'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500">ARI</div>
                    <div className="font-medium">{consistency?.ari == null ? '-' : Number(consistency.ari).toFixed(3)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500">NMI</div>
                    <div className="font-medium">{consistency?.nmi == null ? '-' : Number(consistency.nmi).toFixed(3)}</div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500">avg_retention</div>
                    <div className="font-medium">
                      {consistency?.cluster_retention?.avg_retention == null ? '-' : Number(consistency.cluster_retention.avg_retention).toFixed(3)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500">avg_centroid_drift</div>
                    <div className="font-medium">
                      {consistency?.centroid_drift?.avg_drift == null ? '-' : Number(consistency.centroid_drift.avg_drift).toFixed(3)}
                    </div>
                  </div>
                  <div className="col-span-2">
                    <div className="text-xs text-slate-500">reasons</div>
                    <div className="font-medium">{Array.isArray(consistency?.reasons) && consistency?.reasons.length ? consistency.reasons.join(', ') : '-'}</div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Clusters</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                      <tr>
                        <th className="px-3 py-2">Cluster</th>
                        <th className="px-3 py-2">Members</th>
                        <th className="px-3 py-2">avg_beta</th>
                        <th className="px-3 py-2">avg_corr</th>
                        <th className="px-3 py-2">avg_resid_vol</th>
                        <th className="px-3 py-2">avg_turnover</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {Object.keys(clusters).length === 0 && (
                        <tr>
                          <td colSpan={6} className="px-3 py-4 text-center text-gray-500">
                            No clusters available
                          </td>
                        </tr>
                      )}
                      {Object.entries(clusters)
                        .sort((a, b) => a[0].localeCompare(b[0]))
                        .map(([cid, c]) => (
                          <tr key={cid} className="hover:bg-slate-50">
                            <td className="px-3 py-2 font-medium">{c.cluster_id ?? cid}</td>
                            <td className="px-3 py-2">{Array.isArray(c.members) ? c.members.length : 0}</td>
                            <td className="px-3 py-2">{c.centroid?.avg_beta == null ? '-' : Number(c.centroid.avg_beta).toFixed(3)}</td>
                            <td className="px-3 py-2">{c.centroid?.avg_corr_to_btc == null ? '-' : Number(c.centroid.avg_corr_to_btc).toFixed(3)}</td>
                            <td className="px-3 py-2">{c.centroid?.avg_resid_vol == null ? '-' : Number(c.centroid.avg_resid_vol).toFixed(5)}</td>
                            <td className="px-3 py-2">
                              {c.centroid?.avg_turnover_7d_median == null ? '-' : `$${Math.round(Number(c.centroid.avg_turnover_7d_median)).toLocaleString()}`}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>

                <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
                  {Object.entries(clusters)
                    .sort((a, b) => a[0].localeCompare(b[0]))
                    .map(([cid, c]) => (
                      <div key={cid} className="border rounded p-4">
                        <div className="flex items-center justify-between">
                          <div className="font-semibold">{c.cluster_id ?? cid}</div>
                          <div className="text-xs text-slate-500">{Array.isArray(c.members) ? c.members.length : 0} members</div>
                        </div>
                        <div className="mt-3">{renderCoinBadges((c.members ?? []).slice(0, 30), 'secondary')}</div>
                        {Array.isArray(c.members) && c.members.length > 30 && (
                          <div className="mt-2 text-xs text-slate-500">+{c.members.length - 30} more</div>
                        )}
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="candidates">
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>Selection Hints</span>
                  <Badge variant="outline">btc_alt_candidates: {(selectionHints.btc_alt_candidates ?? []).length}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="text-xs text-slate-500 mb-2">btc_alt_candidates</div>
                  {renderCoinBadges(selectionHints.btc_alt_candidates, 'default')}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                  <div>
                    <div className="text-xs text-slate-500">topk_per_cluster</div>
                    <div className="font-medium">{selectionHints.topk_per_cluster ?? '-'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500">excluded_clusters</div>
                    <div className="font-medium">
                      {Array.isArray(selectionHints.excluded_clusters) && selectionHints.excluded_clusters.length ? selectionHints.excluded_clusters.join(', ') : '-'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-slate-500">excluded_coins</div>
                    <div className="font-medium">
                      {Array.isArray(selectionHints.excluded_coins) && selectionHints.excluded_coins.length ? selectionHints.excluded_coins.join(', ') : '-'}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Candidates</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
                      <tr>
                        <th className="px-3 py-2">Rank</th>
                        <th className="px-3 py-2">Coin</th>
                        <th className="px-3 py-2">Score</th>
                        <th className="px-3 py-2">Turnover</th>
                        <th className="px-3 py-2">Beta</th>
                        <th className="px-3 py-2">Corr</th>
                        <th className="px-3 py-2">ResidVol</th>
                        <th className="px-3 py-2">Cluster</th>
                        <th className="px-3 py-2">liq</th>
                        <th className="px-3 py-2">beta</th>
                        <th className="px-3 py-2">quality</th>
                        <th className="px-3 py-2">Issues</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {candidates.length === 0 && (
                        <tr>
                          <td colSpan={12} className="px-3 py-4 text-center text-gray-500">
                            No candidates available
                          </td>
                        </tr>
                      )}
                      {candidates.slice(0, 120).map((c) => (
                        <tr key={c.coin} className="hover:bg-slate-50">
                          <td className="px-3 py-2">{c.rank ?? '-'}</td>
                          <td className="px-3 py-2 font-medium">{c.coin}</td>
                          <td className="px-3 py-2">{c.score == null ? '-' : Number(c.score).toFixed(4)}</td>
                          <td className="px-3 py-2">{c.liq?.turnover_7d_median == null ? '-' : `$${Math.round(Number(c.liq.turnover_7d_median)).toLocaleString()}`}</td>
                          <td className="px-3 py-2">{c.btc_exposure?.beta == null ? '-' : Number(c.btc_exposure.beta).toFixed(3)}</td>
                          <td className="px-3 py-2">{c.btc_exposure?.corr == null ? '-' : Number(c.btc_exposure.corr).toFixed(3)}</td>
                          <td className="px-3 py-2">{c.btc_exposure?.resid_vol == null ? '-' : Number(c.btc_exposure.resid_vol).toFixed(5)}</td>
                          <td className="px-3 py-2">{c.cluster?.cluster_id ?? '-'}</td>
                          <td className="px-3 py-2">{c.pools?.liq_bucket ?? '-'}</td>
                          <td className="px-3 py-2">{c.pools?.beta_bucket ?? '-'}</td>
                          <td className="px-3 py-2">{c.pools?.quality_bucket ?? '-'}</td>
                          <td className="px-3 py-2">{Array.isArray(c.issues) && c.issues.length ? c.issues.join(', ') : '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {candidates.length > 120 && (
                  <div className="mt-3 text-xs text-slate-500">Showing top 120 candidates (of {candidates.length})</div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="snapshot">
          <Card>
            <CardHeader>
              <CardTitle>Market Snapshot</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div>
                  <div className="text-xs text-slate-500">run_ms</div>
                  <div className="font-medium">
                    {toNum(marketSnapshot?.run_ms) ? new Date(Number(marketSnapshot?.run_ms)).toLocaleString() : '-'}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">venue</div>
                  <div className="font-medium">{String(marketSnapshot?.venue ?? '-')}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">coverage</div>
                  <div className="font-medium">
                    symbols {String(marketSnapshot?.symbols_total ?? '-')}
                    {' · '}mids {String(marketSnapshot?.mids_total ?? '-')}
                    {' · '}stage_a {String(marketSnapshot?.stage_a_candidates ?? '-')}
                  </div>
                </div>
              </div>
              {renderKv(marketSnapshot)}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="hyperparams">
          <Card>
            <CardHeader>
              <CardTitle>Clustering Hyperparams</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {renderKv(clusteringHyperparams)}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="whitelist">
          <Card>
            <CardHeader>
              <CardTitle>Trade Whitelist Auto</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                <div>
                  <div className="text-xs text-slate-500">enabled</div>
                  <div className="font-medium">{String(tradeWhitelistAuto?.enabled ?? '-')}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">source</div>
                  <div className="font-medium">{String(tradeWhitelistAuto?.source ?? '-')}</div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">run_ms</div>
                  <div className="font-medium">
                    {toNum(tradeWhitelistAuto?.run_ms) ? new Date(Number(tradeWhitelistAuto?.run_ms)).toLocaleString() : '-'}
                  </div>
                </div>
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-2">coins</div>
                {renderCoinBadges((tradeWhitelistAuto?.coins as unknown as string[] | undefined) ?? [], 'secondary')}
              </div>
              <div>
                <div className="text-xs text-slate-500 mb-2">whitelist</div>
                {renderCoinBadges((tradeWhitelistAuto?.whitelist as unknown as string[] | undefined) ?? [], 'outline')}
              </div>
              {renderKv(tradeWhitelistAuto)}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="monitoring">
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Alerts</CardTitle>
              </CardHeader>
              <CardContent>
                {Array.isArray((monitoringHints as { alerts?: unknown } | undefined)?.alerts) &&
                ((monitoringHints as { alerts?: unknown } | undefined)?.alerts as unknown[]).length ? (
                  <div className="space-y-2">
                    {((monitoringHints as { alerts?: unknown } | undefined)?.alerts as unknown[]).map((a, i) => {
                      const r = a as Record<string, unknown>;
                      const level = String(r.level ?? 'info');
                      const key = String(r.key ?? '');
                      const msg = String(r.message ?? '');
                      const ts = toNum(r.ts);
                      const badgeVariant: React.ComponentProps<typeof Badge>['variant'] =
                        level === 'crit' ? 'destructive' : level === 'warn' ? 'secondary' : 'outline';
                      return (
                        <div key={`${key}-${i}`} className="flex items-start justify-between gap-3 border rounded p-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <Badge variant={badgeVariant}>{level}</Badge>
                              <span className="font-mono text-xs text-slate-700 truncate">{key || '-'}</span>
                            </div>
                            <div className="mt-1 text-sm text-slate-800 break-words">{msg || '-'}</div>
                          </div>
                          <div className="text-xs text-slate-500 whitespace-nowrap">
                            {ts ? new Date(Number(ts)).toLocaleString() : '-'}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="text-sm text-gray-400">No alerts</div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Diagnostics</CardTitle>
              </CardHeader>
              <CardContent>{renderKv((monitoringHints as { diagnostics?: unknown } | undefined)?.diagnostics as Record<string, unknown> | undefined)}</CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
};
