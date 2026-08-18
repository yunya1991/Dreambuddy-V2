'use client';

import React from 'react';
import { useThreeScreensStore } from '@/stores';
import { V3Card, V3Badge, V3StatusDot, V3Empty } from '@/components';

// 步骤状态映射到 V3StatusDot 状态
const stepStatusMap: Record<string, 'idle' | 'active' | 'success' | 'error'> = {
  pending: 'idle',
  running: 'active',
  done: 'success',
  failed: 'error',
};

const stepLabels: Record<string, string> = {
  A7_GATE: 'A7 风控门禁',
  A4_VALIDATE: 'A4 方案验证',
  C3_GATE: 'C3 门禁检查',
  A5_ENTRY: 'A5 入场执行',
  A6_MONITOR: 'A6 情报监控',
  A9_EXIT: 'A9 离场评估',
};

export function Screen3Panel() {
  const { screen3, propagationStatus } = useThreeScreensStore();

  if (!screen3) {
    return (
      <V3Card title="Screen 3 — 执行层" subtitle="实时监控与执行" padding="lg">
        <V3Empty
          title="等待执行"
          description={propagationStatus === 's2_complete' ? 'Screen2 已完成，准备执行...' : '需要 Screen2 先输出预设策略'}
        />
      </V3Card>
    );
  }

  const { pipeline, positionState, monitorAlerts } = screen3;

  return (
    <div className="space-y-4">
      {/* 状态 */}
      <div className="flex items-center gap-2">
        <V3Badge variant={propagationStatus === 'complete' ? 'success' : propagationStatus === 's3_running' ? 'info' : 'default'}>
          {propagationStatus === 'complete' ? '执行完成' : propagationStatus === 's3_running' ? '执行中' : '等待中'}
        </V3Badge>
      </div>

      {/* 执行流水线 */}
      {pipeline && pipeline.length > 0 && (
        <V3Card title="执行流水线" padding="sm">
          <div className="flex items-center gap-1">
            {pipeline.map((step, i) => (
              <React.Fragment key={step.id}>
                <div className={`
                  flex-1 flex flex-col items-center gap-1.5 p-2 rounded-lg transition-colors
                  ${step.status === 'running' ? 'bg-blue-500/10 border border-blue-500/20' : 'bg-slate-800/20 border border-transparent'}
                `}>
                  <V3StatusDot status={stepStatusMap[step.status] || 'idle'} size="sm" pulse={step.status === 'running'} />
                  <span className="text-[10px] text-slate-300 text-center leading-tight">
                    {stepLabels[step.name] || step.name}
                  </span>
                  {step.status === 'done' && <span className="text-[9px] text-emerald-400">PASS</span>}
                  {step.status === 'failed' && <span className="text-[9px] text-red-400">FAIL</span>}
                  {step.output && <span className="text-[8px] text-slate-500 max-w-[60px] truncate">{step.output}</span>}
                </div>
                {i < pipeline.length - 1 && (
                  <div className={`w-4 h-px ${pipeline[i + 1].status !== 'pending' ? 'bg-blue-500/30' : 'bg-slate-700/30'}`} />
                )}
              </React.Fragment>
            ))}
          </div>
        </V3Card>
      )}

      {/* 持仓状态 */}
      {positionState && (
        <V3Card title="持仓状态" padding="sm">
          <div className="grid grid-cols-3 gap-2">
            <div className="p-2 rounded bg-slate-800/20 text-center">
              <div className="text-[10px] text-slate-400">入场价</div>
              <div className="text-xs font-semibold text-slate-200">{positionState.entry}</div>
            </div>
            <div className="p-2 rounded bg-slate-800/20 text-center">
              <div className="text-[10px] text-slate-400">当前价</div>
              <div className="text-xs font-semibold text-slate-200">{positionState.current}</div>
            </div>
            <div className="p-2 rounded bg-slate-800/20 text-center">
              <div className="text-[10px] text-slate-400">未实现盈亏</div>
              <div className={`text-xs font-semibold ${positionState.pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {positionState.pnl >= 0 ? '+' : ''}{positionState.pnl.toFixed(2)}
              </div>
            </div>
          </div>
        </V3Card>
      )}

      {/* 监控告警 */}
      {monitorAlerts && monitorAlerts.length > 0 && (
        <V3Card title={`告警 (${monitorAlerts.length})`} padding="sm">
          <div className="space-y-1.5">
            {monitorAlerts.slice(0, 5).map((alert) => (
              <div key={alert.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-slate-800/20">
                <V3Badge variant={alert.level === 'critical' ? 'danger' : alert.level === 'warning' ? 'warning' : 'default'}>
                  {alert.level}
                </V3Badge>
                <span className="text-xs text-slate-300 truncate flex-1">{alert.message}</span>
              </div>
            ))}
          </div>
        </V3Card>
      )}
    </div>
  );
}

export default Screen3Panel;
