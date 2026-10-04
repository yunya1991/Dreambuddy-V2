'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { V3Card, V3Badge } from '@/components';

/**
 * F6: Meta-Labeling 前端入口
 *
 * Meta-Labeling (L2 二级判断): 对 L1 信号进行盈利性判断。
 * L1 模型生成方向信号 (buy/sell), L2 模型判断该信号的盈利概率。
 *
 * 决策矩阵:
 *   - L1=buy  + L2 胜率高 → 执行 (size 加大)
 *   - L1=buy  + L2 胜率低 → 观望 (size 减半或 skip)
 *   - L1=sell + L2 胜率高 → 执行
 *   - L1=sell + L2 胜率低 → 观望
 *
 * REFACTOR: 通过 /api/meta-labeling 获取 L2 决策结果，API 不可用时降级到本地 mock
 * 后续接入真实后端：11-易经推理系统/scripts/memory_l4/bcrm2/meta_labeling_features_v2.py
 */

interface L1Signal {
  source: string;
  name: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
}

interface MetaLabelResult {
  signal: L1Signal;
  winProbability: number;       // L2 盈利概率 0-1
  expectedValue: number;        // 期望值
  decision: 'execute' | 'observe' | 'skip';
  sizeMultiplier: number;       // 仓位倍数
}

// 模拟 L1 信号 (实际应由 subagent signals 聚合)
const MOCK_SIGNALS: L1Signal[] = [
  { source: 'technical', name: 'EMA排列', direction: 'long', confidence: 0.72 },
  { source: 'technical', name: 'RSI14', direction: 'neutral', confidence: 0.45 },
  { source: 'sentiment', name: 'FGI', direction: 'long', confidence: 0.60 },
  { source: 'macro', name: '利率预期', direction: 'short', confidence: 0.65 },
  { source: 'risk', name: 'VaR95', direction: 'short', confidence: 0.55 },
  { source: 'portfolio', name: '漂移度', direction: 'neutral', confidence: 0.40 },
];

// L2 Meta-Labeling 模型 (简化版: 基于信号置信度 + 源历史胜率)
const SOURCE_WIN_RATE: Record<string, number> = {
  technical: 0.58,
  sentiment: 0.52,
  macro: 0.61,
  flow: 0.55,
  valuation: 0.56,
  onchain: 0.54,
  risk: 0.63,
  portfolio: 0.50,
};

function computeMetaLabel(signal: L1Signal): MetaLabelResult {
  const baseWinRate = SOURCE_WIN_RATE[signal.source] ?? 0.50;
  // L2 胜率 = 基础胜率 * 置信度调整因子
  const confAdjust = 0.7 + 0.6 * signal.confidence;  // 0.7 ~ 1.3
  const winProb = Math.min(0.95, baseWinRate * confAdjust);

  // 期望值 = 胜率 * 平均盈利 - (1-胜率) * 平均亏损 (假设 盈亏比 1.5)
  const avgWin = 0.03;
  const avgLoss = 0.02;
  const ev = winProb * avgWin - (1 - winProb) * avgLoss;

  // 决策
  let decision: MetaLabelResult['decision'];
  let sizeMultiplier: number;
  if (signal.direction === 'neutral') {
    decision = 'skip';
    sizeMultiplier = 0;
  } else if (winProb >= 0.60 && ev > 0) {
    decision = 'execute';
    sizeMultiplier = winProb >= 0.70 ? 1.5 : 1.0;
  } else if (winProb >= 0.52) {
    decision = 'observe';
    sizeMultiplier = 0.5;
  } else {
    decision = 'skip';
    sizeMultiplier = 0;
  }

  return { signal, winProbability: winProb, expectedValue: ev, decision, sizeMultiplier };
}

const decisionStyles: Record<string, { bg: string; text: string; label: string }> = {
  execute: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', label: '执行' },
  observe: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: '观望' },
  skip: { bg: 'bg-slate-700/30', text: 'text-slate-500', label: '跳过' },
};

const directionStyles: Record<string, string> = {
  long: 'text-emerald-400',
  short: 'text-rose-400',
  neutral: 'text-slate-500',
};

