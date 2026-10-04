'use client';

import React, { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';
import type { UserProfileView, TradeType, TradeMode, RiskTolerance } from '@/types';
import { V3Card, V3Button, V3Badge } from '@/components';

type TradingConfig = UserProfileView['tradingConfig'];

const TRADE_TYPES: TradeType[] = ['SWAP', 'SPOT'];
const TRADE_MODES: TradeMode[] = ['SWAP_MODE', 'SPOT_MODE', 'FUTURES_MODE', 'MARGIN_MODE'];
const RISK_LEVELS: RiskTolerance[] = ['CONSERVATIVE', 'MODERATE', 'AGGRESSIVE'];
const SYMBOL_OPTIONS = ['BTC-USDT-SWAP', 'ETH-USDT-SWAP', 'SOL-USDT-SWAP', 'BNB-USDT-SWAP', 'XRP-USDT-SWAP'];

function parseSymbols(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw as string[];
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) as string[]; } catch { return []; }
  }
  return [];
}

export function TradingParamsPanel() {
  const [params, setParams] = useState<TradingConfig | null>(null);
  const [draft, setDraft] = useState<TradingConfig | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get<{ params?: TradingConfig }>('/api/config/trading-params');
        if (!cancelled && data?.params) setParams(data.params);
      } catch {
        // 后端未就绪时静默降级
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const startEdit = () => {
    if (!params) return;
    setDraft({ ...params, allowedSymbols: parseSymbols(params.allowedSymbols) });
    setError(null);
    setEditing(true);
  };

  const cancelEdit = () => {
    setEditing(false);
    setDraft(null);
    setError(null);
  };

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      await api.patch('/api/config/trading-params', draft);
      setParams({ ...draft });
      setEditing(false);
      setDraft(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const toggleSymbol = (sym: string) => {
    if (!draft) return;
    const current = Array.isArray(draft.allowedSymbols) ? draft.allowedSymbols : parseSymbols(draft.allowedSymbols);
    const next = current.includes(sym) ? current.filter(s => s !== sym) : [...current, sym];
    setDraft({ ...draft, allowedSymbols: next });
  };

  if (loading || !params) {
    return (
      <V3Card title="交易参数" padding="sm">
        <div className="text-center py-8 text-gray-500 text-xs">
          {loading ? '加载中...' : '暂无交易参数配置'}
        </div>
      </V3Card>
    );
  }

  // ===== 编辑模式 =====
  if (editing && draft) {
    const inputCls = 'w-full bg-gray-900/60 border border-gray-700/50 rounded-md px-2 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-indigo-500/50';

    return (
      <V3Card
        title="交易参数"
        subtitle="编辑模式"
        actions={
          <div className="flex items-center gap-2">
            <V3Button variant="ghost" size="sm" onClick={cancelEdit} disabled={saving}>取消</V3Button>
            <V3Button variant="primary" size="sm" onClick={handleSave} loading={saving}>保存</V3Button>
          </div>
        }
        padding="sm"
      >
        {error && (
          <div className="mb-2 text-[11px] text-red-400 px-2 py-1 bg-red-900/20 rounded">{error}</div>
        )}

        <div className="space-y-2.5">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">交易类型</label>
              <select value={draft.tradeType} onChange={e => setDraft({ ...draft, tradeType: e.target.value as TradeType })} className={inputCls}>
                {TRADE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">交易模式</label>
              <select value={draft.tradeMode} onChange={e => setDraft({ ...draft, tradeMode: e.target.value as TradeMode })} className={inputCls}>
                {TRADE_MODES.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">最大杠杆</label>
              <input type="number" value={draft.leverageMax} min={1} max={125}
                onChange={e => setDraft({ ...draft, leverageMax: Number(e.target.value) })}
                className={inputCls} />
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">仓位比例 (%)</label>
              <input type="number" value={draft.capitalPercentage} min={1} max={100}
                onChange={e => setDraft({ ...draft, capitalPercentage: Number(e.target.value) })}
                className={inputCls} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">单日亏损限额 (USDT)</label>
              <input type="number" value={draft.dailyLossLimit} min={0}
                onChange={e => setDraft({ ...draft, dailyLossLimit: Number(e.target.value) })}
                className={inputCls} />
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">账户亏损限额 (USDT)</label>
              <input type="number" value={draft.accountLossLimit} min={0}
                onChange={e => setDraft({ ...draft, accountLossLimit: Number(e.target.value) })}
                className={inputCls} />
            </div>
          </div>

          <div>
            <label className="text-[10px] text-gray-500 block mb-1">风险偏好</label>
            <select value={draft.riskTolerance} onChange={e => setDraft({ ...draft, riskTolerance: e.target.value as RiskTolerance })} className={inputCls}>
              {RISK_LEVELS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>

          <div className="flex items-center justify-between px-2 py-2 rounded-lg bg-gray-900/40 border border-gray-700/30">
            <span className="text-xs text-gray-300">启用交易</span>
            <button
              onClick={() => setDraft({ ...draft, isTradingEnabled: !draft.isTradingEnabled })}
              className={`relative w-9 h-5 rounded-full transition-colors ${draft.isTradingEnabled ? 'bg-emerald-500' : 'bg-gray-700'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${draft.isTradingEnabled ? 'translate-x-4' : ''}`} />
            </button>
          </div>

          <div>
            <label className="text-[10px] text-gray-500 block mb-1.5">允许交易品种</label>
            <div className="flex flex-wrap gap-1.5">
              {SYMBOL_OPTIONS.map(sym => {
                const symbols = Array.isArray(draft.allowedSymbols) ? draft.allowedSymbols : parseSymbols(draft.allowedSymbols);
                const active = symbols.includes(sym);
                return (
                  <button
                    key={sym}
                    onClick={() => toggleSymbol(sym)}
                    className={`px-2 py-1 rounded text-[10px] border transition-colors ${
                      active ? 'bg-indigo-600/20 text-indigo-300 border-indigo-500/40' : 'bg-gray-800/30 text-gray-500 border-gray-700/30 hover:border-gray-600'
                    }`}
                  >
                    {sym}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </V3Card>
    );
  }

  // ===== 只读展示模式 =====
  const paramRows = [
    { label: '交易类型', value: params.tradeType },
    { label: '交易模式', value: params.tradeMode },
    { label: '最大杠杆', value: `${params.leverageMax}x` },
    { label: '仓位比例', value: `${params.capitalPercentage}%` },
    { label: '单日亏损限额', value: `${params.dailyLossLimit} USDT` },
    { label: '账户亏损限额', value: `${params.accountLossLimit} USDT` },
    { label: '风险偏好', value: params.riskTolerance },
    { label: '交易状态', value: params.isTradingEnabled ? '启用' : '禁用' },
  ];

  const symbols = parseSymbols(params.allowedSymbols);

  return (
    <V3Card
      title="交易参数"
      actions={
        <V3Button variant="primary" size="sm" onClick={startEdit}>
          编辑
        </V3Button>
      }
      padding="sm"
    >
      <div className="space-y-1.5">
        {paramRows.map((row) => (
          <div key={row.label} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800/20">
            <span className="text-xs text-gray-400">{row.label}</span>
            <span className={`text-xs font-medium ${row.label === '交易状态' ? (params.isTradingEnabled ? 'text-emerald-400' : 'text-red-400') : 'text-gray-200'}`}>
              {row.value}
            </span>
          </div>
        ))}
      </div>
      {symbols.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700/20">
          <span className="text-xs text-gray-400 mb-1.5 block">允许交易品种</span>
          <div className="flex flex-wrap gap-1.5">
            {symbols.map((s: string) => (
              <V3Badge key={s} variant="default">{s}</V3Badge>
            ))}
          </div>
        </div>
      )}
    </V3Card>
  );
}

export default TradingParamsPanel;
