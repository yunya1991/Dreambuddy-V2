'use client';

import React, { useState } from 'react';
import { venue, type VenueOrderIntent, type VenueOrderReceipt } from '@/lib/venue-client';
import { ProductLockedNotice, useProductEntitlement } from '@/components/features/product/ProductGate';
import { V3Card, V3Button, V3Badge } from '@/components';

// 产品内下单票据（SPEC-52 F2）
// 两步式：先落 order_intent 草稿，人工确认后才经 51 用户 venue 下单。
// 该通道与后端 11 旁路隔离：不走 polling_trader，也不影响后端自有链路。
const EMPTY_FORM = {
  instId: 'BTC-USDT',
  side: 'buy' as 'buy' | 'sell',
  orderType: 'market' as 'market' | 'limit',
  size: '',
  price: '',
  posSide: '' as '' | 'long' | 'short',
  tdMode: '' as '' | 'cross' | 'isolated' | 'cash',
};

function friendlyError(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  if (/requires api credentials|configure okx_api_key|venue_credentials_missing/i.test(message)) {
    return '用户交易 API 未配置：请到「通用设置 → 用户交易 API」填写并验证后重试。';
  }
  if (/bridge_unreachable|bridge_token_missing/i.test(message)) {
    return '本地 51 venue bridge 未启动，请在 51-OKX CLI 系统 下执行 `python3 -m okx_venue.server`。';
  }
  if (/live_trading_forbidden/i.test(message)) {
    return '实盘解锁窗口已关闭，请到「通用设置 → 交易场所账户」重新解锁。';
  }
  return message;
}

