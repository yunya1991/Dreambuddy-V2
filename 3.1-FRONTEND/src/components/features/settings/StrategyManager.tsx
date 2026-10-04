'use client';

import { useState, useEffect } from 'react';
import { api } from '@/lib/api-client';
import {
  V3Card, V3Button, V3Badge, V3StatusDot,
  IconRefresh, IconPlus, IconClose,
} from '@/components';
import type { StrategyView } from '@/types';

// 解析接口返回的结构
interface ParseResult {
  intent: {
    direction: 'BUY' | 'SHORT' | 'SKIP';
    symbol: string;
    tradeType: 'SPOT' | 'SWAP';
    indicators: string[];
  };
  suggestedParams: {
    direction: 'BUY' | 'SHORT' | 'SKIP';
    symbol: string;
    tradeType: 'SPOT' | 'SWAP';
    leverage: number;
    positionSize: number;
    stopLoss: number | null;
    takeProfit: number | null;
  };
  confidence: number;
  explanation: string;
  warnings: string[];
}

interface StrategyForm {
  name: string;
  description: string;
  direction: 'BUY' | 'SHORT' | 'SKIP';
  symbol: string;
  tradeType: 'SPOT' | 'SWAP';
  leverage: number;
  positionSize: number;
  stopLoss: string;
  takeProfit: string;
  rawInput: string;
  frequency: string;
  autoApply: boolean;
}

const EMPTY_FORM: StrategyForm = {
  name: '',
  description: '',
  direction: 'BUY',
  symbol: 'BTC-USDT-SWAP',
  tradeType: 'SWAP',
  leverage: 2,
  positionSize: 0.5,
  stopLoss: '',
  takeProfit: '',
  rawInput: '',
  frequency: 'FOUR_H',
  autoApply: false,
};

const DIRECTION_OPTIONS: { value: 'BUY' | 'SHORT' | 'SKIP'; label: string }[] = [
  { value: 'BUY', label: '做多' },
  { value: 'SHORT', label: '做空' },
  { value: 'SKIP', label: '观望' },
];

const FREQ_OPTIONS: { value: string; label: string }[] = [
  { value: 'ONE_H', label: '1H' },
  { value: 'FOUR_H', label: '4H' },
  { value: 'ONE_D', label: '1D' },
];

const STATUS_VARIANT: Record<string, 'default' | 'success' | 'danger'> = {
  DRAFT: 'default',
  APPROVED: 'default',
  APPLIED: 'success',
  PAUSED: 'default',
  EXPIRED: 'danger',
};

const STATUS_LABEL: Record<string, string> = {
  DRAFT: '草稿',
  APPROVED: '已审核',
  APPLIED: '已应用',
  PAUSED: '已暂停',
  EXPIRED: '已过期',
};

const DIRECTION_LABEL: Record<string, string> = {
  BUY: '做多',
  SHORT: '做空',
  SKIP: '观望',
};

