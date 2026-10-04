'use client';

import React, { useState, useMemo } from 'react';
import { V3Card, V3Badge, V3StatusDot } from '@/components';

/**
 * F7.3: MoodBoardPanel — 情绪板可视化产物
 *
 * Muse 启发: 将多源信息综合成视觉化"情绪板"
 * 一屏综合展示: 多空信号 + 相关性矩阵 + 风险热力图 + 资金流向
 *
 * 关联: D4 (Risk Agent 压力测试) + F1 (Bloomberg 多 panel)
 */

// ── 类型定义 ──────────────────────────────

interface SignalItem {
  source: string;
  name: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
}

interface HeatmapCell {
  label: string;
  metric: string;
  value: number;
}

interface FlowNode {
  name: string;
  category: 'source' | 'target';
}

interface FlowLink {
  source: string;
  target: string;
  value: number;
}

interface MoodBoardData {
  signals: SignalItem[];
  correlationHeatmap: HeatmapCell[];
  riskHeatmap: HeatmapCell[];
  flows: { nodes: FlowNode[]; links: FlowLink[] };
  portfolioHeat: {
    nominal: { symbol: string; value: number }[];
    correlationAdjusted: { symbol: string; value: number }[];
    maxPotential: { symbol: string; value: number }[];
  };
  stressTest: {
    var: number;
    es: number;
    pipelines: { name: string; var: number; es: number }[];
  };
}

// ── 模拟数据 (实际应由 Aggregator 输出 mood_board_artifact) ──

const MOCK_DATA: MoodBoardData = {
  signals: [
    { source: 'technical', name: 'EMA排列', direction: 'long', confidence: 0.72 },
    { source: 'sentiment', name: 'FGI', direction: 'long', confidence: 0.60 },
    { source: 'macro', name: '利率预期', direction: 'short', confidence: 0.65 },
    { source: 'flow', name: '主力资金', direction: 'long', confidence: 0.55 },
    { source: 'risk', name: 'VaR95', direction: 'short', confidence: 0.55 },
    { source: 'portfolio', name: '漂移度', direction: 'neutral', confidence: 0.40 },
  ],
  correlationHeatmap: [
    { label: 'BTC', metric: '相关性', value: 0.85 },
    { label: 'ETH', metric: '相关性', value: 0.72 },
    { label: 'SOL', metric: '相关性', value: 0.55 },
    { label: 'BNB', metric: '相关性', value: 0.48 },
  ],
  riskHeatmap: [
    { label: 'VaR95', metric: '风险值', value: 0.06 },
    { label: 'VaR99', metric: '风险值', value: 0.09 },
    { label: '压力损失', metric: '风险值', value: 0.12 },
    { label: '最大回撤', metric: '风险值', value: 0.08 },
  ],
  flows: {
    nodes: [
      { name: '现货', category: 'source' },
      { name: '合约', category: 'source' },
      { name: 'BTC', category: 'target' },
      { name: 'ETH', category: 'target' },
      { name: 'SOL', category: 'target' },
    ],
    links: [
      { source: '现货', target: 'BTC', value: 45 },
      { source: '现货', target: 'ETH', value: 30 },
      { source: '合约', target: 'BTC', value: 15 },
      { source: '合约', target: 'SOL', value: 10 },
    ],
  },
  portfolioHeat: {
    nominal: [{ symbol: 'BTC', value: 0.4 }, { symbol: 'ETH', value: 0.3 }, { symbol: 'SOL', value: 0.3 }],
    correlationAdjusted: [{ symbol: 'BTC', value: 0.36 }, { symbol: 'ETH', value: 0.25 }, { symbol: 'SOL', value: 0.23 }],
    maxPotential: [{ symbol: 'BTC', value: 0.12 }, { symbol: 'ETH', value: 0.09 }, { symbol: 'SOL', value: 0.09 }],
  },
  stressTest: {
    var: 0.031,
    es: 0.035,
    pipelines: [
      { name: 'PCA', var: 0.017, es: 0.022 },
      { name: 'AE', var: 0.031, es: 0.035 },
      { name: 'VAE', var: 0.019, es: 0.025 },
    ],
  },
};

// ── 辅助函数 ──────────────────────────────

