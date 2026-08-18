'use client';

import { useThreeScreensStore } from '@/stores';
import { V3Card, V3StatusDot } from '@/components';

export function Screen2Panel() {
  const { screen1, screen2 } = useThreeScreensStore();

  if (!screen1?.directionAnchor) {
    return (
      <V3Card>
        <div className="flex items-center justify-center py-8 gap-2">
          <V3StatusDot status="idle" size="sm" />
          <span className="text-sm text-slate-500">等待 Screen1 方向约束...</span>
        </div>
      </V3Card>
    );
  }

  if (!screen2) {
    return <V3Card><p className="text-sm text-slate-500">Screen2 战术层未启动</p></V3Card>;
  }

  return (
    <V3Card title="Screen 2 · 战术层" subtitle="日线预设" badge={screen2.directionConstraint || undefined}>
      <div className="space-y-4">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">方向约束:</span>
          <span className={screen2.directionConstraint === 'bullish' ? 'text-emerald-400' : 'text-red-400'}>
            {screen2.directionConstraint === 'bullish' ? '仅做多' : '仅做空'}
          </span>
        </div>
        <div className="space-y-2">
          <p className="text-xs text-slate-500">预设入场方案</p>
          {screen2.presets.map(p => (
            <div key={p.id} className="grid grid-cols-6 gap-2 p-2 rounded-lg bg-slate-900/50 border border-slate-700/30 text-xs">
              <span className="text-slate-300 font-medium">{p.symbol}</span>
              <span className="text-slate-400">{p.entry}</span>
              <span className="text-red-400">{p.stop}</span>
              <span className="text-emerald-400">{p.target}</span>
              <span className="text-slate-500">{p.timeframe}</span>
              <span className={p.confidence >= 70 ? 'text-emerald-400' : 'text-amber-400'}>{p.confidence}%</span>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="p-2 rounded-lg bg-slate-900/30 border border-slate-700/20">
            <p className="text-[10px] text-slate-500 mb-1">回测指标</p>
            <div className="space-y-0.5 text-xs">
              <div className="flex justify-between"><span className="text-slate-500">胜率</span><span className="text-slate-300">{(screen2.backtest.winRate * 100).toFixed(0)}%</span></div>
              <div className="flex justify-between"><span className="text-slate-500">平均R</span><span className="text-slate-300">{screen2.backtest.avgR.toFixed(2)}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">最大回撤</span><span className="text-red-400">{(screen2.backtest.maxDD * 100).toFixed(1)}%</span></div>
              <div className="flex justify-between"><span className="text-slate-500">Sharpe</span><span className="text-slate-300">{screen2.backtest.sharpe.toFixed(2)}</span></div>
            </div>
          </div>
          <div className="p-2 rounded-lg bg-slate-900/30 border border-slate-700/20">
            <p className="text-[10px] text-slate-500 mb-1">贝叶斯优化</p>
            <div className="space-y-0.5 text-xs">
              <div className="flex justify-between"><span className="text-slate-500">迭代</span><span className="text-slate-300">{screen2.bayesianOpt.iterations}</span></div>
              <div className="flex justify-between"><span className="text-slate-500">改进</span><span className="text-emerald-400">{(screen2.bayesianOpt.improvement * 100).toFixed(0)}%</span></div>
            </div>
          </div>
        </div>
      </div>
    </V3Card>
  );
}