export function OrderTicketPanel() {
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [intent, setIntent] = useState<VenueOrderIntent | null>(null);
  const [receipt, setReceipt] = useState<VenueOrderReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { entitled } = useProductEntitlement();

  const isSwap = form.instId.toUpperCase().endsWith('-SWAP');
  const inputCls =
    'w-full bg-gray-900/60 border border-gray-700/50 rounded-md px-2 py-1.5 text-xs text-gray-200';

  const update = (patch: Partial<typeof form>) => {
    setForm((prev) => ({ ...prev, ...patch }));
    setIntent(null);
    setReceipt(null);
    setError(null);
  };

  const handleDraft = async () => {
    setError(null);
    setReceipt(null);
    const size = Number(form.size);
    if (!form.instId.trim() || !Number.isFinite(size) || size <= 0) {
      setError('标的与数量为必填，数量需大于 0');
      return;
    }
    if (form.orderType === 'limit' && !(Number(form.price) > 0)) {
      setError('限价单必须填写有效价格');
      return;
    }
    setBusy(true);
    try {
      const draft = await venue.createIntent({
        inst_id: form.instId.trim().toUpperCase(),
        side: form.side,
        size,
        order_type: form.orderType,
        price: form.orderType === 'limit' ? Number(form.price) : undefined,
        td_mode: form.tdMode || undefined,
        pos_side: isSwap && form.posSide ? form.posSide : undefined,
        source: 'product_ui',
      });
      setIntent(draft);
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  const handleConfirm = async () => {
    if (!intent) return;
    setError(null);
    setBusy(true);
    try {
      const result = await venue.confirmIntent(intent.id);
      setReceipt(result);
      setIntent(result.intent);
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  if (!entitled) {
    return (
      <V3Card
        title="下单票据"
        subtitle="order_intent → 人工确认 → 51 用户 venue"
        actions={<V3Badge variant="default">已锁定</V3Badge>}
        padding="sm"
      >
        <ProductLockedNotice />
      </V3Card>
    );
  }

  return (
    <V3Card
      title="下单票据"
      subtitle="order_intent → 人工确认 → 51 用户 venue"
      actions={<V3Badge variant="info">产品通道</V3Badge>}
      padding="sm"
    >
      {error && (
        <div className="mb-2 text-[11px] text-red-400 px-2 py-1 bg-red-900/20 rounded">{error}</div>
      )}

      <div className="grid grid-cols-2 gap-2">
        <div className="col-span-2">
          <label className="text-[10px] text-gray-500 block mb-1">标的</label>
          <input
            type="text"
            value={form.instId}
            onChange={(e) => update({ instId: e.target.value })}
            placeholder="BTC-USDT 或 BTC-USDT-SWAP"
            className={`${inputCls} font-mono`}
          />
        </div>

        <div>
          <label className="text-[10px] text-gray-500 block mb-1">方向</label>
          <select
            value={form.side}
            onChange={(e) => update({ side: e.target.value as 'buy' | 'sell' })}
            className={inputCls}
          >
            <option value="buy">买入 / 开多</option>
            <option value="sell">卖出 / 开空</option>
          </select>
        </div>

        <div>
          <label className="text-[10px] text-gray-500 block mb-1">类型</label>
          <select
            value={form.orderType}
            onChange={(e) => update({ orderType: e.target.value as 'market' | 'limit' })}
            className={inputCls}
          >
            <option value="market">市价</option>
            <option value="limit">限价</option>
          </select>
        </div>

        <div>
          <label className="text-[10px] text-gray-500 block mb-1">
            数量 {isSwap ? '(张)' : '(币)'}
          </label>
          <input
            type="number"
            value={form.size}
            onChange={(e) => update({ size: e.target.value })}
            placeholder="0"
            className={inputCls}
          />
        </div>

        <div>
          <label className="text-[10px] text-gray-500 block mb-1">
            {form.orderType === 'limit' ? '价格 *' : '价格（市价忽略）'}
          </label>
          <input
            type="number"
            value={form.price}
            onChange={(e) => update({ price: e.target.value })}
            placeholder="0"
            disabled={form.orderType !== 'limit'}
            className={`${inputCls} disabled:opacity-40`}
          />
        </div>

        {isSwap && (
          <div className="col-span-2">
            <label className="text-[10px] text-gray-500 block mb-1">持仓方向（可选）</label>
            <select
              value={form.posSide}
              onChange={(e) => update({ posSide: e.target.value as typeof form.posSide })}
              className={inputCls}
            >
              <option value="">跟随账户默认</option>
              <option value="long">多</option>
              <option value="short">空</option>
            </select>
          </div>
        )}
      </div>

      <div className="mt-2 flex items-center justify-end gap-2">
        <V3Button variant="secondary" size="sm" onClick={handleDraft} loading={busy && !intent}>
          生成草稿
        </V3Button>
        {intent?.status === 'pending' && (
          <V3Button variant="primary" size="sm" onClick={handleConfirm} loading={busy}>
            确认下单
          </V3Button>
        )}
      </div>

      {intent && (
        <div className="mt-2.5 p-2 rounded-lg bg-gray-800/40 border border-gray-700/40 space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-200 font-medium">
              {intent.side === 'buy' ? '买入' : '卖出'} {intent.size} {intent.inst_id}
            </span>
            <V3Badge
              variant={
                intent.status === 'executed'
                  ? 'success'
                  : intent.status === 'pending'
                    ? 'warning'
                    : 'danger'
              }
            >
              {intent.status}
            </V3Badge>
          </div>
          <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] text-gray-400">
            <span>模式：{intent.mode === 'live' ? '实盘' : '模拟盘'}</span>
            <span>类型：{intent.order_type}</span>
            <span>草稿：{intent.id}</span>
            <span>
              上限：{intent.risk.max_order_size}
              {intent.risk.notional_hint ? ` · 名义 ${intent.risk.notional_hint}` : ''}
            </span>
          </div>
          {intent.error && (
            <div className="text-[10px] text-red-400">
              {intent.error.code}: {intent.error.message}
            </div>
          )}
          {receipt?.order && (
            <div className="text-[10px] text-emerald-400 font-mono">
              回执：order_id={receipt.order.order_id || '—'} sCode={receipt.order.s_code || '—'}
              {receipt.order.s_msg ? ` ${receipt.order.s_msg}` : ''}
            </div>
          )}
        </div>
      )}
    </V3Card>
  );
}

export default OrderTicketPanel;
