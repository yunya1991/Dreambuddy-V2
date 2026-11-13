'use client';

// ============================================
// 回测数据看板 — A/B/C 三组信号回测指标对比
// 指标来源：ranking_backtest.py 产出的 backtest_p2_*.json
// ============================================

import React from 'react';
import { V3Card, V3Badge } from '@/components';
import type { RankingBacktestMetrics } from './types';

interface RankingMonitorProps {
  metrics: RankingBacktestMetrics;
}

const GROUPS: { key: 'A' | 'B' | 'C'; label: string; hint: string }[] = [
  { key: 'A', label: 'A 组', hint: '6-TRADING 原模式' },
  { key: 'B', label: 'B 组', hint: '42→50-NN 神经网络' },
  { key: 'C', label: 'C 组', hint: '23 自进化' },
];

interface MetricDef {
  key: keyof RankingBacktestMetrics;
  label: string;
  desc: string;
  format: (v: number | undefined) => string;
  good?: (a: number, b: number) => boolean; // a 比 b 好?
  variant: (v: number | undefined) => 'success' | 'danger' | 'info' | 'warning' | 'default';
}

const METRICS: MetricDef[] = [
  {
    key: 'nTrades',
    label: '交易笔数',
    desc: '回测窗口内总交易次数',
    format: v => (v != null && v > 0 ? String(v) : '—'),
    variant: v => (v != null && v > 0 ? 'info' : 'default'),
  },
  {
    key: 'winRate',
    label: '胜率',
    desc: '盈利笔数 / 总笔数',
    format: v => (v != null ? `${(v * 100).toFixed(1)}%` : '—'),
    variant: v => {
      if (v == null) return 'default';
      if (v >= 0.5) return 'success';
      if (v >= 0.4) return 'info';
      if (v >= 0.3) return 'warning';
      return 'danger';
    },
  },
  {
    key: 'avgPnl',
    label: '平均单笔收益',
    desc: '含手续费+滑点成本',
    format: v => (v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '—'),
    variant: v => {
      if (v == null) return 'default';
      if (v > 0) return 'success';
      if (v > -1) return 'warning';
      return 'danger';
    },
  },
  {
    key: 'plRatio',
    label: '盈亏比',
    desc: '平均盈利 / |平均亏损|',
    format: v => (v != null && v > 0 ? v.toFixed(2) : '—'),
    variant: v => {
      if (v == null) return 'default';
      if (v >= 1.5) return 'success';
      if (v >= 1.0) return 'info';
      return 'warning';
    },
  },
  {
    key: 'sharpe',
    label: '夏普比率',
    desc: '年化收益 / 年化波动',
    format: v => (v != null ? v.toFixed(2) : '—'),
    variant: v => {
      if (v == null) return 'default';
      if (v > 1) return 'success';
      if (v > 0) return 'info';
      return 'danger';
    },
  },
  {
    key: 'maxDrawdown',
    label: '最大回撤',
    desc: '峰值→谷底 最大跌幅',
    format: v => (v != null ? `-${v.toFixed(1)}%` : '—'),
    variant: v => {
      if (v == null) return 'default';
      if (v < 20) return 'success';
      if (v < 40) return 'info';
      if (v < 70) return 'warning';
      return 'danger';
    },
  },
  {
    key: 'slHitRate',
    label: 'SL 命中率',
    desc: '止损出场 / (止损+止盈)',
    format: v => (v != null ? `${(v * 100).toFixed(0)}%` : '—'),
    variant: v => {
      if (v == null) return 'default';
      if (v < 0.5) return 'success'; // TP 多 → 好
      if (v < 0.7) return 'info';
      if (v < 0.85) return 'warning';
      return 'danger';
    },
  },
  {
    key: 'avgHoldDays',
    label: '平均持有天数',
    desc: '从买入到出场',
    format: v => (v != null ? `${v.toFixed(1)}d` : '—'),
    variant: v => {
      if (v == null) return 'default';
      if (v <= 3) return 'success';
      if (v <= 7) return 'info';
      return 'warning';
    },
  },
];

function getGroupValue(
  metric: MetricDef,
  metrics: RankingBacktestMetrics,
  key: 'A' | 'B' | 'C'
): number | undefined {
  const raw = metrics[metric.key] as Record<string, number | undefined>;
  return raw?.[key];
}

export function RankingMonitor({ metrics }: RankingMonitorProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-slate-400">回测数据（三组信号对比）</h3>
        <span className="text-[10px] text-slate-600">{metrics.date}</span>
      </div>

      {/* 三组信号标签 */}
      <div className="flex gap-3 mb-2 text-[10px]">
        {GROUPS.map(g => (
          <div key={g.key} className="flex items-center gap-1">
            <span className={`font-bold text-slate-300 ${g.key === 'A' ? 'text-blue-400' : g.key === 'B' ? 'text-violet-400' : 'text-emerald-400'}`}>
              {g.label}
            </span>
            <span className="text-slate-600">· {g.hint}</span>
          </div>
        ))}
      </div>

      {/* 指标网格：每行 1 指标 × 3 组 */}
      <div className="space-y-1.5">
        {METRICS.map(metric => (
          <div
            key={metric.key}
            className="grid grid-cols-[120px_1fr_1fr_1fr] gap-2 items-center"
          >
            <div className="text-[10px] text-slate-500 pr-1 border-r border-slate-800/50">
              <div className="font-medium text-slate-400">{metric.label}</div>
              <div className="text-[8px] text-slate-600 leading-tight">{metric.desc}</div>
            </div>
            {GROUPS.map(g => {
              const val = getGroupValue(metric, metrics, g.key);
              const isZero = val == null || (typeof val === 'number' && val === 0);
              return (
                <V3Card key={`${metric.key}-${g.key}`} padding="sm" className={isZero ? 'opacity-40' : ''}>
                  <div className="flex items-center justify-between">
                    <V3Badge variant={metric.variant(val)}>
                      {metric.format(val)}
                    </V3Badge>
                  </div>
                </V3Card>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export default RankingMonitor;
