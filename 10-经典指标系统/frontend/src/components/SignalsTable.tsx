
import React, { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchRecentOrdersWithParams, fetchRecentSignalsWithParams, fetchSignalRejectStats } from '../lib/api';
import type { FetchRecentSignalsParams, Order, SignalRejectStats } from '../lib/api';
import { Radio } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { Button } from './ui/button';
import { clsx } from 'clsx';

export const SignalsTable: React.FC<{
  abOwner?: string;
  bookId?: string;
  strategyId?: string;
  groupId?: string;
  pair?: string;
  title?: string;
  displayLimit?: number;
  includeBackfill?: boolean;
  includeShadow?: boolean;
  includeStale?: boolean;
  showOrderInfo?: boolean;
  defaultActionFilter?: 'all' | 'open' | 'close';
}> = ({ abOwner, bookId, strategyId, groupId, pair, title, displayLimit = 50, includeBackfill = false, includeShadow, includeStale, showOrderInfo = false, defaultActionFilter = 'all' }) => {
  const toMs = (t: number): number => {
    if (!Number.isFinite(t) || t <= 0) return 0;
    return t < 1_000_000_000_000 ? t * 1000 : t;
  };

  const formatReason = (reason: unknown, decision: string): { text: string; raw: string } => {
    const raw = (reason == null ? '' : String(reason)).trim();
    if (!raw) {
      if (decision === 'observe') return { text: '观察中', raw: '' };
      return { text: '', raw: '' };
    }

    const asterHttpMatch = raw.match(/^aster_http_error:(\d+):([\s\S]*)$/);
    if (asterHttpMatch) {
      const status = Number(asterHttpMatch[1]);
      const payload = String(asterHttpMatch[2] ?? '').trim();
      const methodPathMatch = payload.match(/^(GET|POST|PUT|DELETE|PATCH)\s+([^:]+):(.*)$/s);
      const endpoint = methodPathMatch ? String(methodPathMatch[2] ?? '').trim() : '';
      const bodyRaw = methodPathMatch ? String(methodPathMatch[3] ?? '').trim() : payload;
      const pureJsonMatch = bodyRaw.match(/^(\{[\s\S]*\})$/);
      if (pureJsonMatch) {
        try {
          const body = JSON.parse(pureJsonMatch[1]) as { code?: unknown; msg?: unknown };
          const code = Number(body?.code ?? NaN);
          const msg = typeof body?.msg === 'string' ? body.msg : '';
          if (Number.isFinite(code)) {
            if (code === -2019) return { text: `保证金不足 (${code})`, raw };
            if (code === -2022) return { text: `Reduce-only 被拒 (${code})`, raw };
            if (msg) return { text: `Aster ${status} (${code}) ${msg}`, raw };
            return { text: `Aster ${status} (${code})`, raw };
          }
          if (msg) return { text: `Aster ${status} ${msg}`, raw };
          return { text: `Aster ${status} 请求失败`, raw };
        } catch {
          return { text: `Aster ${Number.isFinite(status) ? status : ''} 请求失败`, raw };
        }
      }
      const isHtml = /<!doctype html>|<html/i.test(bodyRaw);
      if (isHtml) {
        if (status === 404 && endpoint) return { text: `Aster 404 接口不存在 (${endpoint})`, raw };
        if (status === 404) return { text: 'Aster 404 接口不存在', raw };
        return { text: `Aster ${Number.isFinite(status) ? status : ''} 网关返回 HTML`, raw };
      }
      const bodyOneLine = bodyRaw.replace(/\s+/g, ' ').trim();
      if (bodyOneLine) {
        const clipped = bodyOneLine.length > 80 ? `${bodyOneLine.slice(0, 80)}…` : bodyOneLine;
        if (endpoint) return { text: `Aster ${Number.isFinite(status) ? status : ''} ${endpoint} ${clipped}`, raw };
        return { text: `Aster ${Number.isFinite(status) ? status : ''} ${clipped}`, raw };
      }
      return { text: `Aster ${Number.isFinite(status) ? status : ''} 请求失败`, raw };
    }

    if (raw === 'decision_not_triggered') return { text: '未触发决策', raw };
    if (raw === 'auto_decision_disabled') return { text: '未开启自动决策', raw };
    if (raw === 'not_executed') return { text: '未执行下单', raw };
    if (raw === 'arena_gate') return { text: 'Gate 拦截', raw };
    if (raw === 'below_threshold') return { text: '低于阈值', raw };
    if (raw === 'pc_below_threshold') return { text: '低于阈值', raw };
    if (raw === 'bar_not_closed') return { text: 'K线未收', raw };
    if (raw === 'non_open_action') return { text: '非开仓信号', raw };
    if (raw === 'arena_no_taker') return { text: '无模型接单', raw };
    if (raw === 'shadow_mode') return { text: 'Shadow 模式', raw };
    if (raw === 'signal_stale') return { text: '信号过期', raw };
    if (raw === 'canary_pair_not_whitelisted') return { text: 'Canary 未放行交易对', raw };
    return { text: raw, raw };
  };

  const formatAb = (sig: unknown): { text: string; title: string } => {
    const diOut = (sig as { decision_info?: { out?: unknown } } | null | undefined)?.decision_info?.out as Record<string, unknown> | undefined;
    const abOwnerRaw = (sig as { ab_owner?: unknown } | null | undefined)?.ab_owner ?? diOut?.ab_owner;
    const ocRaw = (sig as { owner_contrib?: unknown } | null | undefined)?.owner_contrib ?? diOut?.owner_contrib;
    const strategyIdRaw = (sig as { strategy_id?: unknown } | null | undefined)?.strategy_id ?? strategyId;
    const sid = String(strategyIdRaw ?? '').toLowerCase().replace(/[-_]/g, '').trim();
    const isThreeScreen = sid === 'threescreen';

    const parts: string[] = [];
    const titleParts: string[] = [];

    const oc = (ocRaw && typeof ocRaw === 'object') ? (ocRaw as Record<string, unknown>) : null;
    if (oc) {
      let s = Number(oc.strategy ?? NaN);
      const q = Number(oc.quant ?? NaN);
      const c = Number((oc as Record<string, unknown>).carry ?? NaN);
      let t = Number((oc as Record<string, unknown>).three_screen ?? (oc as Record<string, unknown>).ts ?? NaN);

      if (isThreeScreen) {
        const likelyMisattributed = Number.isFinite(s) && s > 0 && (!Number.isFinite(t) || t === 0);
        if (likelyMisattributed) {
          t = s;
          s = 0;
        }
      }
      if (Number.isFinite(s) || Number.isFinite(q) || Number.isFinite(c) || Number.isFinite(t)) {
        parts.push(`S:${Number.isFinite(s) ? s.toFixed(0) : '-'}`);
        parts.push(`Q:${Number.isFinite(q) ? q.toFixed(0) : '-'}`);
        parts.push(`C:${Number.isFinite(c) ? c.toFixed(0) : '-'}`);
        parts.push(`T:${Number.isFinite(t) ? t.toFixed(0) : '-'}`);
        titleParts.push(`owner_contrib=${JSON.stringify(oc)}`);
      }
    }

    const abOwner = (abOwnerRaw == null ? '' : String(abOwnerRaw)).trim();
    if (abOwner) {
      if (parts.length === 0) parts.push(abOwner);
      titleParts.push(`ab_owner=${abOwner}`);
    }

    return { text: parts.join(' '), title: titleParts.join('\n') };
  };

  const baseShowShadow = Boolean(includeShadow);
  const baseShowStale = Boolean(includeStale);
  const [shadowOverride, setShadowOverride] = useState<boolean | null>(null);
  const [staleOverride, setStaleOverride] = useState<boolean | null>(null);
  const showShadow = shadowOverride ?? baseShowShadow;
  const showStale = staleOverride ?? baseShowStale;
  const [actionTouched, setActionTouched] = useState<boolean>(false);
  const [actionFilterLocal, setActionFilterLocal] = useState<'all' | 'open' | 'close'>(() => defaultActionFilter);
  const actionFilter = actionTouched ? actionFilterLocal : defaultActionFilter;
  const abOwnerEff = useMemo(() => {
    if (abOwner) return abOwner;
    const sid = String(strategyId ?? '').toLowerCase().replace(/[-_]/g, '').trim();
    if (sid === 'threescreen') return 'three_screen';
    return abOwner;
  }, [abOwner, strategyId]);
  const bookIdEff = useMemo(() => {
    if (bookId) return bookId;
    if (abOwnerEff === 'three_screen') return 'three_screen';
    return undefined;
  }, [abOwnerEff, bookId]);

  const normalizeDecision = (di: unknown): string => {
    const obj = (di && typeof di === 'object') ? (di as Record<string, unknown>) : null;
    const d = obj?.decision != null ? String(obj.decision) : '';
    const executed = typeof obj?.executed === 'boolean' ? (obj.executed as boolean) : undefined;
    if (d === 'enter' && executed !== true) return 'observe';
    return d || 'unknown';
  };
  const requestParams = useMemo(() => {
    const fetchLimit = Math.max(1, Math.min(200, Math.floor(Number(displayLimit) || 50)));
    const params: FetchRecentSignalsParams = {
      limit: Math.max(20, fetchLimit),
      include_backfill: includeBackfill ? 1 : 0,
      include_shadow: showShadow ? 1 : 0,
      include_stale: showStale ? 1 : 0,
      scan_limit: 800,
      require_bar_closed: 1,
      diverse: 1,
      per_pair: 8,
    };
    if (abOwnerEff) {
      params.ab_owner = abOwnerEff;
    }
    if (bookIdEff) {
      params.book_id = bookIdEff;
    }
    if (strategyId) {
      params.strategy_id = strategyId;
    }
    if (groupId) {
      params.group_id = groupId;
    }
    if (pair) {
      params.pair = pair;
    }
    if (actionFilter === 'open') {
      params.action = 'open';
      params.executed_only = 1;
    }
    if (actionFilter === 'close') {
      params.action = 'close';
      params.executed_only = 1;
    }
    return params;
  }, [abOwnerEff, actionFilter, bookIdEff, displayLimit, groupId, includeBackfill, pair, showShadow, showStale, strategyId]);
  const { data: signals, isLoading, error, isFetching, dataUpdatedAt } = useQuery({ 
    queryKey: ['signals', 'recent', abOwnerEff ?? '', bookIdEff ?? '', strategyId ?? '', groupId ?? '', pair ?? '', showShadow, showStale, actionFilter], 
    queryFn: () => {
      return fetchRecentSignalsWithParams(requestParams);
    },
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: recentOrders } = useQuery({
    queryKey: ['orders', 'recent', 'for_signals', abOwnerEff ?? '', bookIdEff ?? '', strategyId ?? '', groupId ?? '', pair ?? '', showShadow],
    enabled: Boolean(showOrderInfo && (abOwnerEff || bookIdEff)),
    queryFn: () =>
      fetchRecentOrdersWithParams({
        limit: Math.max(40, Math.min(80, Math.floor(Number(displayLimit) || 50) * 2)),
        sort: 'ingest',
        include_shadow: showShadow ? 1 : 0,
        ab_owner: abOwnerEff,
        book_id: bookIdEff,
        allow_book_id_missing: (bookIdEff === 'three_screen' ? 0 : 1),
        no_event_backfill: 1,
        strategy_id: strategyId,
        group_id: groupId,
        pair,
      }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const orderByEventId = useMemo(() => {
    const out = new Map<string, Order>();
    if (!showOrderInfo) return out;
    const raw = Array.isArray(recentOrders) ? recentOrders : [];
    for (const o of raw) {
      const eid = String(o?.event_id ?? '').trim();
      if (!eid) continue;
      out.set(eid, o);
    }
    return out;
  }, [recentOrders, showOrderInfo]);

  const rows = useMemo(() => {
    const raw = Array.isArray(signals) ? signals : [];
    return raw
      .filter((sig): sig is NonNullable<typeof sig> => Boolean(sig) && typeof sig === 'object')
      .filter((sig) => {
      const barClosed = (sig as { bar_closed?: unknown } | null | undefined)?.bar_closed;
      if (barClosed === false) return false;
      const reason = String(sig?.decision_info?.reason ?? '').trim().toLowerCase();
      if (reason === 'bar_not_closed') return false;
      return true;
    })
      .filter((sig) => {
        const a = String((sig as unknown as { action?: unknown } | null | undefined)?.action ?? '').trim().toLowerCase();
        if (actionFilter === 'open') {
          if (a === 'open') return true;
          return normalizeDecision(sig.decision_info ?? null) === 'enter';
        }
        if (actionFilter === 'close') {
          return a === 'close';
        }
        return true;
      });
  }, [signals, actionFilter]);
  const limitedRows = useMemo(() => {
    const n = Math.max(1, Math.floor(Number(displayLimit) || 50));
    return rows.slice(0, n);
  }, [rows, displayLimit]);
  const errorText = (() => {
    const e = error as unknown as { message?: unknown; response?: { status?: unknown } } | null | undefined;
    const status = e?.response?.status;
    const msg = typeof e?.message === 'string' ? e.message : '';
    if (status != null) return `${String(status)}${msg ? `: ${msg}` : ''}`;
    return msg || 'Request failed';
  })();
  const lastOkText = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : '';
  useEffect(() => {
    if (isLoading) return;
    if (isFetching) return;
    if (Array.isArray(signals) && signals.length === 0) {
      console.warn('[SignalsTable] empty signals', { params: requestParams, last_ok_at: dataUpdatedAt || null, error: errorText || null });
    }
  }, [dataUpdatedAt, errorText, isFetching, isLoading, requestParams, signals]);

  const { data: rejectStats } = useQuery<SignalRejectStats>({
    queryKey: ['signals', 'reject_stats', showShadow],
    queryFn: () => fetchSignalRejectStats(5000, showShadow),
    refetchInterval: 5000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const stats = useMemo(() => {
    const rows0 = rows;
    const withDecision = rows0.filter((s) => Boolean(s?.decision_info?.decision));
    const byDecision: Record<string, number> = {};
    const reasonCount: Record<string, number> = {};
    for (const s of withDecision) {
      const di = s.decision_info ?? {};
      const d = normalizeDecision(di);
      byDecision[d] = (byDecision[d] ?? 0) + 1;
      if (d !== 'enter' && d !== 'observe') {
        const r = String(di.reason ?? '');
        const key = r.trim() ? r.trim() : 'none';
        reasonCount[key] = (reasonCount[key] ?? 0) + 1;
      }
    }
    const nonEnterN = Object.entries(byDecision)
      .filter(([k]) => k !== 'enter' && k !== 'observe')
      .reduce((acc, [, v]) => acc + v, 0);
    const topReasons = Object.entries(reasonCount)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([k, v]) => ({ reason: k, n: v, pct: nonEnterN > 0 ? v / nonEnterN : 0 }));
    if (rejectStats && rejectStats.ok) {
      const rs = rejectStats;
      const byD = (rs.by_decision ?? {}) as Record<string, number>;
      const byR = (rs.by_reason ?? {}) as Record<string, number>;
      const nonEnter = Object.entries(byD)
        .filter(([k]) => k !== 'enter' && k !== 'observe')
        .reduce((acc, [, v]) => acc + Number(v ?? 0), 0);
      const ignoreReasons = new Set(['decision_not_triggered', 'not_executed']);
      const topR = Object.entries(byR)
        .filter(([k]) => !ignoreReasons.has(String(k ?? '').trim()))
        .sort((a, b) => Number(b[1] ?? 0) - Number(a[1] ?? 0))
        .slice(0, 5)
        .map(([k, v]) => ({ reason: k, n: Number(v ?? 0), pct: nonEnter > 0 ? Number(v ?? 0) / nonEnter : 0 }));
      return {
        withDecisionN: Number(rs.with_decision ?? withDecision.length),
        byDecision: byD,
        nonEnterN: nonEnter,
        topReasons: topR,
      };
    }
    return {
      withDecisionN: withDecision.length,
      byDecision,
      nonEnterN,
      topReasons,
    };
  }, [rows, rejectStats]);
  const colN = showOrderInfo ? 10 : 9;

  return (
    <Card className="h-full">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-lg font-medium">{title ?? 'Recent Signals'}</CardTitle>
        <div className="flex items-center gap-2">
          <Button
            variant={actionFilter === 'all' ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setActionTouched(true);
              setActionFilterLocal('all');
            }}
          >
            全部
          </Button>
          <Button
            variant={actionFilter === 'open' ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setActionTouched(true);
              setActionFilterLocal('open');
            }}
          >
            仅 open
          </Button>
          <Button
            variant={actionFilter === 'close' ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setActionTouched(true);
              setActionFilterLocal('close');
            }}
          >
            仅 close
          </Button>
          <Button
            variant={showShadow ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setShadowOverride((prev) => {
                const cur = prev ?? baseShowShadow;
                return !cur;
              });
            }}
          >
            {showShadow ? '含 shadow' : '不含 shadow'}
          </Button>
          <Button
            variant={showStale ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setStaleOverride((prev) => {
                const cur = prev ?? baseShowStale;
                return !cur;
              });
            }}
          >
            {showStale ? '含过期' : '不含过期'}
          </Button>
          {isFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
          <Radio className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {!isLoading && error && limitedRows.length > 0 ? (
          <div className="px-4 py-2 border-b border-gray-100 text-xs text-rose-700">
            Backend unreachable · showing cached data{lastOkText ? ` (last ok: ${lastOkText})` : ''}
          </div>
        ) : null}
        {stats.withDecisionN > 0 && (
          <div className="px-4 py-2 border-b border-gray-100 text-xs text-slate-700 space-y-1">
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              <span>decisions: {stats.withDecisionN}</span>
              <span>enter: {stats.byDecision.enter ?? 0}</span>
              <span>observe: {stats.byDecision.observe ?? 0}</span>
              <span>hold: {stats.byDecision.hold ?? 0}</span>
              <span>reject: {stats.byDecision.reject ?? 0}</span>
              <span>error: {stats.byDecision.error ?? 0}</span>
            </div>
            {stats.topReasons.length > 0 && (
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-slate-600">
                {stats.topReasons.map((x) => (
                  <span key={x.reason}>
                    {x.reason}: {x.n} ({(x.pct * 100).toFixed(0)}%)
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="overflow-y-auto max-h-[300px]">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-500 uppercase bg-gray-50/50 sticky top-0">
              <tr>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Pair</th>
                <th className="px-4 py-3">Side</th>
                <th className="px-4 py-3">Decision</th>
                {showOrderInfo ? <th className="px-4 py-3">Order</th> : null}
                <th className="px-4 py-3">AB</th>
                <th className="px-4 py-3">Reason</th>
                <th className="px-4 py-3">PC/Thr</th>
                <th className="px-4 py-3">Agree</th>
                <th className="px-4 py-3">Tag</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading && limitedRows.length === 0 && (
                <tr>
                  <td colSpan={colN} className="px-4 py-8 text-center text-gray-500">
                    Loading signals…
                  </td>
                </tr>
              )}

              {!isLoading && error && limitedRows.length === 0 && (
                <tr>
                  <td colSpan={colN} className="px-4 py-8 text-center text-red-600">
                    Failed to load signals ({errorText})
                  </td>
                </tr>
              )}

              {!isLoading && limitedRows.map((sig) => {
                const id = String(sig.id ?? '');
                const ingestedMs = toMs(Number((sig as unknown as { ingested_ms?: unknown } | null | undefined)?.ingested_ms ?? 0));
                const emitMs = toMs(Number(sig.ts_emit_ms ?? 0));
                const eventMs = toMs(Number(sig.ts ?? 0));
                const ts = ingestedMs || emitMs || toMs(Number(sig.decision_info?.ts_ms ?? 0)) || eventMs;
                const barCloseMs = toMs(Number(sig.bar_close_ms ?? 0));
                const barOpenMs = toMs(Number(sig.bar_open_ms ?? 0));
                const side = String(sig.side ?? '').toLowerCase();
                const sideText = side ? side.toUpperCase() : '-';

                const tagRaw = (sig as unknown as { tag?: unknown; enter_tag?: unknown; buy_tag?: unknown }).tag
                  ?? (sig as unknown as { enter_tag?: unknown }).enter_tag
                  ?? (sig as unknown as { buy_tag?: unknown }).buy_tag;
                const tagText0 = (tagRaw == null ? '' : String(tagRaw)).trim();
                const tagText = (!tagText0 || tagText0.toLowerCase() === 'nan' || tagText0.toLowerCase() === 'none' || tagText0.toLowerCase() === 'null') ? '-' : tagText0;

                const di = sig.decision_info ?? null;
                const decision = di ? normalizeDecision(di) : '-';
                const diOut = (di as typeof sig.decision_info & { out?: { entry_type?: string } | undefined })?.out;
                const entryType = typeof diOut?.entry_type === 'string' ? diOut.entry_type.toLowerCase() : '';
                const action0 = String((sig as unknown as { action?: unknown } | null | undefined)?.action ?? '').toLowerCase().trim();
                const orderMeta = (() => {
                  if (!showOrderInfo) return { order: undefined as Order | undefined, status: '', error: '' };
                  const eid = String((sig.event_id ?? sig.id) ?? '').trim();
                  const o = eid ? orderByEventId.get(eid) : undefined;
                  if (!o) return { order: undefined as Order | undefined, status: '', error: '' };
                  const st = String(o.status ?? '').trim().toLowerCase();
                  const exObj = (o.exec && typeof o.exec === 'object') ? (o.exec as Record<string, unknown>) : {};
                  const errRaw =
                    (exObj.error != null ? String(exObj.error) : '')
                    || (exObj.preflight_error != null ? String(exObj.preflight_error) : '')
                    || ((o as unknown as { error?: unknown } | null | undefined)?.error != null ? String((o as unknown as { error?: unknown }).error) : '');
                  return { order: o, status: st, error: errRaw.trim() };
                })();
                const decisionEff0 = decision === '-' && action0 ? action0 : decision;
                const decisionEff = (() => {
                  if (orderMeta.status === 'filled' && decisionEff0 === 'observe' && (action0 === 'open' || decision === 'enter')) return 'enter';
                  return decisionEff0;
                })();
                const decisionText = decisionEff === 'enter' && entryType === 'addon' ? 'enter+' : decisionEff;
                const diGate = (di as unknown as { arena?: { gate?: { pass?: unknown; reason?: unknown; n_models_considered?: unknown; n_models?: unknown; n_take?: unknown } } } | null | undefined)?.arena?.gate;
                const gatePass = typeof diGate?.pass === 'boolean' ? diGate.pass : undefined;
                const gateReason = typeof diGate?.reason === 'string' ? diGate.reason : '';
                const reasonRaw = (() => {
                  const rtb = (sig as unknown as { trigger_block_reason?: unknown } | null | undefined)?.trigger_block_reason;
                  if (rtb != null && String(rtb).trim()) return String(rtb);
                  const r1 = (di as unknown as { reason?: unknown } | null | undefined)?.reason;
                  if (r1 != null && String(r1).trim()) return String(r1);
                  const r2 = (di as unknown as { out?: { reason?: unknown } } | null | undefined)?.out?.reason;
                  if (r2 != null && String(r2).trim()) return String(r2);
                  const r3 = (sig as unknown as { reason?: unknown } | null | undefined)?.reason;
                  if (r3 != null && String(r3).trim()) return String(r3);
                  return '';
                })();
                const hasDecision = Boolean((di as unknown as { decision?: unknown } | null | undefined)?.decision != null && String((di as unknown as { decision?: unknown }).decision ?? '').trim());
                const reasonKey0 = (() => {
                  if (orderMeta.status === 'failed' && orderMeta.error) return orderMeta.error;
                  if (!hasDecision && !reasonRaw) return 'decision_not_triggered';
                  if (gatePass === false) return gateReason || reasonRaw || 'arena_gate';
                  if ((decisionEff === 'reject' || decisionEff === 'hold' || decisionEff === 'error') && !reasonRaw && gateReason) return gateReason;
                  return reasonRaw;
                })();
                const reasonKey = (() => {
                  const k = String(reasonKey0 ?? '').trim().toLowerCase();
                  if (orderMeta.status === 'filled' && k === 'arena_no_taker') return '';
                  return reasonKey0;
                })();
                const reasonFmt = formatReason(reasonKey, decisionEff);
                const ab = formatAb(sig);

                type ArenaModelView = { pc?: unknown; take?: unknown; weight?: unknown; eligible?: unknown };
                const arenaModelsPrimary = ((sig as unknown as { arena?: { models?: unknown } } | null | undefined)?.arena?.models ?? {}) as Record<string, ArenaModelView | undefined>;
                const refArena = (di as unknown as { arena?: { ref?: unknown } } | null | undefined)?.arena?.ref as Record<string, unknown> | undefined;
                const refModels = (refArena?.models ?? (refArena?.arena && typeof refArena.arena === 'object' ? (refArena.arena as Record<string, unknown>).models : undefined) ?? (di as unknown as { arena?: { models?: unknown } } | null | undefined)?.arena?.models ?? {}) as Record<string, ArenaModelView | undefined>;
                const arenaModels = (arenaModelsPrimary && Object.keys(arenaModelsPrimary).length > 0 ? arenaModelsPrimary : refModels) as Record<string, ArenaModelView | undefined>;
                const arenaChosen = (sig as unknown as { arena?: { chosen?: unknown } } | null | undefined)?.arena?.chosen;
                const chosenId = typeof arenaChosen === 'string' && arenaChosen.trim() ? arenaChosen.trim() : null;
                const chosenPcRaw = chosenId ? arenaModels?.[chosenId]?.pc : undefined;
                const diArenaAggPcRaw = (di as unknown as { arena?: { agg?: { pc_weighted?: unknown; pc_mean?: unknown } } } | null | undefined)?.arena?.agg?.pc_weighted
                  ?? (di as unknown as { arena?: { agg?: { pc_mean?: unknown } } } | null | undefined)?.arena?.agg?.pc_mean;
                const pcN = Number(di?.pc ?? chosenPcRaw ?? diArenaAggPcRaw ?? NaN);
                const diArenaAggThrRaw = (di as unknown as { arena?: { agg?: { threshold?: unknown } } } | null | undefined)?.arena?.agg?.threshold;
                const thrN = Number(di?.threshold ?? diArenaAggThrRaw ?? (sig as unknown as { arena?: { threshold?: unknown } } | null | undefined)?.arena?.threshold ?? NaN);
                const pc = Number.isFinite(pcN) ? pcN : null;
                const thr = Number.isFinite(thrN) ? thrN : null;

                const arenaThr = Number((sig as unknown as { arena?: { threshold?: unknown } } | null | undefined)?.arena?.threshold
                  ?? (refArena?.threshold ?? (refArena?.arena && typeof refArena.arena === 'object' ? (refArena.arena as Record<string, unknown>).threshold : undefined))
                  ?? NaN);
                const useThr = Number.isFinite(arenaThr) && arenaThr > 0 ? arenaThr : NaN;
                const models = arenaModels ?? {};
                const voteRows = Object.entries(models).map(([, m]) => {
                  const eligible = m?.eligible == null ? true : Boolean(m.eligible);
                  const take = Boolean(m?.take);
                  const pc = Number(m?.pc ?? NaN);
                  const voteAgree = (typeof m?.take === 'boolean')
                    ? Boolean(m.take)
                    : (eligible && Number.isFinite(useThr) ? pc >= useThr : take);
                  return { eligible, voteAgree };
                });
                const eligibleN = voteRows.filter((r) => r.eligible).length;
                const refGate = (refArena?.gate ?? (refArena?.arena && typeof refArena.arena === 'object' ? (refArena.arena as Record<string, unknown>).gate : undefined)) as Record<string, unknown> | undefined;
                const aggGate = (di as unknown as { arena?: { agg?: unknown } } | null | undefined)?.arena?.agg as Record<string, unknown> | undefined;
                const denomFromGate = Number(diGate?.n_models_considered ?? diGate?.n_models ?? refGate?.n_models_considered ?? refGate?.n_models ?? aggGate?.n_models ?? NaN);
                const agreeFromGate = Number(diGate?.n_take ?? refGate?.n_take ?? aggGate?.n_take ?? NaN);
                const denomN = Number.isFinite(denomFromGate) && denomFromGate > 0 ? denomFromGate : (eligibleN > 0 ? eligibleN : voteRows.length);
                const agreeN = Number.isFinite(agreeFromGate) && agreeFromGate >= 0 ? agreeFromGate : voteRows.filter((r) => r.eligible && r.voteAgree).length;

                const modelTitle = (() => {
                  const models = arenaModels ?? {};
                  const arenaThr = Number((sig as unknown as { arena?: { threshold?: unknown } } | null | undefined)?.arena?.threshold ?? NaN);
                  const useThr = Number.isFinite(arenaThr) && arenaThr > 0 ? arenaThr : NaN;
                  const entries = Object.entries(models)
                    .map(([k, m]) => ({
                      id: k,
                      pc: Number(m?.pc ?? 0),
                      take: Boolean(m?.take),
                      weight: Number(m?.weight ?? 0),
                      eligible: m?.eligible == null ? true : Boolean(m.eligible),
                      voteAgree: false,
                    }))
                    .map((e) => {
                      const pc = Number(e.pc ?? NaN);
                      const eligible = Boolean(e.eligible);
                      const voteAgree = (typeof e.take === 'boolean')
                        ? Boolean(e.take)
                        : (eligible && Number.isFinite(useThr) ? pc >= useThr : Boolean(e.take));
                      return { ...e, voteAgree };
                    })
                    .sort((a, b) => b.pc - a.pc)
                    .slice(0, 8);
                  if (!entries.length) return '';
                  return entries
                    .map((e) => {
                      const status = e.eligible ? (e.voteAgree ? 'agree' : 'veto') : 'ineligible';
                      return `${e.id}: pc=${e.pc.toFixed(3)} w=${e.weight.toFixed(3)} ${status}`.trim();
                    })
                    .join('\n');
                })();

                const decisionCls = (() => {
                  if (decisionEff === 'enter') return 'text-emerald-700 font-semibold';
                  if (decisionEff === 'reject' || decisionEff === 'error') return 'text-rose-700 font-semibold';
                  if (decisionEff === 'hold') return 'text-slate-700 font-semibold';
                  return 'text-slate-500';
                })();

                return (
                  <tr key={id || String(ts)} className="hover:bg-slate-50/50">
                    <td className="px-4 py-3 text-gray-500">
                      <span
                        title={[
                          ingestedMs ? `ingested: ${new Date(ingestedMs).toLocaleString()}` : '',
                          emitMs ? `emit: ${new Date(emitMs).toLocaleString()}` : '',
                          barOpenMs ? `bar_open: ${new Date(barOpenMs).toLocaleString()}` : '',
                          barCloseMs ? `bar_close: ${new Date(barCloseMs).toLocaleString()}` : '',
                          eventMs ? `event_ts: ${new Date(eventMs).toLocaleString()}` : '',
                        ].filter(Boolean).join('\n') || undefined}
                      >
                        {ts ? new Date(ts).toLocaleTimeString() : '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {sig.pair}
                    </td>
                    <td className={clsx("px-4 py-3 font-semibold", {
                      "text-green-600": side === 'long',
                      "text-red-600": side === 'short'
                    })}>
                      {sideText}
                    </td>
                    <td className={clsx('px-4 py-3', decisionCls)}>
                      {decisionText}
                    </td>
                    {showOrderInfo ? (
                      <td className="px-4 py-3 text-gray-500 font-mono">
                        {(() => {
                          const eid = String((sig.event_id ?? sig.id) ?? '').trim();
                          const o = eid ? orderByEventId.get(eid) : undefined;
                          if (!o) return '-';
                          const exObj = (o.exec && typeof o.exec === 'object') ? (o.exec as Record<string, unknown>) : {};
                          const ex = (() => {
                            const v = o.exchange ?? exObj.venue ?? exObj.exchange;
                            const s = v == null ? '' : String(v).trim();
                            return s;
                          })();
                          const oid = (() => {
                            const v = o.exchange_oid ?? exObj.oid;
                            const s = v == null ? '' : String(v).trim();
                            return s;
                          })();
                          const st = (() => {
                            const v = o.status;
                            const s = v == null ? '' : String(v).trim().toLowerCase();
                            return s;
                          })();
                          const left = st || '-';
                          const right = ex ? `${ex}${oid ? `/${oid}` : ''}` : '-';
                          return `${left} · ${right}`;
                        })()}
                      </td>
                    ) : null}
                    <td className="px-4 py-3 text-gray-600 truncate max-w-[160px]" title={ab.title || undefined}>
                      {ab.text || '-'}
                    </td>
                    <td className="px-4 py-3 text-gray-600 truncate max-w-[220px]" title={reasonFmt.raw || reasonKey || undefined}>
                      {reasonFmt.text || '-'}
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {pc != null && thr != null ? `${pc.toFixed(3)}/${thr.toFixed(3)}` : '-'}
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      <span title={modelTitle}>
                        {denomN > 0 ? `${agreeN}/${denomN}` : '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {tagText}
                    </td>
                  </tr>
                );
              })}

              {!isLoading && rows.length === 0 && !error && (
                <tr>
                  <td colSpan={colN} className="px-4 py-8 text-center text-gray-500">
                    No signals received yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
};
