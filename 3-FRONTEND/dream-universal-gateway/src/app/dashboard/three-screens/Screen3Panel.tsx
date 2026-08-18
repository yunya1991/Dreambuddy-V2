'use client';

import { useThreeScreensStore } from '@/stores';
import { V3Card, V3StatusDot, V3Badge } from '@/components';

const pipelineLabels: Record<string, string> = {
  A7: '入场扫描', A4: '马丁计算', C3: '风控检查', A5: '信号确认', A6: '下单执行', A9: '监控跟踪',
};

export function Screen3Panel() {
  const { screen3 } = useThreeScreensStore();

  if (!screen3) {
    return <V3Card><p className="text-sm text-slate-500">Screen3 执行层未启动</p></V3Card>;
  }

  return (
    <V3Card title="Screen 3 · 执行层" subtitle="A7→A9 流水线">
      <div className="space-y-4">
        <div className="flex items-center gap-1">
          {screen3.pipeline.map((step, i) => (
            <div key={step.id} className="flex items-center gap-1">
              <div className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] ${step.status === 'done' ? 'bg-emerald-900/30 text-emerald-400' : step.status === 'running' ? 'bg-blue-900/30 text-blue-400 animate-pulse' : step.status === 'failed' ? 'bg-red-900/30 text-red-400' : 'bg-slate-800 text-slate-500'}`}>
                <V3StatusDot status={step.status === 'done' ? 'success' : step.status === 'running' ? 'active' : step.status === 'failed' ? 'error' : 'idle'} size="sm" />
                {pipelineLabels[step.name] || step.name}
              </div>
              {i < screen3.pipeline.length - 1 && <span className="text-slate-600">→</span>}
            </div>
          ))}
        </div>
        {screen3.positionState && (
          <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/30">
            <p className="text-[10px] text-slate-500 mb-2">当前持仓</p>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <span className="text-slate-300">{screen3.positionState.symbol}</span>
              <span className={screen3.positionState.side === 'long' ? 'text-emerald-400' : 'text-red-400'}>{screen3.positionState.side}</span>
              <span className={screen3.positionState.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}>{screen3.positionState.pnl >= 0 ? '+' : ''}{screen3.positionState.pnl.toFixed(2)}</span>
            </div>
          </div>
        )}
        {screen3.monitorAlerts.length > 0 && (
          <div className="space-y-1">
            {screen3.monitorAlerts.map(a => (
              <div key={a.id} className={`flex items-center gap-2 p-2 rounded text-[10px] ${a.level === 'critical' ? 'bg-red-900/20 text-red-400' : a.level === 'warning' ? 'bg-amber-900/20 text-amber-400' : 'bg-slate-800 text-slate-400'}`}>
                <V3StatusDot status={a.level === 'critical' ? 'error' : 'warning'} size="sm" />
                {a.message}
              </div>
            ))}
          </div>
        )}
      </div>
    </V3Card>
  );
}
