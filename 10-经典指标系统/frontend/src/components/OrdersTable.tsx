
import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchRecentOrdersWithParams, getUiEnv, type Order } from '../lib/api';
import { isOrderShadowLike, isOrderSimulatedLike } from '../lib/ordersUi';
import { useOrdersUiPrefs } from '../lib/ordersUiPrefs';
import { ShoppingCart } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from './ui/card';
import { clsx } from 'clsx';

const _inferOrderAction = (order: unknown): string => {
  const sideRaw = String((order as { side?: unknown } | null | undefined)?.side ?? '').toLowerCase().trim();
  const posSnapshot = (order as { pos_snapshot?: unknown } | null | undefined)?.pos_snapshot as Record<string, unknown> | undefined;
  const sideFromPos = typeof posSnapshot?.side === 'string' ? String(posSnapshot.side).toLowerCase().trim() : '';
  const side = (sideRaw === 'long' || sideRaw === 'short') ? sideRaw : ((sideFromPos === 'long' || sideFromPos === 'short') ? sideFromPos : sideRaw);
  const entryType = String((order as { entry_type?: unknown } | null | undefined)?.entry_type ?? '').toLowerCase().trim();
  const actionRaw = String((order as { action?: unknown } | null | undefined)?.action ?? '').toLowerCase().trim();
  const tagRaw = typeof (order as { tag?: unknown } | null | undefined)?.tag === 'string' ? String((order as { tag?: unknown }).tag) : '';
  if (actionRaw === 'open' || actionRaw === 'close' || actionRaw === 'reduce') return actionRaw;
  if (side === 'close') return 'close';
  if (tagRaw.includes('market_close')) return 'close';
  if (tagRaw.includes('reduce')) return 'reduce';
  if (entryType === 'addon') return 'addon';
  return 'open';
};

const _formatAbMeta = (o: unknown): { text: string; title: string } => {
  const ocRaw = (o as { owner_contrib?: unknown } | null | undefined)?.owner_contrib;
  const abOwnerRaw = (o as { ab_owner?: unknown } | null | undefined)?.ab_owner;
  const settleRaw = (o as { ab_settlement?: unknown } | null | undefined)?.ab_settlement as
    | { pnl_by_owner?: unknown; notional_by_owner?: unknown; last_ts?: unknown }
    | undefined;

  const parts: string[] = [];
  const titleParts: string[] = [];

  const oc = (ocRaw && typeof ocRaw === 'object') ? (ocRaw as Record<string, unknown>) : null;
  if (oc) {
    const s = Number(oc.strategy ?? NaN);
    const q = Number(oc.quant ?? NaN);
    const c = Number(oc.carry ?? NaN);
    if (Number.isFinite(s) || Number.isFinite(q) || Number.isFinite(c)) {
      parts.push(`S:${Number.isFinite(s) ? s.toFixed(0) : '-'}`);
      parts.push(`Q:${Number.isFinite(q) ? q.toFixed(0) : '-'}`);
      parts.push(`C:${Number.isFinite(c) ? c.toFixed(0) : '-'}`);
      titleParts.push(`owner_contrib=${JSON.stringify(oc)}`);
    }
  }

  const abOwner = (abOwnerRaw == null ? '' : String(abOwnerRaw)).trim();
  if (abOwner) {
    if (parts.length === 0) parts.push(abOwner);
    titleParts.push(`ab_owner=${abOwner}`);
  }

  if (settleRaw && typeof settleRaw === 'object') {
    const pnl = (settleRaw as { pnl_by_owner?: unknown }).pnl_by_owner;
    const pnlObj = (pnl && typeof pnl === 'object') ? (pnl as Record<string, unknown>) : null;
    if (pnlObj) {
      const s = Number(pnlObj.strategy ?? NaN);
      const q = Number(pnlObj.quant ?? NaN);
      const c = Number(pnlObj.carry ?? NaN);
      if (Number.isFinite(s) || Number.isFinite(q) || Number.isFinite(c)) {
        titleParts.push(`settle_pnl=${JSON.stringify(pnlObj)}`);
        if (parts.length === 0) {
          parts.push(`PnL S:${Number.isFinite(s) ? s.toFixed(1) : '-'}`);
          parts.push(`Q:${Number.isFinite(q) ? q.toFixed(1) : '-'}`);
          parts.push(`C:${Number.isFinite(c) ? c.toFixed(1) : '-'}`);
        }
      }
    }
  }

  return { text: parts.join(' '), title: titleParts.join('\n') };
};