export default function MetaLabelingPage() {
  const [filter, setFilter] = useState<'all' | 'execute' | 'observe' | 'skip'>('all');
  // 降级 fallback：API 不可用时使用本地预计算结果
  const [results, setResults] = useState<MetaLabelResult[]>(() => MOCK_SIGNALS.map(computeMetaLabel));
  const [loading, setLoading] = useState(true);
  const [dataSource, setDataSource] = useState<'api' | 'mock'>('mock');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    fetch('/api/meta-labeling', { cache: 'no-store' })
      .then(res => res.json())
      .then(data => {
        if (cancelled) return;
        if (data.success && Array.isArray(data.results) && data.results.length > 0) {
          setResults(data.results);
          setDataSource('api');
        }
        // API 返回空数据时保持本地降级 mock
      })
      .catch(() => {
        // API 不可用时保持本地降级 mock
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  const filtered = useMemo(
    () => filter === 'all' ? results : results.filter(r => r.decision === filter),
    [results, filter]
  );

  const stats = useMemo(() => ({
    total: results.length,
    execute: results.filter(r => r.decision === 'execute').length,
    observe: results.filter(r => r.decision === 'observe').length,
    skip: results.filter(r => r.decision === 'skip').length,
    avgWinProb: results.length > 0 ? results.reduce((s, r) => s + r.winProbability, 0) / results.length : 0,
  }), [results]);

  return (
    <div className="p-4 sm:p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-slate-200">Meta-Labeling 二级判断</h1>
        <p className="text-sm text-slate-500 mt-1">
          L1 信号 → L2 盈利概率判断 → 执行/观望/跳过决策矩阵
          {dataSource === 'mock' && !loading && (
            <span className="ml-2 text-amber-500/70">（演示数据）</span>
          )}
        </p>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">信号总数</p>
          <p className="text-lg font-bold text-slate-200">{stats.total}</p>
        </V3Card>
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">执行</p>
          <p className="text-lg font-bold text-emerald-400">{stats.execute}</p>
        </V3Card>
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">观望</p>
          <p className="text-lg font-bold text-amber-400">{stats.observe}</p>
        </V3Card>
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">平均胜率</p>
          <p className="text-lg font-bold text-blue-400">{(stats.avgWinProb * 100).toFixed(1)}%</p>
        </V3Card>
      </div>

      {/* 过滤器 */}
      <div className="flex items-center gap-2 mb-4">
        {(['all', 'execute', 'observe', 'skip'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-xs px-3 py-1 rounded-lg transition-colors ${
              filter === f
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
                : 'bg-slate-800/40 text-slate-400 border border-slate-700/30 hover:bg-slate-800/60'
            }`}
          >
            {f === 'all' ? '全部' : decisionStyles[f].label}
          </button>
        ))}
      </div>

      {/* 信号列表 */}
      <div className="space-y-2">
        {loading ? (
          <div className="text-center py-8 text-slate-500 text-xs">加载中...</div>
        ) : filtered.map((r, i) => {
          const ds = decisionStyles[r.decision];
          return (
            <V3Card key={i} padding="sm">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <V3Badge variant="default">{r.signal.source}</V3Badge>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-200 truncate">
                      {r.signal.name}
                    </p>
                    <p className={`text-[10px] ${directionStyles[r.signal.direction]}`}>
                      {r.signal.direction.toUpperCase()} · L1置信 {(r.signal.confidence * 100).toFixed(0)}%
                    </p>
                  </div>
                </div>

                {/* L2 胜率条 */}
                <div className="flex items-center gap-2 shrink-0">
                  <div className="w-20 h-1.5 rounded-full bg-slate-700 overflow-hidden">
                    <div
                      className={`h-full ${r.winProbability >= 0.6 ? 'bg-emerald-500' : r.winProbability >= 0.52 ? 'bg-amber-500' : 'bg-slate-600'}`}
                      style={{ width: `${r.winProbability * 100}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-slate-400 w-10 text-right">
                    {(r.winProbability * 100).toFixed(0)}%
                  </span>
                </div>

                {/* 决策标签 */}
                <div className="flex items-center gap-2 shrink-0">
                  <span className={`text-[10px] px-2 py-0.5 rounded ${ds.bg} ${ds.text}`}>
                    {ds.label}
                  </span>
                  <span className="text-[10px] text-slate-500">
                    {r.sizeMultiplier > 0 ? `${r.sizeMultiplier}x` : '—'}
                  </span>
                </div>
              </div>
            </V3Card>
          );
        })}
      </div>

      {/* 决策矩阵说明 */}
      <V3Card padding="sm" className="mt-6">
        <p className="text-xs font-semibold text-slate-300 mb-2">决策矩阵</p>
        <div className="grid grid-cols-3 gap-2 text-[10px]">
          <div className="p-2 rounded bg-emerald-500/10 border border-emerald-500/20">
            <p className="text-emerald-400 font-medium">执行</p>
            <p className="text-slate-500">胜率≥60% &amp; EV&gt;0</p>
          </div>
          <div className="p-2 rounded bg-amber-500/10 border border-amber-500/20">
            <p className="text-amber-400 font-medium">观望</p>
            <p className="text-slate-500">胜率52-60%</p>
          </div>
          <div className="p-2 rounded bg-slate-700/20 border border-slate-700/30">
            <p className="text-slate-500 font-medium">跳过</p>
            <p className="text-slate-500">胜率&lt;52% 或 neutral</p>
          </div>
        </div>
      </V3Card>
    </div>
  );
}
