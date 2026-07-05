'use client';

import React from 'react';
import { useThreeScreensStore } from '@/stores';
import { V3Card } from '@/components/V3Card';
import { V3Badge } from '@/components/V3Badge';
import { V3Empty } from '@/components/V3Empty';
import { V3Button } from '@/components/V3Button';

export function Screen2Panel() {
  const { screen2, directionConstraint } = useThreeScreensStore();

  if (!screen2 || directionConstraint === null) {
    return (
      <V3Card title="Screen 2 — 战术层" subtitle="日线入场预设" padding="lg">
        <V3Empty
          title="等待方向约束"
          description={directionConstraint === null ? '需要 Screen1 先输出方向锚' : '计算预设价位中...'}
        />
      </V3Card>
    );
  }

  const { presets, backtest, bayesianOpt, status } = screen2;
  const isLong = directionConstraint?.direction === 'LONG';

  return (
    <div className="space-y-4">
      {/* 方向约束状态 */}
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-800/30 border border-gray-700/20">
        <span className="text-xs text-gray-400">方向约束:</span>
        <V3Badge variant={isLong ? 'success' : 'danger'}>
          {isLong ? 'LONG' : 'SHORT'}
        </V3Badge>
        <V3Badge variant={status === 'done' ? 'success' : status === 'computing' ? 'info' : 'default'}>
          {status}
        </V3Badge>
      </div>

      {/* 三大预设价位 */}
      <V3Card title="三大预设价位" padding="sm">
        <div className="grid grid-cols-2 gap-3">
          <PresetCard label="入场价" price={presets.entry.price} strength={presets.entry.strength} positive />
          <PresetCard label="加仓价" price={presets.addPosition.price} extra={`${presets.addPosition.size}% 仓位`} positive={isLong} />
          <PresetCard label="止盈价" price={presets.takeProfit.price} extra={`${presets.takeProfit.levels.length} 档`} positive />
          <PresetCard label="止损价" price={presets.stopLoss.price} extra={`${presets.stopLoss.levels.length} 档`} positive={false} />
        </div>
      </V3Card>

      {/* 回测验证 */}
      {backtest && (
        <V3Card title="回测验证" padding="sm">
          <div className="grid grid-cols-4 gap-2">
            <MetricItem label="胜率" value={`${(backtest.winRate * 100).toFixed(1)}%`} positive={backtest.winRate > 0.5} />
            <MetricItem label="平均收益" value={`${(backtest.avgReturn * 100).toFixed(2)}%`} positive={backtest.avgReturn > 0} />
            <MetricItem label="最大回撤" value={`${(backtest.maxDrawdown * 100).toFixed(2)}%`} positive={false} />
            <MetricItem label="样本量" value={`${backtest.sampleSize}`} positive />
          </div>
        </V3Card>
      )}

      {/* 贝叶斯优化 */}
      {bayesianOpt && (
        <V3Card title="贝叶斯优化" padding="sm">
          <div className="grid grid-cols-3 gap-2">
            <MetricItem label="迭代次数" value={`${bayesianOpt.iterations}`} positive />
            <MetricItem label="最优参数" value={Object.entries(bayesianOpt.bestParams).slice(0, 2).map(([k, v]) => `${k}=${v}`).join(', ')} positive />
            <MetricItem label="提升幅度" value={`${(bayesianOpt.improvement * 100).toFixed(1)}%`} positive={bayesianOpt.improvement > 0} />
          </div>
        </V3Card>
      )}
    </div>
  );
}

/** 预设价位卡片 */
function PresetCard({ label, price, strength, extra, positive }: {
  label: string;
  price: number;
  strength?: string;
  extra?: string;
  positive: boolean;
}) {
  return (
    <div className="p-3 rounded-lg bg-gray-800/20 border border-gray-700/20">
      <div className="text-[10px] text-gray-400 mb-1">{label}</div>
      <div className={`text-sm font-semibold ${positive ? 'text-emerald-400' : 'text-red-400'}`}>
        {price.toLocaleString()}
      </div>
      {strength && (
        <V3Badge variant={strength === 'strong' ? 'success' : strength === 'moderate' ? 'warning' : 'default'} className="mt-1">
          {strength}
        </V3Badge>
      )}
      {extra && <div className="text-[10px] text-gray-500 mt-1">{extra}</div>}
    </div>
  );
}

/** 指标项 */
function MetricItem({ label, value, positive }: { label: string; value: string; positive: boolean }) {
  return (
    <div className="text-center p-2 rounded bg-gray-800/20">
      <div className="text-[10px] text-gray-400 mb-0.5">{label}</div>
      <div className={`text-xs font-semibold ${positive ? 'text-emerald-400' : 'text-red-400'}`}>{value}</div>
    </div>
  );
}

export default Screen2Panel;