export function StrategyManager() {
  const [strategies, setStrategies] = useState<StrategyView[]>([]);
  const [loading, setLoading] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<StrategyForm>(EMPTY_FORM);
  const [parsing, setParsing] = useState(false);
  const [parseResult, setParseResult] = useState<ParseResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    fetchStrategies();
  }, []);

  const fetchStrategies = async () => {
    setLoading(true);
    try {
      const data = await api.get<{ strategies: StrategyView[]; recommended: StrategyView[]; custom: StrategyView[]; applied: StrategyView[] }>(
        '/api/config/strategies'
      );
      setStrategies(data?.strategies || []);
    } catch {
      // 静默处理
    } finally {
      setLoading(false);
    }
  };

  const openForm = () => {
    setForm(EMPTY_FORM);
    setParseResult(null);
    setError(null);
    setInfo(null);
    setFormOpen(true);
  };

  const closeForm = () => {
    setFormOpen(false);
    setParseResult(null);
    setError(null);
  };

  const updateField = <K extends keyof StrategyForm>(field: K, value: StrategyForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleParse = async () => {
    if (form.rawInput.trim().length < 4) {
      setError('请输入至少4个字符的策略描述');
      return;
    }
    setParsing(true);
    setError(null);
    try {
      const result = await api.post<ParseResult>('/api/config/strategies/parse', {
        rawInput: form.rawInput,
      });
      setParseResult(result);
      // 自动填充表单字段
      const p = result.suggestedParams;
      setForm((prev) => ({
        ...prev,
        direction: p.direction,
        symbol: p.symbol,
        tradeType: p.tradeType,
        leverage: p.leverage,
        positionSize: p.positionSize,
        stopLoss: p.stopLoss !== null ? String(p.stopLoss) : '',
        takeProfit: p.takeProfit !== null ? String(p.takeProfit) : '',
        name: prev.name || `${p.symbol.split('-')[0]} ${p.direction === 'BUY' ? '多' : p.direction === 'SHORT' ? '空' : '观望'}`,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '解析失败');
    } finally {
      setParsing(false);
    }
  };

  const handleSubmit = async () => {
    setError(null);
    if (!form.name || !form.direction) {
      setError('名称和方向为必填项');
      return;
    }

    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        type: 'CUSTOM',
        name: form.name,
        description: form.description || undefined,
        direction: form.direction,
        symbol: form.symbol,
        tradeType: form.tradeType,
        leverage: form.leverage,
        positionSize: form.positionSize,
        stopLoss: form.stopLoss ? Number(form.stopLoss) : undefined,
        takeProfit: form.takeProfit ? Number(form.takeProfit) : undefined,
        rawInput: form.rawInput || undefined,
        apply: form.autoApply,
        frequency: form.frequency,
      };
      await api.post('/api/config/strategies', body);
      await fetchStrategies();
      closeForm();
      setInfo(form.autoApply ? '策略已创建并应用' : '策略已创建');
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败');
    } finally {
      setSaving(false);
    }
  };

  const handleApply = async (id: string) => {
    setActionLoading(`apply-${id}`);
    setError(null);
    try {
      await api.post(`/api/config/strategies/${id}/apply`, {});
      setInfo('策略已应用，定时任务已创建');
      await fetchStrategies();
    } catch (err) {
      setError(err instanceof Error ? err.message : '应用失败');
    } finally {
      setActionLoading(null);
    }
  };

  const handlePause = async (id: string) => {
    setActionLoading(`pause-${id}`);
    setError(null);
    try {
      await api.post(`/api/config/strategies/${id}/pause`, {});
      setInfo('策略已暂停');
      await fetchStrategies();
    } finally {
      setActionLoading(null);
    }
  };

  const handleDelete = async (id: string) => {
    setError(null);
    try {
      await api.delete(`/api/config/strategies?id=${encodeURIComponent(id)}`);
      setConfirmDelete(null);
      await fetchStrategies();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
      setConfirmDelete(null);
    }
  };

  const inputCls = 'w-full bg-gray-900/60 border border-gray-700/50 rounded-md px-2 py-1.5 text-xs text-gray-200';
  const selectCls = inputCls;

  return (
    <V3Card
      title="策略管理"
      subtitle="策略列表 · 解析 · 应用"
      actions={
        <div className="flex items-center gap-2">
          <V3Button variant="ghost" size="sm" onClick={fetchStrategies} loading={loading} icon={<IconRefresh className="w-3.5 h-3.5" />}>
            刷新
          </V3Button>
          {!formOpen && (
            <V3Button variant="primary" size="sm" onClick={openForm} icon={<IconPlus className="w-3.5 h-3.5" />}>
              创建
            </V3Button>
          )}
        </div>
      }
      padding="sm"
    >
      {error && (
        <div className="mb-2 text-[11px] text-red-400 px-2 py-1 bg-red-900/20 rounded">{error}</div>
      )}
      {info && (
        <div className="mb-2 text-[11px] text-emerald-400 px-2 py-1 bg-emerald-900/20 rounded">{info}</div>
      )}

      {formOpen && (
        <div className="mb-3 p-3 rounded-lg bg-gray-800/40 border border-gray-700/40 space-y-2.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-200">创建策略</span>
            <button onClick={closeForm} className="text-gray-400 hover:text-gray-200">
              <IconClose className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* 自然语言解析区 */}
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">自然语言描述（可选）</label>
            <textarea
              value={form.rawInput}
              onChange={(e) => updateField('rawInput', e.target.value)}
              placeholder="如：做多 BTC 永续合约 2x 杠杆 止损 60000 止盈 70000"
              rows={2}
              className={`${inputCls} resize-none`}
            />
            <div className="mt-1.5 flex justify-end">
              <V3Button variant="secondary" size="sm" onClick={handleParse} loading={parsing}>
                解析填充
              </V3Button>
            </div>
          </div>

          {parseResult && (
            <div className="px-2 py-1.5 rounded-md bg-blue-900/15 border border-blue-700/30 space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-blue-300">解析结果</span>
                <V3Badge variant="default">置信度 {parseResult.confidence}%</V3Badge>
              </div>
              <p className="text-[11px] text-gray-300">{parseResult.explanation}</p>
              {parseResult.warnings.length > 0 && (
                <ul className="text-[10px] text-amber-400 list-disc list-inside space-y-0.5">
                  {parseResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              )}
            </div>
          )}

          {/* 结构化字段 */}
          <div>
            <label className="text-[10px] text-gray-500 block mb-1">策略名称 *</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => updateField('name', e.target.value)}
              placeholder="如：BTC 趋势跟踪"
              className={inputCls}
            />
          </div>

          <div>
            <label className="text-[10px] text-gray-500 block mb-1">描述（可选）</label>
            <input
              type="text"
              value={form.description}
              onChange={(e) => updateField('description', e.target.value)}
              placeholder="策略说明"
              className={inputCls}
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">方向 *</label>
              <select
                value={form.direction}
                onChange={(e) => updateField('direction', e.target.value as StrategyForm['direction'])}
                className={selectCls}
              >
                {DIRECTION_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">品种</label>
              <input
                type="text"
                value={form.symbol}
                onChange={(e) => updateField('symbol', e.target.value)}
                placeholder="BTC-USDT-SWAP"
                className={`${inputCls} font-mono`}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">交易类型</label>
              <select
                value={form.tradeType}
                onChange={(e) => updateField('tradeType', e.target.value as StrategyForm['tradeType'])}
                className={selectCls}
              >
                <option value="SPOT">现货</option>
                <option value="SWAP">合约</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">执行频率</label>
              <select
                value={form.frequency}
                onChange={(e) => updateField('frequency', e.target.value)}
                className={selectCls}
              >
                {FREQ_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">杠杆 (1-5)</label>
              <input
                type="number"
                min={1}
                max={5}
                step={1}
                value={form.leverage}
                onChange={(e) => updateField('leverage', Number(e.target.value))}
                className={inputCls}
              />
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">仓位比例 (0-1)</label>
              <input
                type="number"
                min={0.01}
                max={1}
                step={0.05}
                value={form.positionSize}
                onChange={(e) => updateField('positionSize', Number(e.target.value))}
                className={inputCls}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">止损价（可选）</label>
              <input
                type="number"
                step="any"
                value={form.stopLoss}
                onChange={(e) => updateField('stopLoss', e.target.value)}
                placeholder="如 60000"
                className={inputCls}
              />
            </div>
            <div>
              <label className="text-[10px] text-gray-500 block mb-1">止盈价（可选）</label>
              <input
                type="number"
                step="any"
                value={form.takeProfit}
                onChange={(e) => updateField('takeProfit', e.target.value)}
                placeholder="如 70000"
                className={inputCls}
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer">
            <input
              type="checkbox"
              checked={form.autoApply}
              onChange={(e) => updateField('autoApply', e.target.checked)}
              className="rounded"
            />
            创建后自动应用（生成定时任务）
          </label>

          <div className="flex justify-end gap-2 pt-1">
            <V3Button variant="ghost" size="sm" onClick={closeForm} disabled={saving}>取消</V3Button>
            <V3Button variant="primary" size="sm" onClick={handleSubmit} loading={saving}>
              创建策略
            </V3Button>
          </div>
        </div>
      )}

      {strategies.length === 0 && !formOpen ? (
        <div className="text-center py-8 text-gray-500 text-xs">
          暂无策略
          <div className="mt-2">
            <V3Button variant="secondary" size="sm" onClick={openForm} icon={<IconPlus className="w-3.5 h-3.5" />}>
              创建第一个策略
            </V3Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {strategies.map((s) => {
            const isApplied = s.status === 'APPLIED';
            const isPaused = s.status === 'PAUSED';
            const isConfirming = confirmDelete === s.id;
            const taskCount = s.tasks?.length || 0;
            return (
              <div
                key={s.id}
                className="px-3 py-2 rounded-lg bg-gray-800/20 border border-gray-700/20"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <V3StatusDot
                      status={isApplied ? 'success' : isPaused ? 'warning' : s.status === 'EXPIRED' ? 'error' : 'idle'}
                    />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-medium text-gray-200 truncate">{s.name}</span>
                        <V3Badge variant={s.type === 'RECOMMENDED' ? 'default' : 'success'}>
                          {s.type === 'RECOMMENDED' ? '推荐' : '自定义'}
                        </V3Badge>
                        <V3Badge variant={STATUS_VARIANT[s.status] || 'default'}>
                          {STATUS_LABEL[s.status] || s.status}
                        </V3Badge>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-[10px] text-gray-500">
                        <span>{DIRECTION_LABEL[s.direction] || s.direction}</span>
                        <span>·</span>
                        <span className="font-mono">{s.symbol}</span>
                        <span>·</span>
                        <span>{s.tradeType === 'SWAP' ? `${s.leverage}x` : '现货'}</span>
                        {taskCount > 0 && (
                          <>
                            <span>·</span>
                            <span>{taskCount} 个任务</span>
                          </>
                        )}
                      </div>
                      {s.description && (
                        <p className="text-[10px] text-gray-500 mt-1 line-clamp-2">{s.description}</p>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 mt-2 pt-2 border-t border-gray-700/20">
                  {!isApplied && !isPaused && s.status !== 'EXPIRED' && (
                    <V3Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleApply(s.id)}
                      loading={actionLoading === `apply-${s.id}`}
                      className="text-emerald-400 hover:text-emerald-300"
                    >
                      应用
                    </V3Button>
                  )}
                  {isApplied && (
                    <V3Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handlePause(s.id)}
                      loading={actionLoading === `pause-${s.id}`}
                      className="text-amber-400 hover:text-amber-300"
                    >
                      暂停
                    </V3Button>
                  )}
                  {isConfirming ? (
                    <>
                      <V3Button variant="danger" size="sm" onClick={() => handleDelete(s.id)}>
                        确认删除
                      </V3Button>
                      <V3Button variant="ghost" size="sm" onClick={() => setConfirmDelete(null)}>
                        取消
                      </V3Button>
                    </>
                  ) : (
                    <V3Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmDelete(s.id)}
                      className="text-red-400 hover:text-red-300"
                    >
                      删除
                    </V3Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </V3Card>
  );
}

export default StrategyManager;
