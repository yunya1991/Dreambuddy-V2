import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import {
  createAutoTradeExitIntent,
  createAutoTradeOrderIntent,
  createAutoTradePositionOpen,
  createAutoTradePositionSnapshot,
  fetchAgentAutomationAutoTradeDecisions,
  fetchAgentAutomationAutoTradeState,
  fetchAgentAutomationWeb3MarketDigest,
  fetchAgentOutboxFiles,
  fetchAgentOutboxRead,
  fetchAutoTradePositions,
  hasOperatorToken,
  runAutoTradeExitReview,
  runAutomationWeb3MarketDigest,
  runAutoTradePrecheck,
  setAutomationConfig,
  triggerAutoTradeKillSwitch,
} from '../lib/api';

type OutboxRow = { offset: number; item: unknown };

type Web3MarketDigestRow = {
  type?: unknown;
  ts?: unknown;
  trace_id?: unknown;
  channel?: unknown;
  digest?: unknown;
};

type Digest = {
  ts?: unknown;
  trace_id?: unknown;
  config?: Record<string, unknown>;
  top?: { trending?: unknown[]; top_search?: unknown[]; smart_money_inflow?: unknown[] };
  rankings?: unknown;
  attention_state?: unknown;
  flow_state?: unknown;
  regime_guess?: unknown;
  watchlist?: unknown[];
  watch_addresses?: unknown[];
  address_insights?: unknown[];
  factors?: unknown;
  llm?: unknown;
  tweets?: unknown[];
};

type PersistedLatest = {
  tsMs: number;
  traceId: string;
  digest: Digest | null;
  savedAtMs: number;
};

type PositionRow = {
  position_id: string;
  chain_id?: unknown;
  contract_address?: unknown;
  symbol?: unknown;
  entry_ts_ms?: unknown;
  entry_ref?: unknown;
  size_token?: unknown;
  notional_usd?: unknown;
  status?: unknown;
  last_snapshot_ts_ms?: unknown;
};

function _errStr(e: unknown): string {
  if (typeof e === 'object' && e) {
    const r = (e as { response?: { data?: unknown } }).response;
    const d = r?.data;
    if (d && typeof d === 'object') {
      const err = (d as Record<string, unknown>).error;
      if (typeof err === 'string' && err.trim()) return err;
      const msg = (d as Record<string, unknown>).message;
      if (typeof msg === 'string' && msg.trim()) return msg;
    }
  }
  if (e instanceof Error) return e.message;
  if (typeof e === 'object' && e && 'message' in e) {
    const m = (e as Record<string, unknown>).message;
    if (typeof m === 'string') return m;
  }
  return String(e);
}

function _toStr(v: unknown): string {
  return v == null ? '' : String(v);
}

