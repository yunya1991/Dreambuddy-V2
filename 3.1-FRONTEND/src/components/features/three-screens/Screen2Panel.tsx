'use client';

import React from 'react';
import { useThreeScreensStore } from '@/stores';
import { V3Card, V3Badge, V3Empty, V3Button } from '@/components';

export function Screen2Panel() {
  const { screen2, propagationStatus } = useThreeScreensStore();

  if (!screen2) {
    return (
      <V3Card title="Screen 2 — 战术层" subtitle="日线入场预设" padding="lg">
        <V3Empty
          title="等待方向约束"
          description={propagationStatus === 'idle' ? '需要 Screen1 先输出方向锚' : '计算预设价位中...'}
          action={propagationStatus === 's1_complete' && (
            <V3Button variant="primary" size="sm">启动 Screen2 计算</V3Button>
          )}
        />
      </V3Card>
    );
  }

  const { directionConstraint, presets, backtest, bayesianOpt } = screen2;
  const isLong = directionConstraint === 'bullish';

  return (
    <div className="space-y-4">
      {/* 方向约束状态 */}
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/30 border border-slate-700/20">
        <span className="text-xs text-slate-400">方向约束:</span>
        <V3Badge variant={isLong ? 'success' : directionConstraint === 'bearish' ? 'danger' : 'default'}>
          {directionConstraint?.toUpperCase() || 'NEUTRAL'}
        </V3Badge>
        <V3Badge variant={propagationStatus === 's2_complete' ? 'success' : 'info'}>
          {propagationStatus === 's2_complete' ? '完成' : '计算中'}
        </V3Badge>
      </div>

      {/* 预设策略列表 */}
      {presets && presets.length > 0 && (
        <V3Card title={`预设策略 (${presets.length})`} padding="sm">
          <div className="space-y-2">
            {presets.map((p) => (
              <div key={p.id} className="p-3 rounded-lg bg-slate-800/20 border border-slate-700/20">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-slate-200">{p.symbol}</span>
                  <V3Badge variant={p.confidence > 0.7 ? 'success' : p.confidence > 0.5 ? 'warning' : 'default'}>
                    置信 {(p.confidence * 100).toFixed(0)}%
                  </V3Badge>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  <MetricItem label="入场" value={`$${p.entry.toLocaleString()}`} positive />
                  <MetricItem label="止损" value={`$${p.stop.toLocaleString()}`} positive={false} />
                  <MetricItem label="目标" value={`$${p.target.toLocaleString()}`} positive />
                  <MetricItem label="周期" value={p.timeframe} positive />
                </div>
              </div>
            ))}
          </div>
        </V3Card>
      )}

      {/* 回测验证 */}
      {backtest && (
        <V3Card title="回测验证" padding="sm">
          <div className="grid grid-cols-4 gap-2">
            <MetricItem label="胜率" value={`${(backtest.winRate * 100).toFixed(1)}%`} positive={backtest.winRate > 0.5} />
            <MetricItem label="平均 R 倍" value={backtest.avgR.toFixed(2)} positive={backtest.avgR > 1} />
            <MetricItem label="最大回撤" value={`${(backtest.maxDD * 100).toFixed(2)}%`} positive={false} />
            <MetricItem label="Sharpe" value={backtest.sharpe.toFixed(2)} positive={backtest.sharpe > 1} />
          </div>
        </V3Card>
      )}

      {/* 贝叶斯优化 */}
      {bayesianOpt && (
        <V3Card title="贝叶斯优化" padding="sm">
          <div className="grid grid-cols-3 gap-2">
            <MetricItem label="迭代次数" value={`${bayesianOpt.iterations}`} positive />
            <MetricItem
              label="最优参数"
              value={Object.entries(bayesianOpt.bestParams).slice(0, 2).map(([k, v]) => `${k}=${v}`).join(', ')}
              positive
            />
            <MetricItem
              label="提升幅度"
              value={`${(bayesianOpt.improvement * 100).toFixed(1)}%`}
              positive={bayesianOpt.improvement > 0}
            />
          </div>
        </V3Card>
      )}
    </div>
  );
}

/** 指标项 */
function MetricItem({ label, value, positive }: { label: string; value: string; positive: boolean }) {
  return (
    <div className="text-center p-2 rounded bg-slate-800/20">
      <div className="text-[10px] text-slate-400 mb-0.5">{label}</div>
      <div className={`text-xs font-semibold ${positive ? 'text-emerald-400' : 'text-red-400'}`}>{value}</div>
    </div>
  );
}

export default Screen2Panel;