const directionColors: Record<string, string> = {
  long: 'text-emerald-400 bg-emerald-500/10',
  short: 'text-rose-400 bg-rose-500/10',
  neutral: 'text-slate-400 bg-slate-700/20',
};

const heatColor = (value: number, max: number): string => {
  const ratio = value / max;
  if (ratio > 0.7) return 'bg-rose-500/40';
  if (ratio > 0.4) return 'bg-amber-500/30';
  return 'bg-emerald-500/20';
};

// ── 组件 ──────────────────────────────────

export function MoodBoardPanel({ data = MOCK_DATA }: { data?: MoodBoardData }) {
  const [activeView, setActiveView] = useState<'signals' | 'correlation' | 'risk' | 'flow' | 'heat'>('signals');

  // 多空情绪指数 (0-100)
  const moodIndex = useMemo(() => {
    const longs = data.signals.filter(s => s.direction === 'long');
    const shorts = data.signals.filter(s => s.direction === 'short');
    const longScore = longs.reduce((sum, s) => sum + s.confidence, 0);
    const shortScore = shorts.reduce((sum, s) => sum + s.confidence, 0);
    const total = longScore + shortScore || 1;
    return Math.round((longScore / total) * 100);
  }, [data.signals]);

  const moodLabel = moodIndex >= 65 ? '贪婪' : moodIndex >= 45 ? '中性' : '恐惧';
  const moodColor = moodIndex >= 65 ? 'text-emerald-400' : moodIndex >= 45 ? 'text-amber-400' : 'text-rose-400';

  return (
    <div className="space-y-4">
      {/* 情绪指数头 */}
      <V3Card padding="sm">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-slate-500">市场情绪指数</p>
            <p className={`text-2xl font-bold ${moodColor}`}>{moodIndex} <span className="text-sm">{moodLabel}</span></p>
          </div>
          <div className="w-32 h-2 rounded-full bg-slate-700 overflow-hidden">
            <div
              className={`h-full ${moodIndex >= 65 ? 'bg-emerald-500' : moodIndex >= 45 ? 'bg-amber-500' : 'bg-rose-500'}`}
              style={{ width: `${moodIndex}%` }}
            />
          </div>
        </div>
      </V3Card>

      {/* 视图切换 */}
      <div className="flex items-center gap-2 flex-wrap">
        {([
          { key: 'signals', label: '多空信号' },
          { key: 'correlation', label: '相关性矩阵' },
          { key: 'risk', label: '风险热力图' },
          { key: 'flow', label: '资金流向' },
          { key: 'heat', label: 'Portfolio Heat' },
        ] as const).map(t => (
          <button
            key={t.key}
            onClick={() => setActiveView(t.key)}
            className={`text-xs px-3 py-1 rounded-lg transition-colors ${
              activeView === t.key
                ? 'bg-indigo-500/20 text-indigo-400 border border-indigo-500/30'
                : 'bg-slate-800/40 text-slate-400 border border-slate-700/30 hover:bg-slate-800/60'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 多空信号 */}
      {activeView === 'signals' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {data.signals.map((s, i) => (
            <V3Card key={i} padding="sm">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <V3Badge variant="default">{s.source}</V3Badge>
                  <span className="text-sm text-slate-200">{s.name}</span>
                </div>
                <span className={`text-[10px] px-2 py-0.5 rounded ${directionColors[s.direction]}`}>
                  {s.direction.toUpperCase()}
                </span>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <div className="flex-1 h-1 rounded-full bg-slate-700 overflow-hidden">
                  <div
                    className={`h-full ${s.direction === 'long' ? 'bg-emerald-500' : s.direction === 'short' ? 'bg-rose-500' : 'bg-slate-500'}`}
                    style={{ width: `${s.confidence * 100}%` }}
                  />
                </div>
                <span className="text-[10px] text-slate-500">{(s.confidence * 100).toFixed(0)}%</span>
              </div>
            </V3Card>
          ))}
        </div>
      )}

      {/* 相关性矩阵 */}
      {activeView === 'correlation' && (
        <V3Card padding="sm">
          <p className="text-xs font-semibold text-slate-300 mb-3">资产相关性矩阵</p>
          <div className="grid grid-cols-4 gap-1">
            {data.correlationHeatmap.map((c, i) => (
              <div key={i} className={`p-2 rounded text-center ${heatColor(c.value, 1.0)}`}>
                <p className="text-[10px] text-slate-400">{c.label}</p>
                <p className="text-sm font-bold text-slate-200">{c.value.toFixed(2)}</p>
              </div>
            ))}
          </div>
        </V3Card>
      )}

      {/* 风险热力图 */}
      {activeView === 'risk' && (
        <V3Card padding="sm">
          <p className="text-xs font-semibold text-slate-300 mb-3">风险指标热力图</p>
          <div className="grid grid-cols-4 gap-1">
            {data.riskHeatmap.map((c, i) => (
              <div key={i} className={`p-2 rounded text-center ${heatColor(c.value, 0.15)}`}>
                <p className="text-[10px] text-slate-400">{c.label}</p>
                <p className="text-sm font-bold text-slate-200">{(c.value * 100).toFixed(1)}%</p>
              </div>
            ))}
          </div>
        </V3Card>
      )}

      {/* 资金流向 Sankey (简化为条形图) */}
      {activeView === 'flow' && (
        <V3Card padding="sm">
          <p className="text-xs font-semibold text-slate-300 mb-3">资金流向 (Sankey 简化)</p>
          <div className="space-y-2">
            {data.flows.links.map((l, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-[10px] text-slate-400 w-12">{l.source}</span>
                <div className="flex-1 h-3 rounded-full bg-slate-700/40 overflow-hidden flex">
                  <div className="h-full bg-blue-500/60" style={{ width: `${l.value}%` }} />
                </div>
                <span className="text-[10px] text-slate-400 w-12">{l.target}</span>
                <span className="text-[10px] text-blue-400 w-8">{l.value}</span>
              </div>
            ))}
          </div>
        </V3Card>
      )}

      {/* Portfolio Heat 三层 */}
      {activeView === 'heat' && (
        <div className="space-y-2">
          <V3Card padding="sm">
            <p className="text-xs font-semibold text-slate-300 mb-2">Portfolio Heat (D4 三层指标)</p>
            {['nominal', 'correlationAdjusted', 'maxPotential'].map((layer, idx) => {
              const layerData = data.portfolioHeat[layer as keyof typeof data.portfolioHeat];
              const layerLabels = ['名义暴露 (Nominal)', '相关性调整 (Corr-Adj)', '最大潜在损失 (Max Loss)'];
              return (
                <div key={layer} className="mb-3">
                  <p className="text-[10px] text-slate-500 mb-1">{layerLabels[idx]}</p>
                  <div className="flex items-center gap-1">
                    {layerData.map((p, i) => (
                      <div key={i} className="flex-1">
                        <div className="h-4 rounded bg-slate-700/40 overflow-hidden">
                          <div
                            className={`h-full ${idx === 0 ? 'bg-blue-500/60' : idx === 1 ? 'bg-amber-500/60' : 'bg-rose-500/60'}`}
                            style={{ width: `${p.value * 100}%` }}
                          />
                        </div>
                        <p className="text-[9px] text-slate-500 text-center mt-0.5">{p.symbol}</p>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </V3Card>

          {/* ML 压力测试结果 */}
          <V3Card padding="sm">
            <p className="text-xs font-semibold text-slate-300 mb-2">ML 压力测试 (D4 三管线)</p>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] text-slate-500">保守 VaR / ES</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-rose-400">VaR {(data.stressTest.var * 100).toFixed(2)}%</span>
                <span className="text-xs text-amber-400">ES {(data.stressTest.es * 100).toFixed(2)}%</span>
              </div>
            </div>
            <div className="space-y-1">
              {data.stressTest.pipelines.map((p, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-400 w-10">{p.name}</span>
                  <div className="flex-1 flex gap-1">
                    <div className="flex-1 h-2 rounded bg-slate-700/40 overflow-hidden">
                      <div className="h-full bg-rose-500/60" style={{ width: `${p.var * 1000}%` }} />
                    </div>
                    <div className="flex-1 h-2 rounded bg-slate-700/40 overflow-hidden">
                      <div className="h-full bg-amber-500/60" style={{ width: `${p.es * 1000}%` }} />
                    </div>
                  </div>
                  <span className="text-[9px] text-slate-500">{(p.var * 100).toFixed(1)}% / {(p.es * 100).toFixed(1)}%</span>
                </div>
              ))}
            </div>
          </V3Card>
        </div>
      )}
    </div>
  );
}