function _toNum(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function _fmtAgo(nowMs: number, tsMs: number): string {
  const ms = Math.max(0, nowMs - tsMs);
  const sec = Math.floor(ms / 1000);
  const m = Math.floor(sec / 60);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (d > 0) return `${d}d${h % 24}h ago`;
  if (h > 0) return `${h}h${m % 60}m ago`;
  if (m > 0) return `${m}m ago`;
  return `${sec}s ago`;
}

function _safeArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function _safeObj(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' ? (v as Record<string, unknown>) : null;
}

function _clip(s: string, n: number): string {
  const x = s.trim();
  return x.length <= n ? x : `${x.slice(0, Math.max(0, n - 1))}…`;
}

function _uniqStrings(v: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of v) {
    const s = raw.trim();
    if (!s) continue;
    if (seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

function _fmtUsd(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return '-';
  const a = Math.abs(n);
  if (a >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${(n / 1e3).toFixed(2)}K`;
  return `$${Math.round(n)}`;
}

function _clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return Math.max(0, Math.min(1, v));
}

const LS_KEY_LATEST = 'web3_market_digest.latest_v1';
const LS_KEY_STATE = 'web3_market_digest.state_v1';
const LS_KEY_DECISION_COLLAPSED = 'web3_market_digest.auto.decision_collapsed_v1';

function _lsGetJson(key: string): unknown | null {
  try {
    if (typeof window === 'undefined') return null;
    const raw = String(window.localStorage.getItem(key) ?? '').trim();
    if (!raw) return null;
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function _lsSetJson(key: string, value: unknown): void {
  try {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    void 0;
  }
}

const DOC_CARDS: { id: string; title: string; subtitle: string; bullets: string[] }[] = [
  {
    id: 'rankings',
    title: '市场榜单（crypto_market_rank）',
    subtitle: '注意力 / 资金流 / 高手行为层',
    bullets: [
      'trending / top_search：注意力因子（类比新闻/搜索热度/资金关注度）',
      'smart_money_inflow：资金流因子（类比主动买盘/机构净流入）',
      'top_traders_pnl：高手/强者因子（类比顶级交易员榜单）',
      '输出重点：哪些币“被看到”、哪些币“被买入”、哪些币“被高手交易”',
    ],
  },
  {
    id: 'token_info',
    title: '代币详情（query_token_info）',
    subtitle: '基础画像 / 市场质量层',
    bullets: [
      'metadata：symbol、合约地址、链、logo 等（身份与可交易性）',
      'market：price、liquidity、holders、volume24h、pctChange24h 等（市场质量与流动性约束）',
      '输出重点：把榜单候选落地为可交易标的，并量化“是否可做/怎么做（仓位/止损/滑点）”',
    ],
  },
  {
    id: 'address_info',
    title: '地址洞察（query_address_info）',
    subtitle: '链上持仓 / 资金画像层',
    bullets: [
      '用途 1：跟踪观察地址池（top_traders 地址、自定义鲸鱼/KOL、项目方/基金地址等）',
      '用途 2：对候选做“集中度/大户行为变化”的解释性证据（增持/减仓）',
      '输出重点：提供“因果解释线索”而不是内幕推断',
    ],
  },
  {
    id: 'candidates',
    title: '候选池（漏斗式）',
    subtitle: '从榜单到可交易清单',
    bullets: [
      'Step A：合并 trending/top_search/smart_money_inflow 的 topN 去重，得到 C0（15–25）',
      'Step B：用 token_info 做市场质量过滤（liquidity/volume24h 低于阈值 → 降级观察），得到 C1',
      'Step C：对 C1 最强 5–10 个结合地址洞察取证，得到 C2（建议区）',
    ],
  },
  {
    id: 'brief',
    title: '市场情报简报（结构）',
    subtitle: '机器可读 JSON + 人可读摘要',
    bullets: [
      'Market Regime Snapshot：热点集中度、聪明钱换榜稳定性、候选平均流动性/成交量、三因子共振',
      'Opportunities：画像（链/合约/价格/24h/成交量/流动性/holders）+ 入选原因 + 交易约束（非指令）',
      'Risk Alerts：薄流动性/过热、榜单驱动但资金流不匹配、高集中度/操纵风险、观察地址减仓迹象',
    ],
  },
  {
    id: 'llm',
    title: '大模型建议（每 1h 自动输出）',
    subtitle: '固定 schema + 线程推文',
    bullets: [
      '输入：market_snapshot / rankings / tokens / addresses_watch / constraints',
      '输出：summary、regime、watchlist（reason/risk/invalidations）、action_suggestions、risk_alerts、tweets(thread)',
      '强约束：不含收益承诺/价格目标/明确买卖点，必须包含失效条件与风险提示（NFA）',
    ],
  },
];

type Web3MarketDigestPanelProps = {
  forcedTab?: 'research' | 'auto';
  hideTabSwitch?: boolean;
  allowWrite?: boolean;
};

export const Web3MarketDigestPanel: React.FC<Web3MarketDigestPanelProps> = ({ forcedTab, hideTabSwitch = false, allowWrite = true }) => {
  const [nowMs, setNowMs] = useState<number>(() => Date.now());
  const [isVisible, setIsVisible] = useState<boolean>(() => {
    try {
      if (typeof document === 'undefined') return true;
      return !document.hidden;
    } catch {
      return true;
    }
  });
  const [offset, setOffset] = useState<number>(0);
  const offsetRef = useRef<number>(0);
  const [rows, setRows] = useState<OutboxRow[]>([]);
  const [pollError, setPollError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [persistedLatest, setPersistedLatest] = useState<PersistedLatest | null>(() => {
    const v = _lsGetJson(LS_KEY_LATEST);
    const obj = _safeObj(v);
    if (!obj) return null;
    const tsMs = Number(obj.tsMs ?? NaN);
    const traceId = _toStr(obj.traceId ?? '');
    const digest = (_safeObj(obj.digest) as Digest | null) ?? null;
    const savedAtMs = Number(obj.savedAtMs ?? NaN);
    if (!Number.isFinite(tsMs) || !traceId.trim()) return null;
    return {
      tsMs,
      traceId,
      digest,
      savedAtMs: Number.isFinite(savedAtMs) ? savedAtMs : Date.now(),
    };
  });
  const outboxName = 'web3_digest.jsonl';
  const [tab, setTab] = useState<'research' | 'auto'>(forcedTab === 'auto' ? 'auto' : 'research');
  const [decisionWindow, setDecisionWindow] = useState<'1h' | '6h' | '24h' | 'custom'>('6h');
  const [decisionWindowCustomMin, setDecisionWindowCustomMin] = useState<string>('180');
  const [decisionCollapsedPref, setDecisionCollapsedPref] = useState<boolean | null>(() => {
    const v = _lsGetJson(LS_KEY_DECISION_COLLAPSED);
    if (typeof v === 'boolean') return v;
    return null;
  });
  const [tradeChainId, setTradeChainId] = useState('56');
  const [tradeContractAddress, setTradeContractAddress] = useState('');
  const [tradeSymbol, setTradeSymbol] = useState('');
  const [tradeSide, setTradeSide] = useState<'buy' | 'sell'>('buy');
  const [tradeNotionalUsd, setTradeNotionalUsd] = useState('50');
  const [tradeSlippageBps, setTradeSlippageBps] = useState('300');
  const [precheckSnap, setPrecheckSnap] = useState<Record<string, unknown> | null>(null);
  const [autoTradeEnablePassword, setAutoTradeEnablePassword] = useState('');
  const [positionSizeToken, setPositionSizeToken] = useState('0');
  const [positionEntryRef, setPositionEntryRef] = useState('trade.decision');
  const [selectedPositionId, setSelectedPositionId] = useState('');
  const [snapshotAutoEnabled, setSnapshotAutoEnabled] = useState(false);
  const [snapshotPeriod, setSnapshotPeriod] = useState<'5m' | '15m' | '30m' | '1h'>('15m');
  const [exitMode, setExitMode] = useState<'manual' | 'auto'>('manual');
  const [exitConfirmCount, setExitConfirmCount] = useState('2');
  const [exitAction, setExitAction] = useState<'reduce' | 'close'>('reduce');
  const [exitReduceRatio, setExitReduceRatio] = useState('0.5');
  const [exitReason, setExitReason] = useState('factor_review');
  const [exitFactors, setExitFactors] = useState<Record<'attention' | 'liquidity' | 'flow' | 'onchain', boolean>>({
    attention: true,
    liquidity: true,
    flow: true,
    onchain: true,
  });

  useEffect(() => {
    const t = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(t);
    };
  }, []);

  useEffect(() => {
    const onVis = () => {
      try {
        setIsVisible(!document.hidden);
      } catch {
        setIsVisible(true);
      }
    };
    try {
      document.addEventListener('visibilitychange', onVis, { passive: true });
    } catch {
      void 0;
    }
    return () => {
      try {
        document.removeEventListener('visibilitychange', onVis);
      } catch {
        void 0;
      }
    };
  }, []);

  useEffect(() => {
    offsetRef.current = offset;
  }, [offset]);

  const outboxFilesQuery = useQuery({
    queryKey: ['agent', 'outbox', 'files'],
    queryFn: fetchAgentOutboxFiles,
    refetchInterval: () => (isVisible ? 30000 : false),
    refetchOnWindowFocus: false,
  });

  const web3StateQuery = useQuery({
    queryKey: ['agent', 'automation', 'web3_market_digest', 'state'],
    queryFn: fetchAgentAutomationWeb3MarketDigest,
    refetchInterval: () => (isVisible ? 10000 : false),
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 3,
    retryDelay: (attemptIndex) => Math.min(8000, 500 * 2 ** attemptIndex),
  });

  const autoTradeStateQuery = useQuery({
    queryKey: ['agent', 'automation', 'auto_trade', 'state'],
    queryFn: fetchAgentAutomationAutoTradeState,
    refetchInterval: () => (isVisible ? 10000 : false),
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 3,
    retryDelay: (attemptIndex) => Math.min(8000, 500 * 2 ** attemptIndex),
  });

  const activeTab = forcedTab === 'auto' ? 'auto' : (forcedTab === 'research' ? 'research' : tab);

  const positionsQuery = useQuery({
    queryKey: ['agent', 'automation', 'auto_trade', 'positions', isVisible],
    queryFn: fetchAutoTradePositions,
    enabled: activeTab === 'auto',
    refetchInterval: () => (activeTab === 'auto' && isVisible ? 10000 : false),
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 3,
    retryDelay: (attemptIndex) => Math.min(8000, 500 * 2 ** attemptIndex),
  });

  const canOperate = hasOperatorToken() && allowWrite;
  const autoTradeEnabled = Boolean(autoTradeStateQuery.data?.auto_trade_enabled);
  const autoTradeMode = String(autoTradeStateQuery.data?.auto_trade_mode ?? '').trim().toLowerCase();
  const autoExitEnabled = Boolean(autoTradeStateQuery.data?.auto_trade_auto_exit_enabled ?? true);
  const autoTradeCanExecute = canOperate && autoTradeEnabled && autoTradeMode === 'auto';

  const cachedWeb3State = useMemo(() => {
    if (web3StateQuery.data) return null;
    const raw = _lsGetJson(LS_KEY_STATE);
    const obj = _safeObj(raw);
    const data = _safeObj(obj?.data);
    return data;
  }, [web3StateQuery.data]);

  useEffect(() => {
    const data = web3StateQuery.data as Record<string, unknown> | undefined;
    if (!data || !Object.keys(data).length) return;
    _lsSetJson(LS_KEY_STATE, { savedAtMs: Date.now(), data });
  }, [web3StateQuery.data]);

  const outboxExists = useMemo(() => {
    const items = (outboxFilesQuery.data as { items?: { name?: string }[] } | undefined)?.items ?? [];
    return items.some((it) => String(it?.name ?? '') === outboxName);
  }, [outboxFilesQuery.data]);

  const appendRows = useCallback((incoming: OutboxRow[]) => {
    if (!incoming.length) return;
    setRows((prev) => {
      const byOffset = new Map<number, OutboxRow>();
      for (const it of prev) byOffset.set(it.offset, it);
      for (const it of incoming) {
        const off = Number((it as { offset?: unknown }).offset ?? NaN);
        if (!Number.isFinite(off)) continue;
        byOffset.set(off, { offset: off, item: (it as { item?: unknown }).item });
      }
      const merged = Array.from(byOffset.values()).sort((a, b) => a.offset - b.offset);
      return merged.slice(Math.max(0, merged.length - 800));
    });
  }, []);

  const pollOnce = useCallback(async () => {
    if (!outboxExists) return;
    try {
      const res = await fetchAgentOutboxRead({ name: outboxName, offset: offsetRef.current, limit: 80, tail: true, tail_bytes: 20000000 });
      if ((res as { reset?: unknown } | undefined)?.reset) {
        setRows([]);
        setOffset(0);
      }
      const items = Array.isArray((res as { items?: unknown }).items) ? ((res as { items: OutboxRow[] }).items) : [];
      appendRows(items);
      try {
        let best: { tsMs: number; traceId: string; digest: Digest | null } | null = null;
        for (const r of items) {
          const obj = _safeObj(r.item) as Web3MarketDigestRow | null;
          if (!obj) continue;
          if (String(obj.type ?? '') !== 'web3.market_digest') continue;
          const tsRaw = obj.ts;
          const tsNum = Number(tsRaw ?? 0);
          const tsMs = Number.isFinite(tsNum) ? (tsNum < 1e11 ? tsNum * 1000 : tsNum) : 0;
          const traceId = _toStr(obj.trace_id ?? '').trim();
          if (!tsMs || !traceId) continue;
          const dig = (_safeObj(obj.digest) as Digest | null) ?? null;
          if (!best || tsMs > best.tsMs) best = { tsMs, traceId, digest: dig };
        }
        if (best && (!persistedLatest || best.tsMs > persistedLatest.tsMs)) {
          const nextLatest: PersistedLatest = { tsMs: best.tsMs, traceId: best.traceId, digest: best.digest, savedAtMs: Date.now() };
          setPersistedLatest(nextLatest);
          _lsSetJson(LS_KEY_LATEST, nextLatest);
        }
      } catch {
        void 0;
      }
      const next = Number((res as { next_offset?: unknown }).next_offset ?? offsetRef.current);
      if (Number.isFinite(next) && next >= 0) setOffset(next);
      setPollError(null);
    } catch (e) {
      setPollError(String((e as { message?: unknown } | null | undefined)?.message ?? e));
    }
  }, [appendRows, outboxExists, persistedLatest]);

  const runMutation = useMutation({
    mutationFn: async () => await runAutomationWeb3MarketDigest({ force: true, trigger_event: 'ui' }),
    onSuccess: async () => {
      setRunError(null);
      await web3StateQuery.refetch();
      await outboxFilesQuery.refetch();
      void pollOnce();
    },
    onError: (e) => {
      setRunError(String((e as { message?: unknown } | null | undefined)?.message ?? e));
    },
  });

  useEffect(() => {
    let timer: number | null = null;
    let kick: number | null = null;
    if (outboxExists && isVisible) {
      kick = window.setTimeout(() => {
        void pollOnce();
      }, 0);
      timer = window.setInterval(() => {
        void pollOnce();
      }, 10000);
    }
    return () => {
      if (kick != null) window.clearTimeout(kick);
      if (timer != null) window.clearInterval(timer);
    };
  }, [outboxExists, isVisible, pollOnce]);

  const latestDigestItem = useMemo(() => {
    const parsed: { tsMs: number; traceId: string; row: Web3MarketDigestRow; digest: Digest | null }[] = [];
    for (const r of rows) {
      const obj = _safeObj(r.item) as Web3MarketDigestRow | null;
      if (!obj) continue;
      if (String(obj.type ?? '') !== 'web3.market_digest') continue;
      const tsRaw = obj.ts;
      const tsNum = Number(tsRaw ?? 0);
      const tsMs = Number.isFinite(tsNum) ? (tsNum < 1e11 ? tsNum * 1000 : tsNum) : 0;
      const traceId = _toStr(obj.trace_id ?? '');
      const digest = (_safeObj(obj.digest) as Digest | null) ?? null;
      parsed.push({ tsMs, traceId, row: obj, digest });
    }
    if (!parsed.length) return null;
    parsed.sort((a, b) => a.tsMs - b.tsMs);
    return parsed[parsed.length - 1] ?? null;
  }, [rows]);

  const latestFromApi = useMemo(() => {
    const data = web3StateQuery.data as { latest?: unknown } | undefined;
    const latest = _safeObj(data?.latest);
    if (!latest) return null;
    const tsNum = Number(latest.ts ?? 0);
    const tsMs = Number.isFinite(tsNum) ? (tsNum < 1e11 ? tsNum * 1000 : tsNum) : 0;
    const traceId = _toStr(latest.trace_id ?? '');
    const digest = (_safeObj(latest.digest) as Digest | null) ?? null;
    return { tsMs, traceId, row: latest as unknown as Web3MarketDigestRow, digest };
  }, [web3StateQuery.data]);

  const latestDigest = latestFromApi ?? latestDigestItem ?? persistedLatest;
  const parsedPositions = useMemo(() => {
    const items = Array.isArray(positionsQuery.data?.positions) ? positionsQuery.data?.positions : [];
    return items
      .map((it) => {
        const row = _safeObj(it);
        if (!row) return null;
        const positionId = _toStr(row.position_id ?? '').trim();
        if (!positionId) return null;
        return {
          position_id: positionId,
          chain_id: row.chain_id,
          contract_address: row.contract_address,
          symbol: row.symbol,
          entry_ts_ms: row.entry_ts_ms,
          entry_ref: row.entry_ref,
          size_token: row.size_token,
          notional_usd: row.notional_usd,
          status: row.status,
          last_snapshot_ts_ms: row.last_snapshot_ts_ms,
        } as PositionRow;
      })
      .filter((x): x is PositionRow => Boolean(x));
  }, [positionsQuery.data?.positions]);
  const openPositions = useMemo(
    () => parsedPositions.filter((x) => _toStr(x.status ?? 'open').trim().toLowerCase() === 'open'),
    [parsedPositions],
  );
  const effectiveSelectedPositionId = useMemo(() => {
    if (!openPositions.length) return '';
    if (selectedPositionId && openPositions.some((x) => x.position_id === selectedPositionId)) return selectedPositionId;
    return openPositions[0]?.position_id ?? '';
  }, [openPositions, selectedPositionId]);
  const selectedPosition = useMemo(() => openPositions.find((x) => x.position_id === effectiveSelectedPositionId) ?? null, [effectiveSelectedPositionId, openPositions]);
  const selectedFactors = useMemo(
    () => Object.entries(exitFactors).filter(([, enabled]) => enabled).map(([k]) => k),
    [exitFactors],
  );
  const selectedPositionFactorPack = useMemo(() => {
    const pos = selectedPosition;
    if (!pos) return null;
    const d = latestDigest?.digest as Digest | null | undefined;
    const dv1 = _safeObj((d as unknown as { digest_v1?: unknown } | undefined)?.digest_v1);
    const rankings = _safeObj(dv1?.rankings);
    const constraints = _safeObj(dv1?.constraints);
    const tokenInfoRows = _safeArray(dv1?.token_info).map((x) => _safeObj(x)).filter((x): x is Record<string, unknown> => Boolean(x));
    const addressRows = _safeArray(dv1?.address_insights).map((x) => _safeObj(x)).filter((x): x is Record<string, unknown> => Boolean(x));

    const symbol = _toStr(pos.symbol ?? '').trim().toUpperCase();
    const contract = _toStr(pos.contract_address ?? '').trim().toLowerCase();
    const trendSyms = new Set(_safeArray(rankings?.trending).map((x) => _toStr(_safeObj(x)?.symbol ?? '').trim().toUpperCase()).filter((x) => x));
    const searchSyms = new Set(_safeArray(rankings?.top_search).map((x) => _toStr(_safeObj(x)?.symbol ?? '').trim().toUpperCase()).filter((x) => x));
    const flowSyms = new Set(
      _safeArray(rankings?.smart_money_inflow)
        .map((x) => {
          const obj = _safeObj(x);
          const sym = _toStr(obj?.symbol ?? '').trim().toUpperCase();
          if (sym) return sym;
          const tokenName = _toStr(obj?.tokenName ?? '').trim();
          return tokenName ? tokenName.split('/', 1)[0].trim().toUpperCase() : '';
        })
        .filter((x) => x),
    );
    const inTrending = trendSyms.has(symbol);
    const inSearch = searchSyms.has(symbol);
    const inFlow = flowSyms.has(symbol);
    const attentionScore = _clamp01((inTrending ? 0.6 : 0) + (inSearch ? 0.4 : 0));
    const flowScore = _clamp01(inFlow ? 0.85 : 0.25);

    const tok = tokenInfoRows.find((x) => _toStr(x.contractAddress ?? '').trim().toLowerCase() === contract)
      ?? tokenInfoRows.find((x) => _toStr(x.symbol ?? '').trim().toUpperCase() === symbol)
      ?? null;
    const liq = _toNum(tok?.liquidity_usd ?? tok?.liquidity);
    const vol = _toNum(tok?.volume24h_usd ?? tok?.volume24h);
    const minLiq = Math.max(1, Number(constraints?.min_liquidity_usd ?? 1));
    const minVol = Math.max(1, Number(constraints?.min_volume24h_usd ?? 1));
    const liqScore = liq == null ? 0.2 : _clamp01(Math.min(1.2, liq / minLiq) * 0.6 + 0.2);
    const volScore = vol == null ? 0.2 : _clamp01(Math.min(1.2, vol / minVol) * 0.6 + 0.2);
    const liquidityScore = _clamp01((liqScore + volScore) / 2);

    let deltaUsd = 0;
    for (const ai of addressRows) {
      for (const dlt of _safeArray(ai.deltas)) {
        const dltObj = _safeObj(dlt);
        if (!dltObj) continue;
        const ca = _toStr(dltObj.contractAddress ?? dltObj.ca ?? '').trim().toLowerCase();
        if (!ca || ca !== contract) continue;
        deltaUsd += _toNum(dltObj.delta_value_usd_est) ?? 0;
      }
    }
    const onchainScore = deltaUsd > 0 ? _clamp01(0.55 + Math.min(0.35, Math.abs(deltaUsd) / 2_000_000)) : (deltaUsd < 0 ? 0.15 : 0.4);
    const valueScore = _clamp01(attentionScore * 0.26 + liquidityScore * 0.34 + flowScore * 0.24 + onchainScore * 0.16);
    const riskScore = _clamp01((1 - attentionScore) * 0.18 + (1 - liquidityScore) * 0.36 + (1 - flowScore) * 0.24 + (1 - onchainScore) * 0.22);

    return {
      attention: {
        score: attentionScore,
        trending_hit: inTrending,
        top_search_hit: inSearch,
      },
      liquidity: {
        score: liquidityScore,
        liquidity_usd: liq,
        volume24h_usd: vol,
        min_liquidity_usd: minLiq,
        min_volume24h_usd: minVol,
      },
      flow: {
        score: flowScore,
        smart_money_inflow_hit: inFlow,
      },
      onchain: {
        score: onchainScore,
        address_delta_usd_est: Number(deltaUsd.toFixed(2)),
      },
      risk_score: Number(riskScore.toFixed(4)),
      value_score: Number(valueScore.toFixed(4)),
    };
  }, [latestDigest?.digest, selectedPosition]);
  const snapshotPeriodMs = useMemo(() => {
    if (snapshotPeriod === '5m') return 5 * 60 * 1000;
    if (snapshotPeriod === '30m') return 30 * 60 * 1000;
    if (snapshotPeriod === '1h') return 60 * 60 * 1000;
    return 15 * 60 * 1000;
  }, [snapshotPeriod]);
  const decisionWindowSec = useMemo(() => {
    if (decisionWindow === '1h') return 3600;
    if (decisionWindow === '24h') return 24 * 3600;
    if (decisionWindow === 'custom') {
      const n = Number(decisionWindowCustomMin);
      const m = Number.isFinite(n) ? Math.max(5, Math.min(7 * 24 * 60, Math.round(n))) : 180;
      return m * 60;
    }
    return 6 * 3600;
  }, [decisionWindow, decisionWindowCustomMin]);

  const decisionItems = useMemo(() => {
    const windowMs = decisionWindowSec * 1000;
    const items: { tsMs: number; traceId: string; chainId: string; symbol: string; contractAddress: string; liquidity?: unknown; volume24h?: unknown }[] = [];

    const collectFromDigest = (d: Digest | null, tsMs: number, traceId: string) => {
      if (!d) return;
      const chainDefault = _toStr(d?.config?.chain_id ?? d?.config?.chainId ?? '').trim() || '56';
      const pushCandidate = (raw: Record<string, unknown>, chainHint?: string) => {
        const sym = _toStr(raw.symbol ?? raw.token ?? raw.ticker ?? raw.tokenSymbol ?? '').trim().toUpperCase();
        const ca = _toStr(raw.contractAddress ?? raw.contract_address ?? raw.ca ?? raw.address ?? '').trim();
        const chainId = _toStr(raw.chainId ?? raw.chain_id ?? raw.binanceChainId ?? chainHint ?? chainDefault).trim() || chainDefault;
        if (!sym || !ca) return;
        items.push({
          tsMs,
          traceId,
          chainId,
          symbol: sym,
          contractAddress: ca,
          liquidity: raw.liquidity_usd ?? raw.liquidity ?? raw.liquidityUsd,
          volume24h: raw.volume24h_usd ?? raw.volume24h ?? raw.volume24hUsd ?? raw.volume,
        });
      };

      const watchlist = _safeArray(d?.watchlist).map((x) => _safeObj(x)).filter((x): x is Record<string, unknown> => Boolean(x));
      for (const it of watchlist.slice(0, 80)) pushCandidate(it);

      const llm = _safeObj(d?.llm);
      const llmWatch = _safeArray(llm?.watchlist).map((x) => _safeObj(x)).filter((x): x is Record<string, unknown> => Boolean(x));
      for (const it of llmWatch.slice(0, 80)) pushCandidate(it);

      const dv1 = _safeObj((d as unknown as { digest_v1?: unknown } | undefined)?.digest_v1);
      const dv1Watch = _safeArray(dv1?.watchlist).map((x) => _safeObj(x)).filter((x): x is Record<string, unknown> => Boolean(x));
      for (const it of dv1Watch.slice(0, 80)) pushCandidate(it);

      const rankings = _safeObj(d?.rankings);
      const ranks = _safeObj(rankings?.ranks);
      for (const k of ['trending', 'top_search', 'smart_money_inflow']) {
        const arr = _safeArray(ranks?.[k as keyof typeof ranks]).map((x) => _safeObj(x)).filter((x): x is Record<string, unknown> => Boolean(x));
        for (const it of arr.slice(0, 80)) {
          const tokenName = _toStr(it.tokenName ?? '').trim();
          if (k === 'smart_money_inflow' && tokenName && !_toStr(it.symbol ?? '').trim()) {
            const guess = tokenName.split('/', 1)[0]?.trim().toUpperCase() || '';
            pushCandidate({ ...it, symbol: guess, contractAddress: it.ca ?? it.contractAddress }, chainDefault);
          } else {
            pushCandidate(it, chainDefault);
          }
        }
      }

      const factors = _safeObj(d?.factors);
      const qti = _safeObj(factors?.query_token_info);
      const toks = _safeArray(qti?.tokens).map((x) => _safeObj(x)).filter((x): x is Record<string, unknown> => Boolean(x));
      for (const it of toks.slice(0, 120)) {
        const tokenObj = _safeObj(it.token);
        const metaObj = _safeObj(it.metadata);
        const marketObj = _safeObj(it.market);
        pushCandidate({
          symbol: tokenObj?.symbol ?? metaObj?.symbol,
          contractAddress: tokenObj?.contractAddress ?? metaObj?.contractAddress,
          chainId: tokenObj?.chainId ?? metaObj?.chainId ?? chainDefault,
          liquidity: marketObj?.liquidity,
          volume24h: marketObj?.volume24h,
        }, chainDefault);
      }
    };

    let inWindowRows = 0;
    for (const r of rows) {
      const obj = _safeObj(r.item) as Web3MarketDigestRow | null;
      if (!obj || String(obj.type ?? '') !== 'web3.market_digest') continue;
      const tsRaw = obj.ts;
      const tsNum = Number(tsRaw ?? 0);
      const tsMs = Number.isFinite(tsNum) ? (tsNum < 1e11 ? tsNum * 1000 : tsNum) : 0;
      if (!tsMs || nowMs - tsMs > windowMs) continue;
      inWindowRows += 1;
      const traceId = _toStr(obj.trace_id ?? '').trim();
      const d = (_safeObj(obj.digest) as Digest | null) ?? null;
      collectFromDigest(d, tsMs, traceId);
    }

    if (!items.length && inWindowRows === 0 && latestDigest && latestDigest.digest) {
      const tsMs = Number((latestDigest as { tsMs?: unknown }).tsMs ?? 0) || nowMs;
      const traceId = _toStr((latestDigest as { traceId?: unknown }).traceId ?? '').trim();
      collectFromDigest((latestDigest.digest as Digest | null) ?? null, tsMs, traceId);
    }

    items.sort((a, b) => b.tsMs - a.tsMs);
    const seen = new Set<string>();
    const dedup: typeof items = [];
    for (const it of items) {
      const key = `${it.chainId}:${it.contractAddress.toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      dedup.push(it);
      if (dedup.length >= 80) break;
    }
    return dedup;
  }, [decisionWindowSec, latestDigest, nowMs, rows]);

  const recommendationThreshold = 0.6;

  const decisionsQuery = useQuery({
    queryKey: ['agent', 'automation', 'auto_trade', 'decisions', decisionWindowSec, isVisible],
    queryFn: () => fetchAgentAutomationAutoTradeDecisions({ window_sec: decisionWindowSec }),
    enabled: isVisible,
    refetchInterval: () => (isVisible ? 10000 : false),
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 2,
    retryDelay: (attemptIndex) => Math.min(4000, 400 * 2 ** attemptIndex),
  });

  const auditedDecisionItems = useMemo(() => {
    const items = Array.isArray(decisionsQuery.data?.items) ? decisionsQuery.data?.items : [];
    const parsed: {
      tsMs: number;
      traceId: string;
      chainId: string;
      symbol: string;
      contractAddress: string;
      liquidity?: unknown;
      volume24h?: unknown;
      scoring?: Record<string, unknown>;
    }[] = [];
    for (const it of items) {
      const row = _safeObj(it);
      if (!row) continue;
      const cand = _safeObj(row.candidate);
      const scoreObj = _safeObj(row.scoring);
      const tsNum = Number(row.ts ?? 0);
      const tsMs = Number.isFinite(tsNum) ? (tsNum < 1e11 ? tsNum * 1000 : tsNum) : 0;
      const chainId = _toStr(row.chain_id ?? '').trim() || '56';
      const symbol = _toStr(cand?.symbol ?? '').trim().toUpperCase();
      const contractAddress = _toStr(cand?.contractAddress ?? '').trim();
      if (!symbol || !contractAddress) continue;
      const b = _safeObj(scoreObj?.breakdown);
      parsed.push({
        tsMs,
        traceId: _toStr(row.trace_id ?? '').trim(),
        chainId,
        symbol,
        contractAddress,
        liquidity: b?.liquidity_usd,
        volume24h: b?.volume24h_usd,
        scoring: scoreObj ?? undefined,
      });
    }
    parsed.sort((a, b) => b.tsMs - a.tsMs);
    const dedup: typeof parsed = [];
    const seen = new Set<string>();
    for (const it of parsed) {
      const key = `${it.chainId}:${it.contractAddress.toLowerCase()}`;
      if (seen.has(key)) continue;
      seen.add(key);
      dedup.push(it);
      if (dedup.length >= 80) break;
    }
    return dedup;
  }, [decisionsQuery.data?.items]);

  const decisionItemsForUi = auditedDecisionItems.length ? auditedDecisionItems : decisionItems;
  const decisionCollapsed = decisionCollapsedPref == null ? decisionItemsForUi.length > 20 : decisionCollapsedPref;

  const recommendationRows = useMemo(() => {
    const d = latestDigest?.digest as Digest | null | undefined;
    const dv1 = _safeObj((d as unknown as { digest_v1?: unknown } | undefined)?.digest_v1);
    const dv1Rankings = _safeObj(dv1?.rankings);
    const dv1Constraints = _safeObj(dv1?.constraints);
    const dv1Candidates = _safeObj(dv1?.candidates);
    const dv1AddressInsights = _safeArray(dv1?.address_insights);
    const dv1RiskAlerts = _safeArray(dv1?.risk_alerts);

    const minLiq = Number(dv1Constraints?.min_liquidity_usd ?? 0);
    const minVol = Number(dv1Constraints?.min_volume24h_usd ?? 0);

    const attentionTrending = new Set(
      _safeArray(dv1Rankings?.trending)
        .map((x) => _toStr(_safeObj(x)?.symbol ?? '').trim().toUpperCase())
        .filter((x) => x),
    );
    const attentionSearch = new Set(
      _safeArray(dv1Rankings?.top_search)
        .map((x) => _toStr(_safeObj(x)?.symbol ?? '').trim().toUpperCase())
        .filter((x) => x),
    );
    const flowSymbols = new Set(
      _safeArray(dv1Rankings?.smart_money_inflow)
        .map((x) => {
          const obj = _safeObj(x);
          const direct = _toStr(obj?.symbol ?? '').trim().toUpperCase();
          if (direct) return direct;
          const tokenName = _toStr(obj?.tokenName ?? '').trim().toUpperCase();
          if (!tokenName) return '';
          return tokenName.includes('/') ? tokenName.split('/', 1)[0].trim() : tokenName;
        })
        .filter((x) => x),
    );

    const c2MapByContract = new Map<string, { reason: string; risk: string; invalidations: string[] }>();
    const c2MapBySymbol = new Map<string, { reason: string; risk: string; invalidations: string[] }>();
    for (const x of _safeArray(dv1Candidates?.C2)) {
      const obj = _safeObj(x);
      if (!obj) continue;
      const reason = _toStr(obj.reason ?? '').trim();
      const risk = _toStr(obj.risk ?? '').trim();
      const invalidations = _safeArray(obj.invalidations).map((v) => _toStr(v).trim()).filter((v) => v).slice(0, 3);
      const ca = _toStr(obj.contractAddress ?? '').trim().toLowerCase();
      const sym = _toStr(obj.symbol ?? '').trim().toUpperCase();
      const payload = { reason, risk, invalidations };
      if (ca) c2MapByContract.set(ca, payload);
      if (sym) c2MapBySymbol.set(sym, payload);
    }

    const deltaByContract = new Map<string, number>();
    for (const x of dv1AddressInsights) {
      const row = _safeObj(x);
      if (!row) continue;
      for (const dlt of _safeArray(row.deltas)) {
        const dltObj = _safeObj(dlt);
        if (!dltObj) continue;
        const ca = _toStr(dltObj.contractAddress ?? dltObj.ca ?? '').trim().toLowerCase();
        const delta = _toNum(dltObj.delta_value_usd_est);
        if (!ca || delta == null) continue;
        deltaByContract.set(ca, (deltaByContract.get(ca) ?? 0) + delta);
      }
    }

    const globalRiskPenalty = (() => {
      let p = 0;
      for (const x of dv1RiskAlerts) {
        const row = _safeObj(x);
        if (!row) continue;
        const t = _toStr(row.type ?? '').toLowerCase();
        const sev = _toStr(row.severity ?? '').toLowerCase();
        if (t.includes('thin_liquidity') && sev === 'high') p += 0.06;
        if (t.includes('manipulation')) p += 0.04;
        if (t.includes('concentration')) p += 0.03;
      }
      return Math.min(0.15, p);
    })();

    const rows = decisionItemsForUi.map((it) => {
      const symbol = _toStr(it.symbol).trim().toUpperCase();
      const contract = _toStr(it.contractAddress).trim();
      const contractKey = contract.toLowerCase();
      const auditedScoring = _safeObj((it as { scoring?: unknown }).scoring);
      const auditedProb = _toNum(auditedScoring?.calibrated_prob);
      const auditedCi = _safeObj(auditedScoring?.confidence_interval);
      const auditedLow = _toNum(auditedCi?.low);
      const auditedHigh = _toNum(auditedCi?.high);
      const auditedThresholds = _safeObj(auditedScoring?.thresholds);
      const auditedProbMin = _toNum(auditedThresholds?.prob_min_buy);
      const auditedRecommend = Boolean(auditedScoring?.recommend_buy);

      const attTags: string[] = [];
      let attentionScore = 0;
      if (attentionTrending.has(symbol)) {
        attTags.push('trending');
        attentionScore += 0.18;
      }
      if (attentionSearch.has(symbol)) {
        attTags.push('top_search');
        attentionScore += 0.12;
      }

      const liq = _toNum(it.liquidity);
      const vol = _toNum(it.volume24h);
      let liquidityScore = 0;
      if (liq != null && liq > 0) {
        if (minLiq > 0) {
          if (liq >= minLiq) liquidityScore += 0.10;
          if (liq >= minLiq * 2) liquidityScore += 0.06;
        } else {
          liquidityScore += 0.08;
        }
      }
      if (vol != null && vol > 0) {
        if (minVol > 0) {
          if (vol >= minVol) liquidityScore += 0.10;
          if (vol >= minVol * 2) liquidityScore += 0.06;
        } else {
          liquidityScore += 0.08;
        }
      }

      const flowHit = flowSymbols.has(symbol);
      const flowScore = flowHit ? 0.24 : 0.03;

      const deltaUsd = deltaByContract.get(contractKey);
      let onchainScore = 0.05;
      let onchainView = '观察地址未见显著仓位变化';
      if (typeof deltaUsd === 'number') {
        if (deltaUsd > 0) {
          onchainScore = 0.16;
          onchainView = `观察地址净增持 ${_fmtUsd(deltaUsd)}`;
        } else if (deltaUsd < 0) {
          onchainScore = -0.07;
          onchainView = `观察地址净减持 ${_fmtUsd(Math.abs(deltaUsd))}`;
        } else {
          onchainScore = 0.04;
          onchainView = '观察地址仓位基本持平';
        }
      }

      const c2Meta = c2MapByContract.get(contractKey) ?? c2MapBySymbol.get(symbol) ?? { reason: '', risk: '', invalidations: [] };
      let riskPenalty = globalRiskPenalty;
      const riskLower = c2Meta.risk.toLowerCase();
      if (riskLower.includes('thin')) riskPenalty += 0.08;
      if (riskLower.includes('manipulation')) riskPenalty += 0.08;
      if (riskLower.includes('concentration')) riskPenalty += 0.06;
      if (minLiq > 0 && liq != null && liq < minLiq) riskPenalty += 0.08;
      if (minVol > 0 && vol != null && vol < minVol) riskPenalty += 0.08;
      riskPenalty = Math.min(0.4, riskPenalty);

      const raw = 0.20 + attentionScore + liquidityScore + flowScore + onchainScore - riskPenalty;
      const score = Math.min(0.99, Math.max(0.01, raw));
      const calibratedScore = auditedProb == null ? score : Math.min(0.99, Math.max(0.01, auditedProb));
      const threshold = auditedProbMin == null ? recommendationThreshold : Math.min(0.95, Math.max(0.05, auditedProbMin));
      const recommend = auditedScoring ? auditedRecommend : false;

      const attentionView = attTags.length ? `注意力命中 ${attTags.join('+')}` : '注意力未命中核心榜单';
      const liquidityView = `流动性 ${_fmtUsd(liq)} / 成交量 ${_fmtUsd(vol)}`;
      const flowView = flowHit ? '资金流命中 smart_money_inflow' : '资金流未命中 smart_money_inflow';
      const reason = `${attentionView}；${liquidityView}；${flowView}；${onchainView}${auditedScoring ? '' : '；等待 trade.decision 校准信号'}`;

      return {
        ...it,
        score: calibratedScore,
        scorePct: Math.round(calibratedScore * 100),
        confidenceLow: auditedLow,
        confidenceHigh: auditedHigh,
        recommend,
        reason: c2Meta.reason ? `${reason}；补充：${c2Meta.reason}` : reason,
        risk: c2Meta.risk,
        invalidations: c2Meta.invalidations,
        threshold,
      };
    });

    rows.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      const liqA = _toNum(a.liquidity) ?? 0;
      const liqB = _toNum(b.liquidity) ?? 0;
      if (liqB !== liqA) return liqB - liqA;
      const volA = _toNum(a.volume24h) ?? 0;
      const volB = _toNum(b.volume24h) ?? 0;
      return volB - volA;
    });
    return rows.slice(0, 5);
  }, [decisionItemsForUi, latestDigest]);

  const ordersTailQuery = useQuery({
    queryKey: ['agent', 'outbox', 'read', { name: 'orders.jsonl', tab: activeTab }],
    queryFn: () => fetchAgentOutboxRead({ name: 'orders.jsonl', tail: true, limit: 80, tail_bytes: 2_000_000, compact: true }),
    enabled: activeTab === 'auto' && isVisible,
    refetchInterval: () => (activeTab === 'auto' && isVisible ? 10000 : false),
    refetchOnWindowFocus: false,
    retry: (failureCount) => failureCount < 2,
    retryDelay: (attemptIndex) => Math.min(4000, 400 * 2 ** attemptIndex),
  });

  useEffect(() => {
    if (!latestFromApi?.tsMs || !latestFromApi.traceId) return;
    _lsSetJson(LS_KEY_LATEST, { tsMs: latestFromApi.tsMs, traceId: latestFromApi.traceId, digest: latestFromApi.digest, savedAtMs: Date.now() });
  }, [latestFromApi?.tsMs, latestFromApi?.traceId, latestFromApi?.digest]);

  const precheckMutation = useMutation({
    mutationFn: async () => {
      const ca = tradeContractAddress.trim();
      if (!ca) throw new Error('missing contract address');
      return await runAutoTradePrecheck({ chain_id: tradeChainId.trim() || '56', contract_address: ca, timeout_sec: 10 });
    },
    onSuccess: (res) => {
      setPrecheckSnap((res as unknown as Record<string, unknown>) || null);
    },
  });

  const intentMutation = useMutation({
    mutationFn: async () => {
      const ca = tradeContractAddress.trim();
      if (!ca) throw new Error('missing contract address');
      const notional = Number(tradeNotionalUsd);
      const slip = Number(tradeSlippageBps);
      const pretrade = _safeObj(precheckSnap);
      const gate = _safeObj(pretrade?.gate);
      const pretrade_checks: Record<string, unknown> = {
        gate_decision: _toStr(gate?.decision ?? ''),
        gate_reason: _toStr(gate?.reason ?? ''),
      };
      return await createAutoTradeOrderIntent({
        chain_id: tradeChainId.trim() || '56',
        contract_address: ca,
        symbol: tradeSymbol.trim() || undefined,
        side: tradeSide,
        notional_usd: Number.isFinite(notional) ? notional : undefined,
        max_slippage_bps: Number.isFinite(slip) ? slip : undefined,
        pretrade_checks,
      });
    },
  });

  const positionOpenMutation = useMutation({
    mutationFn: async () => {
      const ca = tradeContractAddress.trim();
      if (!ca) throw new Error('missing contract address');
      const notional = Number(tradeNotionalUsd);
      const sizeToken = Number(positionSizeToken);
      return await createAutoTradePositionOpen({
        chain_id: tradeChainId.trim() || '56',
        contract_address: ca,
        symbol: tradeSymbol.trim() || undefined,
        entry_ref: positionEntryRef.trim() || undefined,
        notional_usd: Number.isFinite(notional) ? notional : undefined,
        size_token: Number.isFinite(sizeToken) ? sizeToken : undefined,
      });
    },
    onSuccess: async (res) => {
      const pid = _toStr((res as { position_id?: unknown } | null | undefined)?.position_id ?? '').trim();
      if (pid) setSelectedPositionId(pid);
      await positionsQuery.refetch();
    },
  });

  const snapshotMutation = useMutation({
    mutationFn: async () => {
      const pos = selectedPosition;
      if (!pos) throw new Error('missing_position');
      return await createAutoTradePositionSnapshot({
        position_id: pos.position_id,
        chain_id: _toStr(pos.chain_id).trim() || '56',
        contract_address: _toStr(pos.contract_address).trim(),
        refresh_period: snapshotPeriod,
        factors: selectedPositionFactorPack ? {
          attention: selectedPositionFactorPack.attention,
          liquidity: selectedPositionFactorPack.liquidity,
          flow: selectedPositionFactorPack.flow,
          onchain: selectedPositionFactorPack.onchain,
          risk_score: selectedPositionFactorPack.risk_score,
          value_score: selectedPositionFactorPack.value_score,
        } : undefined,
      });
    },
    onSuccess: async () => {
      await positionsQuery.refetch();
    },
  });

  const exitIntentMutation = useMutation({
    mutationFn: async () => {
      const pos = selectedPosition;
      if (!pos) throw new Error('missing_position');
      const confirmCount = Number(exitConfirmCount);
      const rr = Number(exitReduceRatio);
      const selected = selectedFactors.length ? selectedFactors : ['attention', 'liquidity', 'flow', 'onchain'];
      const risk = selectedPositionFactorPack?.risk_score;
      const value = selectedPositionFactorPack?.value_score;
      return await createAutoTradeExitIntent({
        position_id: pos.position_id,
        mode: exitMode,
        reason: exitReason.trim() || 'factor_review',
        selected_factors: selected,
        confirm_count: Number.isFinite(confirmCount) ? Math.max(0, Math.min(20, Math.round(confirmCount))) : 2,
        risk_score: typeof risk === 'number' ? risk : undefined,
        value_score: typeof value === 'number' ? value : undefined,
        action: exitAction,
        reduce_ratio: Number.isFinite(rr) ? Math.max(0, Math.min(1, rr)) : undefined,
      });
    },
  });

  const exitReviewMutation = useMutation({
    mutationFn: async () => await runAutoTradeExitReview({ reason: 'ui' }),
    onSuccess: async () => {
      await positionsQuery.refetch();
    },
  });

  useEffect(() => {
    if (!snapshotAutoEnabled) return;
    if (!effectiveSelectedPositionId) return;
    if (!canOperate) return;
    let stopped = false;
    const runNow = async () => {
      if (stopped || snapshotMutation.isPending) return;
      try {
        await snapshotMutation.mutateAsync();
      } catch {
        void 0;
      }
    };
    void runNow();
    const t = window.setInterval(() => {
      void runNow();
    }, snapshotPeriodMs);
    return () => {
      stopped = true;
      window.clearInterval(t);
    };
  }, [canOperate, effectiveSelectedPositionId, snapshotAutoEnabled, snapshotMutation, snapshotPeriodMs]);

  const killSwitchMutation = useMutation({
    mutationFn: async () => await triggerAutoTradeKillSwitch({ reason: 'ui' }),
    onSuccess: async () => {
      await autoTradeStateQuery.refetch();
    },
  });
  const autoTradeToggleMutation = useMutation({
    mutationFn: async (payload: { enabled: boolean; password?: string }) =>
      await setAutomationConfig({
        auto_trade_enabled: payload.enabled,
        auto_trade_enable_password: payload.password,
        confirm_live: true,
      }),
    onSuccess: async () => {
      await autoTradeStateQuery.refetch();
      setAutoTradeEnablePassword('');
    },
  });
  const autoTradeModeMutation = useMutation({
    mutationFn: async (mode: string) =>
      await setAutomationConfig({
        auto_trade_mode: mode,
        confirm_live: true,
      }),
    onSuccess: async () => {
      await autoTradeStateQuery.refetch();
    },
  });
  const autoTradeOpenInProdMutation = useMutation({
    mutationFn: async (enabled: boolean) =>
      await setAutomationConfig({
        auto_trade_binance_spot_open_in_prod: enabled,
        auto_trade_enable_password: enabled ? autoTradeEnablePassword : undefined,
        confirm_live: true,
      }),
    onSuccess: async () => {
      await autoTradeStateQuery.refetch();
      setAutoTradeEnablePassword('');
    },
  });
  const autoTradeAutoExitMutation = useMutation({
    mutationFn: async (enabled: boolean) =>
      await setAutomationConfig({
        auto_trade_auto_exit_enabled: enabled,
        confirm_live: true,
      }),
    onSuccess: async () => {
      await autoTradeStateQuery.refetch();
    },
  });

  const loop = (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span className="truncate">闭环：注意力—流动性—资金流—链上地址行为</span>
          <Badge variant="outline">Web3 Market Digest</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <div className="rounded border bg-white px-3 py-2">
            <div className="text-xs text-slate-600">Attention</div>
            <div className="mt-1">Trending / Top search</div>
          </div>
          <div className="rounded border bg-white px-3 py-2">
            <div className="text-xs text-slate-600">Liquidity</div>
            <div className="mt-1">liquidity / vol24h</div>
          </div>
          <div className="rounded border bg-white px-3 py-2">
            <div className="text-xs text-slate-600">Flows</div>
            <div className="mt-1">Smart-money inflow</div>
          </div>
          <div className="rounded border bg-white px-3 py-2">
            <div className="text-xs text-slate-600">On-chain</div>
            <div className="mt-1">Watch addresses</div>
          </div>
        </div>
        <div className="text-xs text-slate-600">
          目标：用事实证据 + 风险约束替代“预测/喊单”，输出可复用的市场情报与 thread 文案。
        </div>
      </CardContent>
    </Card>
  );

  const live = (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span className="truncate">最新一次输出</span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => void pollOnce()} disabled={!outboxExists}>刷新 outbox</Button>
            <Button size="sm" variant="outline" onClick={() => void web3StateQuery.refetch()} disabled={web3StateQuery.isFetching}>刷新状态</Button>
            <Button size="sm" onClick={() => runMutation.mutate()} disabled={!canOperate || runMutation.isPending}>运行一次</Button>
            {!latestDigest ? <Badge variant="outline">no_data</Badge> : <Badge variant="secondary">{_fmtAgo(nowMs, latestDigest.tsMs)}</Badge>}
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {runError ? <div className="text-red-700">运行失败：{runError}</div> : null}
        {(() => {
          const st = ((web3StateQuery.data as { state?: unknown; hold_sec?: unknown; latest_age_sec?: unknown } | undefined) ?? (cachedWeb3State as { state?: unknown; hold_sec?: unknown; latest_age_sec?: unknown } | undefined) ?? {});
          if (web3StateQuery.error && !cachedWeb3State) {
            return <div className="text-red-700">状态接口失败：{String((web3StateQuery.error as { message?: unknown } | null | undefined)?.message ?? 'unknown_error')}</div>;
          }
          if (!st || !Object.keys(st).length) {
            return <div className="text-slate-600">状态：-</div>;
          }
          const cached = Boolean(!web3StateQuery.data && cachedWeb3State);
            const hold = Number(st.hold_sec ?? NaN);
            const age = Number(st.latest_age_sec ?? NaN);
            const stateObj = _safeObj(st.state);
            const lastRun = Number(stateObj?.last_run_ms ?? NaN);
            const lastTrace = _toStr(stateObj?.last_trace_id ?? '').trim();
            const lastPublish = _safeObj(stateObj?.last_publish);
            const lastPublishReason = _toStr(lastPublish?.reason ?? '').trim();
            const lastPublishOk = Boolean(lastPublish?.ok);
            return (
              <div className="grid grid-cols-1 md:grid-cols-4 gap-2 text-xs">
                <div className="rounded border bg-white px-2 py-2">
                  <div className="text-slate-600">latest_age{cached ? ' (cached)' : ''}</div>
                  <div className="truncate">{Number.isFinite(age) ? `${age.toFixed(0)}s` : '-'}</div>
                </div>
                <div className="rounded border bg-white px-2 py-2">
                  <div className="text-slate-600">hold_sec</div>
                  <div className="truncate">{Number.isFinite(hold) ? String(Math.max(0, Math.floor(hold))) : '-'}</div>
                </div>
                <div className="rounded border bg-white px-2 py-2">
                  <div className="text-slate-600">last_run</div>
                  <div className="truncate">{Number.isFinite(lastRun) && lastRun > 0 ? _fmtAgo(nowMs, (lastRun < 1e11 ? lastRun * 1000 : lastRun)) : '-'}</div>
                </div>
                <div className="rounded border bg-white px-2 py-2">
                  <div className="text-slate-600">publish</div>
                  <div className="truncate">
                    <Badge variant={lastPublishOk ? 'secondary' : 'outline'}>{lastPublishOk ? 'ok' : (lastPublishReason || '-')}</Badge>
                    {lastTrace ? <span className="ml-2 text-slate-600">{lastTrace.slice(0, 10)}…</span> : null}
                  </div>
                </div>
              </div>
            );
        })()}
        {!outboxExists ? (
          <div className="text-slate-600">未发现 web3_digest.jsonl（/agent/outbox/files）。</div>
        ) : pollError ? (
          <div className="text-red-700">读取 outbox 失败：{pollError}</div>
        ) : !latestDigest ? (
          <div className="text-slate-600">尚未发现 type=web3.market_digest 的产物。</div>
        ) : (
          (() => {
            const d = latestDigest.digest;
            const top = d?.top ?? {};
            const w = _safeArray(d?.watchlist);
            const tweets = _safeArray(d?.tweets).map((x) => _toStr(x)).filter((x) => x.trim());
            const llm = _safeObj(d?.llm);
            const llmOk = llm ? Boolean(llm.ok) : false;
            const llmSummary = llm ? _toStr(llm.summary ?? '') : '';
            const llmActions = _safeArray(llm?.actions).map((x) => _clip(_toStr(x), 160)).filter((x) => x.trim()).slice(0, 8);
            const llmRisks = _safeArray(llm?.risk_alerts).map((x) => _clip(_toStr(x), 160)).filter((x) => x.trim()).slice(0, 8);
            const regime = _toStr(d?.regime_guess ?? d?.attention_state ?? '').trim() || '-';
            const attention = _toStr(d?.attention_state ?? '').trim() || '-';
            const flows = _toStr(d?.flow_state ?? '').trim() || '-';
            const chainId = _toStr(d?.config?.chain_id ?? d?.config?.chainId ?? '').trim() || '-';
            const dv1 = _safeObj((d as unknown as { digest_v1?: unknown } | undefined)?.digest_v1);
            const dv1Snap = _safeObj(dv1?.snapshot);
            const dv1Constraints = _safeObj(dv1?.constraints);
            const dv1Thread = _safeObj(dv1?.thread);
            const dv1RiskAlerts = _safeArray(dv1?.risk_alerts).map((x) => _toStr(x)).filter((x) => x.trim()).slice(0, 8);
            const dv1Tweets = _uniqStrings(_safeArray(dv1Thread?.tweets).map((x) => _toStr(x))).slice(0, 8);

            const trending = _safeArray(top.trending).map(_toStr).filter((x) => x.trim()).slice(0, 3);
            const topSearch = _safeArray(top.top_search).map(_toStr).filter((x) => x.trim()).slice(0, 3);
            const inflow = _safeArray(top.smart_money_inflow).map(_toStr).filter((x) => x.trim()).slice(0, 3);

            const factors = _safeObj(d?.factors);
            const cmr = _safeObj(factors?.crypto_market_rank);
            const attFac = _safeObj(cmr?.attention_factors);
            const flowFac = _safeObj(cmr?.flow_factors);
            const traderFac = _safeObj(cmr?.top_trader_factors);
            const seenTokens = _safeArray(attFac?.seen_symbols).map(_toStr).filter((x) => x.trim()).slice(0, 12);
            const boughtTokens = _safeArray(flowFac?.bought_symbols).map(_toStr).filter((x) => x.trim()).slice(0, 12);
            const topTraderAddrs = _safeArray(traderFac?.top_trader_addresses).map(_toStr).filter((x) => x.trim()).slice(0, 8);
            const outputFocus = _toStr(cmr?.output_focus ?? '').trim();

            return (
              <div className="space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
                  <div className="rounded border bg-white px-2 py-2">
                    <div className="text-slate-600">regime</div>
                    <div className="truncate">{regime}</div>
                  </div>
                  <div className="rounded border bg-white px-2 py-2">
                    <div className="text-slate-600">attention / flows</div>
                    <div className="truncate">{attention} / {flows}</div>
                  </div>
                  <div className="rounded border bg-white px-2 py-2">
                    <div className="text-slate-600">chain</div>
                    <div className="truncate">{chainId}</div>
                  </div>
                </div>

                {!dv1 ? null : (
                  <div className="rounded border bg-white px-3 py-2">
                    <div className="text-xs text-slate-600 mb-2">web3_market_digest_v1</div>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                      <div className="rounded border bg-slate-50 px-3 py-2">
                        <div className="text-slate-600 mb-1">snapshot</div>
                        <div className="text-slate-700 whitespace-pre-wrap break-words">
                          {[
                            `regime=${_toStr(dv1Snap?.regime ?? '-')}`,
                            `attention=${_toStr(dv1Snap?.attention_state ?? '-')}`,
                            `flow=${_toStr(dv1Snap?.flow_state ?? '-')}`,
                          ].join(' · ')}
                        </div>
                        {_toStr(dv1Snap?.notes ?? '').trim() ? <div className="mt-1 text-slate-600 whitespace-pre-wrap break-words">{_toStr(dv1Snap?.notes ?? '')}</div> : null}
                      </div>
                      <div className="rounded border bg-slate-50 px-3 py-2">
                        <div className="text-slate-600 mb-1">constraints</div>
                        <div className="text-slate-700 whitespace-pre-wrap break-words">
                          {[
                            `min_liq=${_fmtUsd(dv1Constraints?.min_liquidity_usd)}`,
                            `min_vol=${_fmtUsd(dv1Constraints?.min_volume24h_usd)}`,
                            `slip=${_toStr(dv1Constraints?.max_slippage_bps ?? '-')}`,
                            `pos<=${_toStr(dv1Constraints?.max_position_pct ?? '-')}`,
                          ].join(' · ')}
                        </div>
                      </div>
                      <div className="rounded border bg-slate-50 px-3 py-2">
                        <div className="text-slate-600 mb-1">risk_alerts</div>
                        <div className="text-slate-700 whitespace-pre-wrap break-words">{dv1RiskAlerts.length ? dv1RiskAlerts.join('\n') : '-'}</div>
                      </div>
                    </div>
                    {!dv1Tweets.length ? null : (
                      <div className="mt-2">
                        <div className="text-xs text-slate-600 mb-1">thread (v1)</div>
                        <div className="space-y-2">
                          {dv1Tweets.map((t, i) => (
                            <div key={`dv1_tw_${i}`} className="rounded border bg-slate-50 px-3 py-2 text-xs whitespace-pre-wrap break-words">
                              <div className="mb-1 text-slate-500">Tweet {i + 1}</div>
                              {t}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                  <div className="rounded border bg-white px-3 py-2">
                    <div className="text-xs text-slate-600 mb-2">因子层：注意力（trending / top_search）</div>
                    <div className="space-y-1 text-xs">
                      <div className="flex items-center justify-between gap-2"><span className="text-slate-600">trending</span><span className="truncate">{trending.length ? trending.join(', ') : '-'}</span></div>
                      <div className="flex items-center justify-between gap-2"><span className="text-slate-600">top_search</span><span className="truncate">{topSearch.length ? topSearch.join(', ') : '-'}</span></div>
                    </div>
                    <div className="mt-2 text-xs text-slate-600">输出重点：哪些币“被看到”</div>
                  </div>

                  <div className="rounded border bg-white px-3 py-2">
                    <div className="text-xs text-slate-600 mb-2">因子层：资金流（smart_money_inflow）</div>
                    <div className="space-y-1 text-xs">
                      <div className="flex items-center justify-between gap-2"><span className="text-slate-600">inflow</span><span className="truncate">{inflow.length ? inflow.join(', ') : '-'}</span></div>
                    </div>
                    <div className="mt-2 text-xs text-slate-600">输出重点：哪些币“被买入”</div>
                  </div>

                  <div className="rounded border bg-white px-3 py-2">
                    <div className="text-xs text-slate-600 mb-2">因子层：高手（top_traders_pnl）</div>
                    {(() => {
                      const rk = _safeObj(d?.rankings);
                      const rr = _safeObj(rk?.ranks);
                      const traders = _safeArray(rr?.top_traders_pnl);
                      const top3 = traders.slice(0, 3).map((x) => _safeObj(x)).filter((x): x is Record<string, unknown> => Boolean(x));
                      if (!top3.length) return <div className="text-xs text-slate-600">-</div>;
                      return (
                        <div className="space-y-1 text-xs">
                          {top3.map((t, idx) => {
                            const label = _toStr(t.addressLabel ?? t.label ?? t.name ?? `trader${idx + 1}`).trim() || `trader${idx + 1}`;
                            const pnl = _toStr(t.realizedPnl ?? '').trim();
                            const win = _toStr(t.winRate ?? '').trim();
                            const addr = _toStr(t.address ?? '').trim();
                            return (
                              <div key={`${label}_${idx}`} className="space-y-1">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="truncate">{label}</span>
                                  <span className="text-slate-600 truncate">{pnl ? `pnl ${_clip(pnl, 14)}` : '-'} {win ? `· win ${_clip(win, 8)}` : ''}</span>
                                </div>
                                {addr ? <div className="text-slate-500 truncate">{addr}</div> : null}
                              </div>
                            );
                          })}
                        </div>
                      );
                    })()}
                    <div className="mt-2 text-xs text-slate-600">输出重点：哪些币“被高手交易”</div>
                  </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                  <div className="rounded border bg-white px-3 py-2">
                    <div className="text-xs text-slate-600 mb-2">rankings top3</div>
                    <div className="space-y-1 text-xs">
                      <div className="flex items-center justify-between gap-2"><span className="text-slate-600">trending</span><span className="truncate">{trending.length ? trending.join(', ') : '-'}</span></div>
                      <div className="flex items-center justify-between gap-2"><span className="text-slate-600">top_search</span><span className="truncate">{topSearch.length ? topSearch.join(', ') : '-'}</span></div>
                      <div className="flex items-center justify-between gap-2"><span className="text-slate-600">inflow</span><span className="truncate">{inflow.length ? inflow.join(', ') : '-'}</span></div>
                    </div>
                  </div>

                  <div className="rounded border bg-white px-3 py-2">
                    <div className="text-xs text-slate-600 mb-2">watchlist</div>
                    {!w.length ? (
                      <div className="text-xs text-slate-600">-</div>
                    ) : (
                      <div className="space-y-1 text-xs">
                        {w.slice(0, 6).map((x, i) => {
                          const it = _safeObj(x);
                          const sym = _toStr(it?.symbol ?? it?.token ?? '').trim() || '-';
                          const liq = _fmtUsd(it?.liquidity_usd ?? it?.liquidity ?? it?.liq);
                          const vol = _fmtUsd(it?.volume24h_usd ?? it?.volume24h ?? it?.vol24h);
                          return (
                            <div key={`${sym}_${i}`} className="flex items-center justify-between gap-2">
                              <span className="truncate">{sym}</span>
                              <span className="text-slate-600 truncate">liq {liq} · vol {vol}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <div className="rounded border bg-white px-3 py-2">
                    <div className="text-xs text-slate-600 mb-2">LLM</div>
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <span className="text-slate-600">status</span>
                      <Badge variant={llmOk ? 'secondary' : 'outline'}>{llmOk ? 'ok' : 'fallback'}</Badge>
                    </div>
                    {llmSummary ? <div className="mt-2 text-xs text-slate-700 whitespace-pre-wrap break-words">{llmSummary}</div> : null}
                    {llmRisks.length ? (
                      <div className="mt-2">
                        <div className="text-xs text-slate-600 mb-1">risk_alerts</div>
                        <div className="space-y-1 text-xs text-slate-700">
                          {llmRisks.map((x, idx) => <div key={`r_${idx}`} className="whitespace-pre-wrap break-words">- {x}</div>)}
                        </div>
                      </div>
                    ) : null}
                    {llmActions.length ? (
                      <div className="mt-2">
                        <div className="text-xs text-slate-600 mb-1">actions</div>
                        <div className="space-y-1 text-xs text-slate-700">
                          {llmActions.map((x, idx) => <div key={`a_${idx}`} className="whitespace-pre-wrap break-words">- {x}</div>)}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="rounded border bg-white px-3 py-2">
                  <div className="text-xs text-slate-600 mb-2">重要信息因子（文档 1974-1977）</div>
                  {outputFocus ? <div className="text-xs text-slate-700 mb-2 whitespace-pre-wrap break-words">{outputFocus}</div> : null}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                    <div className="rounded border bg-slate-50 px-3 py-2">
                      <div className="text-slate-600 mb-1">注意力因子（trending/top_search）</div>
                      <div className="text-slate-700 whitespace-pre-wrap break-words">{seenTokens.length ? seenTokens.join(', ') : '-'}</div>
                    </div>
                    <div className="rounded border bg-slate-50 px-3 py-2">
                      <div className="text-slate-600 mb-1">资金流因子（smart_money_inflow）</div>
                      <div className="text-slate-700 whitespace-pre-wrap break-words">{boughtTokens.length ? boughtTokens.join(', ') : '-'}</div>
                    </div>
                    <div className="rounded border bg-slate-50 px-3 py-2">
                      <div className="text-slate-600 mb-1">高手/强者因子（top_traders_pnl）</div>
                      <div className="text-slate-700 whitespace-pre-wrap break-words">{topTraderAddrs.length ? topTraderAddrs.join(', ') : '-'}</div>
                    </div>
                  </div>
                </div>

                {dv1Tweets.length ? null : (
                  <div className="rounded border bg-white px-3 py-2">
                    <div className="text-xs text-slate-600 mb-2">thread tweets</div>
                    {!_uniqStrings(tweets).length ? (
                      <div className="text-xs text-slate-600">-</div>
                    ) : (
                      <div className="space-y-2">
                        {_uniqStrings(tweets).slice(0, 8).map((t, i) => (
                          <div key={`tw_${i}`} className="rounded border bg-slate-50 px-3 py-2 text-xs whitespace-pre-wrap break-words">
                            <div className="mb-1 text-slate-500">Tweet {i + 1}</div>
                            {t}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <details>
                  <summary className="cursor-pointer select-none text-xs text-slate-500">原始 digest</summary>
                  <pre className="mt-2 whitespace-pre-wrap break-words text-xs">{JSON.stringify(d, null, 2)}</pre>
                </details>
              </div>
            );
          })()
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-6">
      <Tabs value={activeTab} onValueChange={(v) => setTab(v === 'auto' ? 'auto' : 'research')} className="w-full">
        {hideTabSwitch || forcedTab ? null : (
          <TabsList>
            <TabsTrigger value="research">研究</TabsTrigger>
            <TabsTrigger value="auto">自动化交易</TabsTrigger>
          </TabsList>
        )}

        <TabsContent value="research" className="space-y-6">
          {loop}
          {live}
          <details className="rounded border bg-white px-3 py-2">
            <summary className="cursor-pointer select-none text-sm text-slate-600">设计要点（文档摘要）</summary>
            <div className="mt-3 grid grid-cols-1 lg:grid-cols-2 gap-6">
              {DOC_CARDS.map((c) => (
                <Card key={c.id}>
                  <CardHeader>
                    <CardTitle className="flex items-center justify-between gap-2">
                      <span className="truncate">{c.title}</span>
                      <Badge variant="outline">{c.id}</Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <div className="text-sm text-slate-600">{c.subtitle}</div>
                    <div className="space-y-1 text-xs text-slate-700">
                      {c.bullets.map((b) => (
                        <div key={b} className="whitespace-pre-wrap break-words">- {b}</div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </details>
        </TabsContent>

        <TabsContent value="auto" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span>自动化交易开关</span>
                <div className="flex items-center gap-2">
                  <Badge variant={String(autoTradeStateQuery.data?.auto_trade_env ?? '-') === 'prod' ? 'secondary' : 'outline'}>{String(autoTradeStateQuery.data?.auto_trade_env ?? '-')}</Badge>
                  <Badge variant={autoTradeStateQuery.data?.auto_trade_enabled ? 'destructive' : 'outline'}>{autoTradeStateQuery.data?.auto_trade_enabled ? 'enabled' : 'disabled'}</Badge>
                  <Badge variant="secondary">{String(autoTradeStateQuery.data?.auto_trade_mode ?? '-')}</Badge>
                  <Badge variant={autoTradeStateQuery.data?.kill_switch_triggered ? 'destructive' : 'outline'}>
                    {autoTradeStateQuery.data?.kill_switch_triggered ? 'kill_switch=ON' : 'kill_switch=OFF'}
                  </Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <label className="inline-flex items-center gap-2 rounded border px-2 py-1 bg-white">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={autoTradeEnabled}
                    disabled={autoTradeToggleMutation.isPending || !canOperate}
                    onChange={(e) => {
                      const next = Boolean(e.target.checked);
                      const msg = next
                        ? '开启自动化交易后，信号可能触发真实下单。确认开启？'
                        : '关闭自动化交易（Kill-Switch）后，将停止新开仓。确认关闭？';
                      if (!window.confirm(msg)) return;
                      if (next && !autoTradeEnablePassword.trim()) {
                        window.alert('请先填写实盘开关密码');
                        return;
                      }
                      autoTradeToggleMutation.mutate({ enabled: next, password: next ? autoTradeEnablePassword : undefined });
                    }}
                  />
                  <span>Kill-Switch（自动化交易总开关，默认关闭）</span>
                </label>
                <input
                  className="border rounded h-8 px-2 bg-white w-56"
                  type="password"
                  value={autoTradeEnablePassword}
                  onChange={(e) => setAutoTradeEnablePassword(e.target.value)}
                  placeholder="实盘开关密码（仅开启时需要）"
                />
                <label className="inline-flex items-center gap-2 rounded border px-2 py-1 bg-white">
                  <span>mode</span>
                  <select
                    className="border rounded h-7 px-2 bg-white"
                    value={autoTradeMode || 'manual'}
                    disabled={autoTradeModeMutation.isPending || !canOperate}
                    onChange={(e) => {
                      const next = String(e.target.value || 'manual');
                      const msg = next === 'auto' ? '切换到 auto 模式后将允许新开仓（需满足其它门禁）。确认？' : '切换到 manual 模式后将禁止新开仓。确认？';
                      if (!window.confirm(msg)) return;
                      autoTradeModeMutation.mutate(next);
                    }}
                  >
                    <option value="manual">manual</option>
                    <option value="auto">auto</option>
                  </select>
                </label>
                <label className="inline-flex items-center gap-2 rounded border px-2 py-1 bg-white">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={Boolean(autoTradeStateQuery.data?.auto_trade_binance_spot_open_in_prod)}
                    disabled={autoTradeOpenInProdMutation.isPending || !canOperate}
                    onChange={(e) => {
                      const next = Boolean(e.target.checked);
                      const msg = next ? '允许 prod 真实下单（Binance Spot）。确认？' : '关闭 prod 真实下单。确认？';
                      if (!window.confirm(msg)) return;
                      if (next && !autoTradeEnablePassword.trim()) {
                        window.alert('请先填写实盘开关密码');
                        return;
                      }
                      autoTradeOpenInProdMutation.mutate(next);
                    }}
                  />
                  <span>prod 实盘执行</span>
                </label>
                <label className="inline-flex items-center gap-2 rounded border px-2 py-1 bg-white">
                  <input
                    type="checkbox"
                    className="h-4 w-4"
                    checked={autoExitEnabled}
                    disabled={autoTradeAutoExitMutation.isPending || !canOperate}
                    onChange={(e) => {
                      const next = Boolean(e.target.checked);
                      const msg = next ? '开启自动化离场：入场后将自动执行离场评估与降风险。确认？' : '关闭自动化离场：由你手动决定离场。确认？';
                      if (!window.confirm(msg)) return;
                      autoTradeAutoExitMutation.mutate(next);
                    }}
                  />
                  <span>自动化离场开关</span>
                </label>
                <Badge variant={canOperate ? 'secondary' : 'outline'}>{canOperate ? 'operator_ok' : 'operator_token_missing'}</Badge>
                <Badge variant={autoTradeCanExecute ? 'secondary' : 'outline'}>{autoTradeCanExecute ? 'execution_ready' : 'execution_blocked'}</Badge>
                {autoTradeCanExecute ? (
                  <Button
                    variant="outline"
                    disabled={killSwitchMutation.isPending || !!autoTradeStateQuery.data?.kill_switch_triggered}
                    onClick={() => {
                      const ok = window.confirm(autoExitEnabled ? '触发 kill switch：停止新开仓并进入离场评估？' : '触发 kill switch：停止新开仓（离场由你手动决定）？');
                      if (!ok) return;
                      killSwitchMutation.mutate();
                    }}
                  >
                    触发 Kill Switch
                  </Button>
                ) : (
                  <span className="text-slate-500">
                    {!autoTradeEnabled ? 'auto_trade_enabled=false，仅展示研究建议' : (autoTradeMode !== 'auto' ? `auto_trade_mode=${autoTradeMode || '-'}，仅展示研究建议` : 'operator_token_missing')}
                  </span>
                )}
                {autoTradeEnabled && autoTradeMode !== 'auto' ? (
                  <span className="text-amber-700">auto_trade_mode={autoTradeMode || '-'}，新开仓相关按钮已禁用</span>
                ) : null}
              </div>
              {autoTradeToggleMutation.isError ? <div className="text-xs text-red-700">{_errStr(autoTradeToggleMutation.error) || 'toggle_failed'}</div> : null}
              {autoTradeModeMutation.isError ? <div className="text-xs text-red-700">{_errStr(autoTradeModeMutation.error) || 'mode_failed'}</div> : null}
              {autoTradeOpenInProdMutation.isError ? <div className="text-xs text-red-700">{_errStr(autoTradeOpenInProdMutation.error) || 'prod_open_failed'}</div> : null}
              {autoTradeAutoExitMutation.isError ? <div className="text-xs text-red-700">{_errStr(autoTradeAutoExitMutation.error) || 'auto_exit_toggle_failed'}</div> : null}
              {killSwitchMutation.isError ? <div className="text-xs text-red-700">{_errStr(killSwitchMutation.error) || 'kill switch failed'}</div> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span>信号触发执行（Binance Spot Skill）</span>
                <Badge variant="outline">execution tool</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              {(() => {
                const st = _safeObj(autoTradeStateQuery.data?.state);
                const last = _safeObj(st?.last_trade_execution);
                const skipped = Boolean(last?.skipped);
                const ok = Boolean(last?.ok);
                const reason = _toStr(last?.reason ?? '');
                const attempted = Number(last?.attempted ?? 0);
                const executed = Number(last?.executed ?? 0);
                return (
                  <>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={ok && !skipped ? 'secondary' : 'outline'}>{ok ? 'ok' : 'error'}</Badge>
                      <Badge variant={executed > 0 ? 'secondary' : 'outline'}>{`attempted=${Number.isFinite(attempted) ? attempted : 0}`}</Badge>
                      <Badge variant={executed > 0 ? 'secondary' : 'outline'}>{`executed=${Number.isFinite(executed) ? executed : 0}`}</Badge>
                      {reason ? <Badge variant="outline">{reason}</Badge> : null}
                    </div>
                    <div className="text-slate-600">触发条件：digest 生成 trade.decision 后自动调用 Binance Spot 交易技能执行下单。</div>
                    <pre className="rounded border bg-slate-50 px-3 py-2 whitespace-pre-wrap break-words">{JSON.stringify(last ?? {}, null, 2)}</pre>
                  </>
                );
              })()}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span>下单推荐表（Top5）</span>
                <Badge variant="outline">threshold {Math.round(recommendationThreshold * 100)}%</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!recommendationRows.length ? (
                <div className="text-xs text-slate-600">暂无推荐候选（等待最新 digest 数据）。</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                      <tr>
                        <th className="px-3 py-2">推荐币种</th>
                        <th className="px-3 py-2">推荐理由</th>
                        <th className="px-3 py-2">推荐评分</th>
                        <th className="px-3 py-2">结论</th>
                        <th className="px-3 py-2"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {recommendationRows.map((it, idx) => (
                        <tr key={`rec_${it.chainId}_${it.contractAddress}_${idx}`} className="border-b last:border-0 hover:bg-slate-50/50 align-top">
                          <td className="px-3 py-2">
                            <div className="text-gray-800 font-medium">{it.symbol}</div>
                            <div className="text-gray-500">{it.chainId}</div>
                          </td>
                          <td className="px-3 py-2 text-gray-600 whitespace-pre-wrap break-words max-w-[580px]">
                            <div>{it.reason}</div>
                            {it.risk ? <div className="mt-1 text-amber-700">风险：{it.risk}</div> : null}
                            {it.invalidations.length ? <div className="mt-1 text-slate-500">失效条件：{it.invalidations.join('；')}</div> : null}
                          </td>
                          <td className="px-3 py-2">
                            <Badge variant={it.recommend ? 'secondary' : 'outline'}>{it.scorePct}%</Badge>
                            {(typeof it.confidenceLow === 'number' && typeof it.confidenceHigh === 'number') ? (
                              <div className="mt-1 text-[11px] text-slate-500">
                                CI [{Math.round(it.confidenceLow * 100)}%, {Math.round(it.confidenceHigh * 100)}%]
                              </div>
                            ) : null}
                          </td>
                          <td className="px-3 py-2">
                            <Badge variant={it.recommend ? 'secondary' : 'destructive'}>{it.recommend ? '建议买入' : '不建议买入'}</Badge>
                            <div className="mt-1 text-[11px] text-slate-500">阈值 {Math.round((it.threshold ?? recommendationThreshold) * 100)}%</div>
                          </td>
                          <td className="px-3 py-2">
                            {autoTradeCanExecute ? (
                              <Button
                                variant="outline"
                                className="h-7 px-2"
                                onClick={() => {
                                  setTradeChainId(it.chainId || '56');
                                  setTradeContractAddress(it.contractAddress);
                                  setTradeSymbol(it.symbol);
                                  setPrecheckSnap(null);
                                }}
                              >
                                选择
                              </Button>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span>下单决策列表（优先 trade.decision 事件）</span>
                <div className="flex items-center gap-2 text-xs">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      const next = !decisionCollapsed;
                      setDecisionCollapsedPref(next);
                      _lsSetJson(LS_KEY_DECISION_COLLAPSED, next);
                    }}
                  >
                    {decisionCollapsed ? '展开列表' : '折叠列表'}
                  </Button>
                  <span className="text-slate-500">窗口</span>
                  <select className="border rounded h-8 px-2 bg-white" value={decisionWindow} onChange={(e) => setDecisionWindow(e.target.value as typeof decisionWindow)}>
                    <option value="1h">1h</option>
                    <option value="6h">6h</option>
                    <option value="24h">24h</option>
                    <option value="custom">自定义</option>
                  </select>
                  {decisionWindow === 'custom' ? (
                    <input
                      className="border rounded h-8 px-2 bg-white w-24"
                      value={decisionWindowCustomMin}
                      onChange={(e) => setDecisionWindowCustomMin(e.target.value)}
                      placeholder="分钟"
                    />
                  ) : null}
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {decisionsQuery.isError ? (
                <div className="text-xs text-red-700">trade.decision 读取失败，已回退到 digest 推导：{_errStr(decisionsQuery.error)}</div>
              ) : null}
              {!decisionItemsForUi.length ? (
                <div className="text-xs text-slate-600">窗口内暂无可用标的（需要 watchlist 且包含合约地址）。</div>
              ) : decisionCollapsed ? (
                <div className="rounded border bg-slate-50 px-3 py-3 text-xs text-slate-700 space-y-1">
                  <div>当前已折叠，窗口内候选 {decisionItemsForUi.length} 条。</div>
                  <div>可先参考上方 Top5 推荐表，点击“展开列表”查看完整决策明细。</div>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                      <tr>
                        <th className="px-3 py-2">ts</th>
                        <th className="px-3 py-2">chain</th>
                        <th className="px-3 py-2">symbol</th>
                        <th className="px-3 py-2">contract</th>
                        <th className="px-3 py-2">liq</th>
                        <th className="px-3 py-2">vol24h</th>
                        <th className="px-3 py-2"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {decisionItemsForUi.slice(0, 40).map((it, idx) => (
                        <tr key={`${it.chainId}_${it.contractAddress}_${idx}`} className="border-b last:border-0 hover:bg-slate-50/50">
                          <td className="px-3 py-2 text-gray-600">{new Date(it.tsMs).toLocaleString()}</td>
                          <td className="px-3 py-2 text-gray-600">{it.chainId}</td>
                          <td className="px-3 py-2 text-gray-800 font-medium">{it.symbol}</td>
                          <td className="px-3 py-2 text-gray-500 truncate max-w-[260px]">{it.contractAddress}</td>
                          <td className="px-3 py-2 text-gray-500">{_fmtUsd(it.liquidity)}</td>
                          <td className="px-3 py-2 text-gray-500">{_fmtUsd(it.volume24h)}</td>
                          <td className="px-3 py-2">
                            {autoTradeCanExecute ? (
                              <Button
                                variant="outline"
                                className="h-7 px-2"
                                onClick={() => {
                                  setTradeChainId(it.chainId || '56');
                                  setTradeContractAddress(it.contractAddress);
                                  setTradeSymbol(it.symbol);
                                  setPrecheckSnap(null);
                                }}
                              >
                                选择
                              </Button>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span>持仓跟踪（position.open / position.snapshot）</span>
                <div className="flex items-center gap-2">
                  <Badge variant="outline">open={openPositions.length}</Badge>
                  <Badge variant={snapshotAutoEnabled ? 'secondary' : 'outline'}>
                    {snapshotAutoEnabled ? `auto ${snapshotPeriod}` : 'auto off'}
                  </Badge>
                </div>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <div className="rounded border bg-slate-50 px-3 py-2 text-slate-700">
                买入后先登记 position.open，再按 5m/15m/30m/1h 刷新 position.snapshot，快照覆盖注意力—流动性—资金流—链上地址行为四因子。
              </div>
              {positionsQuery.isError ? <div className="text-red-700">持仓读取失败：{_errStr(positionsQuery.error)}</div> : null}
              {!openPositions.length ? (
                <div className="text-slate-600">暂无 open 持仓，可先用下方交易参数生成 order.intent 后登记持仓。</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left">
                    <thead className="text-[11px] text-gray-500 uppercase bg-gray-50/50">
                      <tr>
                        <th className="px-3 py-2">position_id</th>
                        <th className="px-3 py-2">symbol</th>
                        <th className="px-3 py-2">size/notional</th>
                        <th className="px-3 py-2">entry</th>
                        <th className="px-3 py-2">snapshot</th>
                      </tr>
                    </thead>
                    <tbody>
                      {openPositions.slice(0, 30).map((p) => {
                        const entryTs = Number(p.entry_ts_ms ?? 0);
                        const snapTs = Number(p.last_snapshot_ts_ms ?? 0);
                        const pid = _toStr(p.position_id).trim();
                        return (
                          <tr key={pid} className="border-b last:border-0 hover:bg-slate-50/50">
                            <td className="px-3 py-2">
                              <button
                                type="button"
                                className={effectiveSelectedPositionId === pid ? 'text-blue-600 font-semibold' : 'text-slate-700'}
                                onClick={() => setSelectedPositionId(pid)}
                              >
                                {pid.slice(0, 8)}…
                              </button>
                            </td>
                            <td className="px-3 py-2 text-slate-700">{_toStr(p.symbol ?? '-')} · {_toStr(p.chain_id ?? '-')}</td>
                            <td className="px-3 py-2 text-slate-600">
                              qty {_toStr(p.size_token ?? '-')} / {_fmtUsd(p.notional_usd)}
                            </td>
                            <td className="px-3 py-2 text-slate-600">
                              {entryTs > 0 ? new Date(entryTs).toLocaleString() : '-'}
                            </td>
                            <td className="px-3 py-2 text-slate-600">
                              {snapTs > 0 ? _fmtAgo(nowMs, snapTs) : '-'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-2">
                <div>
                  <div className="text-slate-500 mb-1">snapshot 周期</div>
                  <select className="w-full border rounded h-8 px-2 bg-white" value={snapshotPeriod} onChange={(e) => setSnapshotPeriod((e.target.value as '5m' | '15m' | '30m' | '1h'))}>
                    <option value="5m">5m</option>
                    <option value="15m">15m</option>
                    <option value="30m">30m</option>
                    <option value="1h">1h</option>
                  </select>
                </div>
                <div className="flex items-end">
                  <label className="inline-flex items-center gap-2 rounded border px-2 py-1 bg-white">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={snapshotAutoEnabled}
                      disabled={!canOperate}
                      onChange={(e) => setSnapshotAutoEnabled(Boolean(e.target.checked))}
                    />
                    <span>自动刷新快照</span>
                  </label>
                </div>
                <div className="flex items-end">
                  {canOperate ? (
                    <Button variant="outline" disabled={!selectedPosition || snapshotMutation.isPending} onClick={() => snapshotMutation.mutate()}>
                      {snapshotMutation.isPending ? '刷新中…' : '立即刷新快照'}
                    </Button>
                  ) : null}
                </div>
                <div className="md:col-span-2 xl:col-span-2 flex items-end">
                  <div className="rounded border bg-white px-2 py-1 w-full">
                    {!selectedPositionFactorPack ? (
                      <div className="text-slate-500">请选择持仓后显示四因子快照</div>
                    ) : (
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline">attention {Math.round(selectedPositionFactorPack.attention.score * 100)}%</Badge>
                          <Badge variant="outline">liquidity {Math.round(selectedPositionFactorPack.liquidity.score * 100)}%</Badge>
                          <Badge variant="outline">flow {Math.round(selectedPositionFactorPack.flow.score * 100)}%</Badge>
                          <Badge variant="outline">onchain {Math.round(selectedPositionFactorPack.onchain.score * 100)}%</Badge>
                        </div>
                        <div className="text-slate-600">
                          risk_score={Math.round(selectedPositionFactorPack.risk_score * 100)}% · value_score={Math.round(selectedPositionFactorPack.value_score * 100)}%
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              {snapshotMutation.isError ? <div className="text-red-700">snapshot 失败：{_errStr(snapshotMutation.error)}</div> : null}
              {snapshotMutation.data ? (
                <pre className="rounded border bg-slate-50 px-3 py-2 whitespace-pre-wrap break-words">{JSON.stringify(snapshotMutation.data, null, 2)}</pre>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <span>离场系统（exit.intent + risk review）</span>
                <Button variant="outline" size="sm" disabled={!canOperate || exitReviewMutation.isPending} onClick={() => exitReviewMutation.mutate()}>
                  {exitReviewMutation.isPending ? '评估中…' : '运行风险离场评估'}
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-xs">
              <div className="rounded border bg-slate-50 px-3 py-2 text-slate-700">
                离场设置按因子勾选 + 刷新周期 + 连续确认次数触发 exit.intent；风险系统基于四因子生成 risk_score/value_score，高风险优先执行减仓/平仓。
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-2">
                <div>
                  <div className="text-slate-500 mb-1">mode</div>
                  <select className="w-full border rounded h-8 px-2 bg-white" value={exitMode} disabled={!canOperate} onChange={(e) => setExitMode(e.target.value === 'auto' ? 'auto' : 'manual')}>
                    <option value="manual">manual</option>
                    <option value="auto">auto</option>
                  </select>
                </div>
                <div>
                  <div className="text-slate-500 mb-1">confirm_count</div>
                  <input className="w-full border rounded h-8 px-2 bg-white" value={exitConfirmCount} disabled={!canOperate} onChange={(e) => setExitConfirmCount(e.target.value)} />
                </div>
                <div>
                  <div className="text-slate-500 mb-1">action</div>
                  <select className="w-full border rounded h-8 px-2 bg-white" value={exitAction} disabled={!canOperate} onChange={(e) => setExitAction(e.target.value === 'close' ? 'close' : 'reduce')}>
                    <option value="reduce">reduce</option>
                    <option value="close">close</option>
                  </select>
                </div>
                <div>
                  <div className="text-slate-500 mb-1">reduce_ratio</div>
                  <input className="w-full border rounded h-8 px-2 bg-white" value={exitReduceRatio} disabled={!canOperate} onChange={(e) => setExitReduceRatio(e.target.value)} />
                </div>
                <div className="xl:col-span-2">
                  <div className="text-slate-500 mb-1">reason</div>
                  <input className="w-full border rounded h-8 px-2 bg-white" value={exitReason} disabled={!canOperate} onChange={(e) => setExitReason(e.target.value)} />
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {(['attention', 'liquidity', 'flow', 'onchain'] as const).map((k) => (
                  <label key={k} className="inline-flex items-center gap-2 rounded border px-2 py-1 bg-white">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={Boolean(exitFactors[k])}
                      disabled={!canOperate}
                      onChange={(e) => setExitFactors((prev) => ({ ...prev, [k]: Boolean(e.target.checked) }))}
                    />
                    <span>{k}</span>
                  </label>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">selected={selectedFactors.join(',') || '-'}</Badge>
                <Badge variant="outline">position={effectiveSelectedPositionId ? `${effectiveSelectedPositionId.slice(0, 8)}…` : '-'}</Badge>
                {selectedPositionFactorPack ? (
                  <>
                    <Badge variant={selectedPositionFactorPack.risk_score >= 0.72 ? 'destructive' : 'outline'}>
                      risk {Math.round(selectedPositionFactorPack.risk_score * 100)}%
                    </Badge>
                    <Badge variant="secondary">value {Math.round(selectedPositionFactorPack.value_score * 100)}%</Badge>
                  </>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {canOperate ? (
                  <Button disabled={!selectedPosition || exitIntentMutation.isPending} onClick={() => exitIntentMutation.mutate()}>
                    {exitIntentMutation.isPending ? '提交中…' : '生成 exit.intent'}
                  </Button>
                ) : null}
              </div>
              {exitIntentMutation.isError ? <div className="text-red-700">exit.intent 失败：{_errStr(exitIntentMutation.error)}</div> : null}
              {exitReviewMutation.isError ? <div className="text-red-700">exit review 失败：{_errStr(exitReviewMutation.error)}</div> : null}
              {exitReviewMutation.data ? (
                <pre className="rounded border bg-slate-50 px-3 py-2 whitespace-pre-wrap break-words">{JSON.stringify(exitReviewMutation.data, null, 2)}</pre>
              ) : null}
              {exitIntentMutation.data ? (
                <pre className="rounded border bg-slate-50 px-3 py-2 whitespace-pre-wrap break-words">{JSON.stringify(exitIntentMutation.data, null, 2)}</pre>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>预交易门禁（审计 + 可交易检查）</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-3 text-xs">
                <div>
                  <div className="text-slate-500 mb-1">chain_id</div>
                  <input className="w-full border rounded h-9 px-2 bg-white" value={tradeChainId} onChange={(e) => setTradeChainId(e.target.value)} />
                </div>
                <div className="md:col-span-2 xl:col-span-3">
                  <div className="text-slate-500 mb-1">contract_address</div>
                  <input className="w-full border rounded h-9 px-2 bg-white" value={tradeContractAddress} onChange={(e) => setTradeContractAddress(e.target.value)} />
                </div>
                <div>
                  <div className="text-slate-500 mb-1">symbol</div>
                  <input className="w-full border rounded h-9 px-2 bg-white" value={tradeSymbol} onChange={(e) => setTradeSymbol(e.target.value)} />
                </div>
                <div className="flex items-end gap-2">
                  {autoTradeCanExecute ? (
                    <Button variant="secondary" disabled={precheckMutation.isPending} onClick={() => precheckMutation.mutate()}>
                      {precheckMutation.isPending ? 'Checking…' : '运行检查'}
                    </Button>
                  ) : null}
                </div>
              </div>

              {precheckMutation.isError ? <div className="text-xs text-red-700">{_errStr(precheckMutation.error) || 'precheck_failed'}</div> : null}
              {!precheckSnap ? null : (
                <div className="rounded border bg-slate-50 px-3 py-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-slate-600">gate</div>
                    <Badge variant={String(_safeObj(precheckSnap?.gate)?.decision ?? '') === 'pass' ? 'secondary' : 'outline'}>
                      {String(_safeObj(precheckSnap?.gate)?.decision ?? '-')}
                    </Badge>
                  </div>
                  <div className="mt-2 whitespace-pre-wrap break-words">{JSON.stringify(precheckSnap, null, 2)}</div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>下单意图（order.intent → orders.jsonl）</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-3 text-xs">
                <div>
                  <div className="text-slate-500 mb-1">side</div>
                  <select className="w-full border rounded h-9 px-2 bg-white" value={tradeSide} onChange={(e) => setTradeSide(e.target.value === 'sell' ? 'sell' : 'buy')}>
                    <option value="buy">buy</option>
                    <option value="sell">sell</option>
                  </select>
                </div>
                <div>
                  <div className="text-slate-500 mb-1">notional_usd</div>
                  <input className="w-full border rounded h-9 px-2 bg-white" value={tradeNotionalUsd} onChange={(e) => setTradeNotionalUsd(e.target.value)} />
                </div>
                <div>
                  <div className="text-slate-500 mb-1">max_slippage_bps</div>
                  <input className="w-full border rounded h-9 px-2 bg-white" value={tradeSlippageBps} onChange={(e) => setTradeSlippageBps(e.target.value)} />
                </div>
                <div>
                  <div className="text-slate-500 mb-1">size_token（position.open）</div>
                  <input className="w-full border rounded h-9 px-2 bg-white" value={positionSizeToken} onChange={(e) => setPositionSizeToken(e.target.value)} />
                </div>
                <div>
                  <div className="text-slate-500 mb-1">entry_ref（position.open）</div>
                  <input className="w-full border rounded h-9 px-2 bg-white" value={positionEntryRef} onChange={(e) => setPositionEntryRef(e.target.value)} />
                </div>
                <div className="flex items-end gap-2">
                  {autoTradeCanExecute ? (
                    <Button variant="secondary" disabled={intentMutation.isPending} onClick={() => intentMutation.mutate()}>
                      {intentMutation.isPending ? 'Submitting…' : '生成 order.intent'}
                    </Button>
                  ) : null}
                  {canOperate ? (
                    <Button variant="outline" disabled={positionOpenMutation.isPending} onClick={() => positionOpenMutation.mutate()}>
                      {positionOpenMutation.isPending ? '登记中…' : '登记 position.open'}
                    </Button>
                  ) : null}
                </div>
              </div>
              {intentMutation.isError ? <div className="text-xs text-red-700">{_errStr(intentMutation.error) || 'intent_failed'}</div> : null}
              {positionOpenMutation.isError ? <div className="text-xs text-red-700">{_errStr(positionOpenMutation.error) || 'position_open_failed'}</div> : null}
              {intentMutation.data ? (
                <div className="rounded border bg-slate-50 px-3 py-2 text-xs whitespace-pre-wrap break-words">{JSON.stringify(intentMutation.data, null, 2)}</div>
              ) : null}
              {positionOpenMutation.data ? (
                <div className="rounded border bg-slate-50 px-3 py-2 text-xs whitespace-pre-wrap break-words">{JSON.stringify(positionOpenMutation.data, null, 2)}</div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>orders.jsonl（tail）</CardTitle>
            </CardHeader>
            <CardContent>
              {ordersTailQuery.isLoading ? (
                <div className="text-xs text-slate-600">loading…</div>
              ) : ordersTailQuery.isError ? (
                <div className="text-xs text-red-700">failed</div>
              ) : (
                <pre className="text-xs whitespace-pre-wrap break-words">{JSON.stringify(ordersTailQuery.data?.items?.map((x) => x.item).slice(-20) ?? [], null, 2)}</pre>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};