export const OrdersTable: React.FC<{
  abOwner?: string;
  bookId?: string;
  strategyId?: string;
  groupId?: string;
  pair?: string;
  title?: string;
  displayLimit?: number;
  actionGroup?: 'all' | 'entry' | 'exit';
  includeShadow?: boolean;
}> = ({ abOwner, bookId, strategyId, groupId, pair, title, displayLimit, actionGroup = 'all', includeShadow }) => {
  const { showShadow, setShowShadow, showSimulated, setShowSimulated } = useOrdersUiPrefs({
    scope: 'orders_table',
    defaults: { showShadow: (includeShadow ?? (getUiEnv() === 'explore')) },
  });
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
  const limitEff = useMemo(() => {
    const n = Number(displayLimit ?? 20);
    if (!Number.isFinite(n)) return 20;
    return Math.min(200, Math.max(1, Math.floor(n)));
  }, [displayLimit]);
  const fetchLimitEff = useMemo(() => Math.min(80, Math.max(20, limitEff * 4)), [limitEff]);
  const { data: orders, isLoading, error, isFetching, dataUpdatedAt } = useQuery({ 
    queryKey: ['orders', 'recent', abOwnerEff ?? '', bookIdEff ?? '', strategyId ?? '', groupId ?? '', pair ?? '', fetchLimitEff], 
    queryFn: () => fetchRecentOrdersWithParams({
      limit: fetchLimitEff,
      ab_owner: abOwnerEff,
      book_id: bookIdEff,
      allow_book_id_missing: (bookIdEff === 'three_screen' ? 0 : 1),
      no_default_filter: ((abOwnerEff || bookIdEff) ? 0 : 1),
      no_event_backfill: 1,
      strategy_id: strategyId,
      group_id: groupId,
      pair,
    }),
    refetchInterval: 15000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const allRows = useMemo(() => {
    const raw = Array.isArray(orders) ? orders : [];
    const rows = raw.filter((o): o is Order => Boolean(o) && typeof o === 'object');
    const _toMs = (v: unknown): number => {
      const n = Number(v ?? NaN);
      if (!Number.isFinite(n) || n <= 0) return 0;
      return n < 1_000_000_000_000 ? n * 1000 : n;
    };
    const tsOf = (o: Order): number => {
      const view = o as unknown as { ingested_ms?: unknown; ts_emit_ms?: unknown; received_ms?: unknown; created_ms?: unknown; ts?: unknown };
      return (
        _toMs(view.ingested_ms)
        || _toMs(view.ts_emit_ms)
        || _toMs(view.received_ms)
        || _toMs(view.created_ms)
        || _toMs(view.ts)
      );
    };
    const priority = (o: Order): number => {
      const status = String(o.status ?? '').toLowerCase().trim();
      const mode = String(o.mode ?? '').toLowerCase().trim();
      let p = 0;
      if (status === 'filled' || status === 'closed' || status === 'done' || status === 'completed' || status === 'success') p += 20;
      else if (status === 'partial' || status === 'partially_filled' || status === 'partially-filled') p += 10;
      else if (status === 'open' || status === 'new' || status === 'accepted') p += 5;
      if (mode === 'real') p += 3;
      else if (mode.includes('dry') || mode.includes('paper') || mode.includes('sim')) p -= 1;
      return p;
    };
    const dedupKey = (o: Order): string | null => {
      const view = o as unknown as {
        exec?: unknown;
        venue?: unknown;
        exchange_order_id?: unknown;
        exchange_oid?: unknown;
        oid?: unknown;
        base_event_id?: unknown;
      };
      const exec = (view.exec && typeof view.exec === 'object' ? (view.exec as Record<string, unknown>) : null);
      const exchange = String(o.exchange ?? view.venue ?? exec?.venue ?? exec?.exchange ?? '').toLowerCase().trim();
      const exOid = String(view.exchange_order_id ?? o.exchange_oid ?? view.exchange_oid ?? view.oid ?? exec?.oid ?? '').trim();
      if (exchange && exOid) return `exoid:${exchange}:${exOid}`;
      const id = String(o.id ?? '').trim();
      if (id) return `id:${id}`;
      const eventId = String(o.event_id ?? view.base_event_id ?? '').trim();
      if (eventId) {
        const action = String(o.action ?? '').toLowerCase().trim();
        const pair0 = String(o.pair ?? '').toUpperCase().trim();
        const side0 = String(o.side ?? '').toLowerCase().trim();
        return `eid:${eventId}:${action}:${pair0}:${side0}`;
      }
      return null;
    };
    const m = new Map<string, Order>();
    const anon: Order[] = [];
    for (const r of rows) {
      const k = dedupKey(r);
      if (!k) {
        anon.push(r);
        continue;
      }
      const cur = m.get(k);
      if (!cur) {
        m.set(k, r);
        continue;
      }
      const tsNew = tsOf(r);
      const tsCur = tsOf(cur);
      if (tsNew > tsCur) m.set(k, r);
      else if (tsNew === tsCur && priority(r) >= priority(cur)) m.set(k, r);
    }
    const out = [...m.values(), ...anon];
    out.sort((a, b) => tsOf(b) - tsOf(a));
    return out;
  }, [orders]);
  const nonShadowRows = useMemo(
    () => allRows.filter((o) => !isOrderShadowLike(o)),
    [allRows]
  );
  const nonShadowNonSimRows = useMemo(
    () => nonShadowRows.filter((o) => !isOrderSimulatedLike(o)),
    [nonShadowRows]
  );
  const rows = showShadow ? (showSimulated ? allRows : allRows.filter((o) => !isOrderSimulatedLike(o))) : (showSimulated ? nonShadowRows : nonShadowNonSimRows);
  const filteredRows = useMemo(() => {
    if (actionGroup === 'all') return rows;
    if (actionGroup === 'entry') {
      return rows.filter((o) => {
        const a = _inferOrderAction(o);
        return a === 'open' || a === 'addon';
      });
    }
    if (actionGroup === 'exit') {
      return rows.filter((o) => {
        const a = _inferOrderAction(o);
        return a === 'close' || a === 'reduce' || a === 'stop';
      });
    }
    return rows;
  }, [actionGroup, rows]);
  const displayRows = useMemo(() => filteredRows.slice(0, limitEff), [filteredRows, limitEff]);

  const shadowOnlyHint = (!showShadow && allRows.length > 0 && nonShadowRows.length === 0);
  const simulatedOnlyHint = (!showSimulated && allRows.length > 0 && (showShadow ? allRows.filter((o) => !isOrderSimulatedLike(o)).length === 0 : nonShadowNonSimRows.length === 0));
  const errorText = (() => {
    const e = error as unknown as { message?: unknown; response?: { status?: unknown } } | null | undefined;
    const status = e?.response?.status;
    const msg = typeof e?.message === 'string' ? e.message : '';
    if (status != null) return `${String(status)}${msg ? `: ${msg}` : ''}`;
    return msg || 'Request failed';
  })();
  const lastOkText = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString() : '';

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-lg font-medium">{title ?? 'Recent Orders'}</CardTitle>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className={clsx(
              'px-2 py-1 rounded text-xs border',
              showShadow ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-700 border-slate-200'
            )}
            onClick={() => {
              setShowShadow((v) => !v);
            }}
          >
            {showShadow ? '含 shadow' : '不含 shadow'}
          </button>
          <button
            type="button"
            className={clsx(
              'px-2 py-1 rounded text-xs border',
              showSimulated ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-700 border-slate-200'
            )}
            onClick={() => setShowSimulated((v) => !v)}
          >
            {showSimulated ? '含模拟盘' : '不含模拟盘'}
          </button>
          {isFetching ? <span className="text-xs text-slate-500">Updating…</span> : null}
          <ShoppingCart className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardHeader>
      <CardContent>
        {shadowOnlyHint ? (
          <div className="mb-2 text-xs text-slate-600">
            当前只有 shadow/observed 订单（影子模式不真实下单）
          </div>
        ) : null}
        {simulatedOnlyHint ? (
          <div className="mb-2 text-xs text-slate-600">
            当前只有模拟盘（dry-run）订单（可切换“含模拟盘”查看）
          </div>
        ) : null}
        {!isLoading && error && displayRows.length > 0 ? (
          <div className="mb-2 text-xs text-rose-700">
            Backend unreachable · showing cached data{lastOkText ? ` (last ok: ${lastOkText})` : ''}
          </div>
        ) : null}
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs text-gray-500 uppercase bg-gray-50/50">
              <tr>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">Time</th>
                <th className="px-4 py-3">Pair</th>
                <th className="px-4 py-3">Side</th>
                <th className="px-4 py-3">Action</th>
                <th className="px-4 py-3">Trigger</th>
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3">AB</th>
                <th className="px-4 py-3">Size</th>
                <th className="px-4 py-3">Lev</th>
                <th className="px-4 py-3">EX / OID</th>
                <th className="px-4 py-3">Prob / Calib</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Mode</th>
                <th className="px-4 py-3">Gate</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && displayRows.length === 0 && (
                <tr>
                  <td colSpan={15} className="px-4 py-8 text-center text-gray-500">
                    Loading orders…
                  </td>
                </tr>
              )}

              {!isLoading && error && displayRows.length === 0 && (
                <tr>
                  <td colSpan={15} className="px-4 py-8 text-center text-red-600">
                    Failed to load orders ({errorText})
                  </td>
                </tr>
              )}

              {!isLoading && displayRows.map((order) => {
                const id = String(order.id ?? '');
                const shortId = (() => {
                  if (!id) return '';
                  if (id.startsWith('ord_')) {
                    const parts = id.split('_');
                    if (parts.length >= 3 && parts[1]) {
                      const ms = parts[1];
                      const seq = parts.slice(2).join('_');
                      return `${ms.slice(-10)}_${seq}`;
                    }
                    return id.slice(0, 14);
                  }
                  if (id.length <= 12) return id;
                  return `${id.slice(0, 6)}…${id.slice(-4)}`;
                })();
                const sideRaw = String(order.side ?? '').toLowerCase().trim();
                const posSnapshot = (order as unknown as { pos_snapshot?: unknown }).pos_snapshot as Record<string, unknown> | undefined;
                const sideFromPos = typeof posSnapshot?.side === 'string' ? String(posSnapshot.side).toLowerCase().trim() : '';
                const side = (sideRaw === 'long' || sideRaw === 'short') ? sideRaw : ((sideFromPos === 'long' || sideFromPos === 'short') ? sideFromPos : sideRaw);
                const sideText = (side === 'long' || side === 'short') ? side.toUpperCase() : (sideRaw ? sideRaw.toUpperCase() : '-');
                const entryType = String((order as unknown as { entry_type?: unknown }).entry_type ?? '').toLowerCase();
                const actionRaw = String((order as unknown as { action?: unknown }).action ?? '').toLowerCase().trim();
                const tagRaw = typeof (order as unknown as { tag?: unknown }).tag === 'string' ? String((order as unknown as { tag?: unknown }).tag) : '';
                const strategyId = String((order as unknown as { strategy_id?: unknown }).strategy_id ?? '').trim();
                const groupId = String((order as unknown as { group_id?: unknown }).group_id ?? '').trim();
                const eventId = String((order as unknown as { event_id?: unknown }).event_id ?? '').trim();
                const action = (() => {
                  if (actionRaw === 'open' || actionRaw === 'close' || actionRaw === 'reduce') return actionRaw;
                  if (sideRaw === 'close') return 'close';
                  if (tagRaw.includes('market_close')) return 'close';
                  if (tagRaw.includes('reduce')) return 'reduce';
                  if (entryType === 'addon') return 'addon';
                  return 'open';
                })();
                const p = Number((order as unknown as { p?: unknown }).p ?? 0);
                const pc = Number((order as unknown as { pc?: unknown }).pc ?? 0);
                const ts = Number((order as unknown as { ts?: unknown }).ts ?? 0);
                const gate = (order as unknown as { gate?: unknown }).gate as Record<string, unknown> | undefined;
                const gateOk = typeof gate?.ok === 'boolean' ? (gate?.ok as boolean) : undefined;
                const gatePass = typeof gate?.pass === 'boolean' ? (gate?.pass as boolean) : undefined;
                const gateReason = typeof gate?.reason === 'string' ? (gate?.reason as string) : undefined;
                const execExecute = (order.exec as Record<string, unknown> | undefined)?.execute;
                const execFlag = typeof execExecute === 'boolean' ? (execExecute as boolean) : undefined;
                const execObj = (order.exec ?? {}) as Record<string, unknown>;
                const execErr = typeof execObj.error === 'string' ? String(execObj.error) : '';
                const execErrKind = typeof execObj.error_kind === 'string' ? String(execObj.error_kind) : '';
                const execErrCode = (() => {
                  const v = execObj.code;
                  const n = Number(v ?? NaN);
                  return Number.isFinite(n) ? n : null;
                })();
                const execHint = typeof execObj.hint === 'string' ? String(execObj.hint) : '';
                const execNoPos = Boolean(execObj.no_position);
                const qtyCapped = Boolean(execObj.qty_capped);
                const effectiveNotional = Number(execObj.effective_notional_usdc ?? NaN);
                const qty = Number(execObj.qty ?? NaN);
                const maxQty = Number(execObj.max_qty ?? NaN);
                const capReason = typeof execObj.qty_cap_reason === 'string' ? String(execObj.qty_cap_reason) : '';
                const effectiveFrac = Number(execObj.effective_frac ?? NaN);
                const leverage = (() => {
                  const v = execObj.leverage ?? (order as unknown as { leverage?: unknown }).leverage;
                  const x = Number(v ?? NaN);
                  return Number.isFinite(x) ? x : null;
                })();
                const exchange = (() => {
                  const ex = (order as unknown as { exchange?: unknown }).exchange;
                  if (ex != null && String(ex).trim()) return String(ex);
                  const v = execObj.venue ?? execObj.exchange ?? (order as unknown as { venue?: unknown }).venue;
                  if (v != null && String(v).trim()) return String(v);
                  return '';
                })();
                const exchangeOid = (() => {
                  const top = (order as unknown as { exchange_oid?: unknown }).exchange_oid;
                  if (top != null && String(top).trim()) return String(top);
                  const v = execObj.oid;
                  if (v != null && String(v).trim()) return String(v);
                  return '';
                })();
                const runtimeCfg = (execObj.runtime_config && typeof execObj.runtime_config === 'object')
                  ? (execObj.runtime_config as Record<string, unknown>)
                  : null;
                const runtimeCfgVer = runtimeCfg?.runtime_config_version;
                const runtimeCfgTitle = runtimeCfg ? `runtime_config=${JSON.stringify(runtimeCfg)}` : '';
                const statusRaw = String(order.status ?? '').toLowerCase().trim();
                const nonFatalNoPos = execNoPos || /reduceonly\s+order\s+is\s+rejected|-2022|no\s+position|position\s+is\s+zero|position_amt\s*<=\s*0/i.test(execErr);
                const displayStatus = (() => {
                  if (statusRaw === 'failed' && (action === 'close' || action === 'reduce') && nonFatalNoPos) return 'ignored';
                  if (statusRaw === 'ignored_not_owner') return 'ignored';
                  return statusRaw || 'unknown';
                })();
                const capInfo = (() => {
                  if (!qtyCapped) return '';
                  const parts: string[] = ['qty_capped=true'];
                  if (capReason) parts.push(`reason=${capReason}`);
                  if (Number.isFinite(qty)) parts.push(`qty=${qty}`);
                  if (Number.isFinite(maxQty)) parts.push(`max_qty=${maxQty}`);
                  if (Number.isFinite(effectiveNotional)) parts.push(`effective_notional=${effectiveNotional.toFixed(2)}`);
                  if (Number.isFinite(effectiveFrac)) parts.push(`effective_frac=${(effectiveFrac * 100).toFixed(1)}%`);
                  return parts.join(' ');
                })();
                const statusTitle = [
                  execErr,
                  (execErrKind ? `kind=${execErrKind}` : ''),
                  (execErrCode == null ? '' : `code=${execErrCode}`),
                  (execHint ? `hint=${execHint}` : ''),
                  capInfo,
                ].filter(Boolean).join('\n');
                const ab = _formatAbMeta(order);
                return (
                  <tr key={id || String(ts)} className="border-b last:border-0 hover:bg-slate-50/50">
                    <td className="px-4 py-3 font-mono text-gray-500" title={id}>
                      {shortId || '-'}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {ts ? new Date(ts).toLocaleTimeString() : '-'}
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {order.pair}
                    </td>
                    <td className={clsx("px-4 py-3 font-semibold", {
                      "text-green-600": side === 'long',
                      "text-red-600": side === 'short'
                    })}>
                      {sideText}
                    </td>
                    <td className="px-4 py-3">
                      <span className={clsx('px-2 py-0.5 rounded text-xs font-medium', {
                        'bg-slate-100 text-slate-700': action === 'open',
                        'bg-indigo-100 text-indigo-800': action === 'addon',
                        'bg-amber-100 text-amber-800': action === 'reduce',
                        'bg-orange-100 text-orange-800': action === 'close',
                      })}>
                        {action === 'addon' ? 'ADD' : action.toUpperCase()}
                      </span>
                    </td>
                    <td
                      className="px-4 py-3 text-xs text-slate-700 max-w-[220px]"
                      title={[
                        (strategyId ? `strategy_id=${strategyId}` : ''),
                        (groupId ? `group_id=${groupId}` : ''),
                        (tagRaw ? `tag=${tagRaw}` : ''),
                        (eventId ? `event_id=${eventId}` : ''),
                      ].filter(Boolean).join('\n') || undefined}
                    >
                      <div className="truncate font-medium">{tagRaw || '-'}</div>
                      <div className="truncate text-[11px] text-slate-500">
                        {[strategyId, groupId].filter(Boolean).join(' / ') || '-'}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-500 truncate max-w-[160px]" title={order.model ?? ''}>
                      {order.model ?? '-'}
                    </td>
                    <td className="px-4 py-3 text-gray-500 truncate max-w-[160px]" title={ab.title || undefined}>
                      {ab.text || '-'}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {(() => {
                        const sRaw = (order as unknown as { size?: unknown }).size;
                        const sText = String(sRaw ?? '-');
                        if (qtyCapped && Number.isFinite(effectiveNotional) && sText !== '-') {
                          return (
                            <span title={capInfo || undefined}>
                              {sText} → {effectiveNotional.toFixed(2)}
                              <span className="ml-1 text-[10px] text-amber-700">cap</span>
                            </span>
                          );
                        }
                        return <span title={capInfo || undefined}>{sText}</span>;
                      })()}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {leverage == null ? '-' : `${leverage}x`}
                    </td>
                    <td className="px-4 py-3 text-gray-500 font-mono">
                      {exchange ? String(exchange) : '-'}
                      {exchangeOid ? ` / ${exchangeOid}` : (exchange && execFlag === false ? ' / -' : (exchange ? ' / -' : ''))}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {Number.isFinite(p) ? p.toFixed(2) : '-'} / <span className="font-semibold text-slate-700">{Number.isFinite(pc) ? pc.toFixed(2) : '-'}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={clsx("px-2.5 py-0.5 rounded-full text-xs font-medium", {
                        "bg-green-100 text-green-800": displayStatus === 'filled' || displayStatus === 'submitted',
                        "bg-yellow-100 text-yellow-800": displayStatus === 'accepted',
                        "bg-red-100 text-red-800": displayStatus === 'failed' || displayStatus === 'cancelled',
                        "bg-slate-100 text-slate-700": displayStatus === 'ignored'
                      })}>
                        <span title={statusTitle || undefined}>{displayStatus}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      <span title={runtimeCfgTitle || undefined}>{order.mode}</span>
                      {runtimeCfgVer ? <span className="ml-1 text-[10px] text-slate-500">cfg</span> : null}
                      {execFlag === true ? <span className="ml-1 text-xs text-emerald-700">exec</span> : null}
                      {execFlag === false ? <span className="ml-1 text-xs text-slate-500">no-exec</span> : null}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className={clsx("px-2 py-0.5 rounded text-xs font-semibold", {
                          "bg-green-100 text-green-800": gateOk === true || gatePass === true,
                          "bg-red-100 text-red-800": gateOk === false || gatePass === false,
                          "bg-slate-100 text-slate-600": gateOk === undefined && gatePass === undefined,
                        })}>
                          {(gateOk === true || gatePass === true) ? 'PASS' : (gateOk === false || gatePass === false) ? 'BLOCK' : '-'}
                        </span>
                        <span className="text-xs text-slate-500 truncate max-w-[160px]" title={gateReason ?? ''}>
                          {gateReason ?? ''}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}

              {!isLoading && rows.length === 0 && !error && (
                <tr>
                  <td colSpan={15} className="px-4 py-8 text-center text-gray-500">
                    No recent orders found
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
