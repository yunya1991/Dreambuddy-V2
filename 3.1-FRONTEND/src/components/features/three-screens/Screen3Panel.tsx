'use client';

import React from 'react';
import { useThreeScreensStore } from '@/stores';
import { V3Card } from '@/components/V3Card';
import { V3Badge } from '@/components/V3Badge';
import { V3StatusDot } from '@/components/V3StatusDot';
import { V3Empty } from '@/components/V3Empty';

// 步骤 ID 到中文标签的映射
const stepLabels: Record<string, string> = {
  A7_GATE: 'A7 风控门禁',
  A4_VALIDATE: 'A4 方案验证',
  C3_GATE: 'C3 门禁检查',
  A5_ENTRY: 'A5 入场执行',
  A6_MONITOR: 'A6 情报监控',
  A9_EXIT: 'A9 离场评估',
};

// 步骤状态映射到 V3StatusDot 状态
const stepStatusMap: Record<string, 'idle' | 'active' | 'success' | 'error'> = {
  pending: 'idle',
  active: 'active',
  passed: 'success',
  failed: 'error',
  skipped: 'idle',
};

export function Screen3Panel() {
  const { screen3, directionConstraint, presetConstraint } = useThreeScreensStore();

  if (!screen3 || !presetConstraint) {
    return (
      <V3Card title="Screen 3 — 执行层" subtitle="实时监控与执行" padding="lg">
        <V3Empty
          title="等待执行"
          description={!directionConstraint ? '需要方向约束' : '需要预设价位约束'}
        />
      </V3Card>
    );
  }

  const { pipeline, position, monitor, status } = screen3;

  return (
    <div className="space-y-4">
      {/* 方向 + 预设约束 */}
      <div className="flex gap-2">
        <V3Badge variant={directionConstraint?.direction === 'LONG' ? 'success' : 'danger'}>
          方向: {directionConstraint?.direction}
        </V3Badge>
        <V3Badge variant="info">
          入场: {presetConstraint.entry.price}
        </V3Badge>
        <V3Badge variant={status === 'executing' ? 'info' : status === 'done' ? 'success' : 'default'}>
          {status}
        </V3Badge>
      </div>

      {/* 执行流水线 */}
      <V3Card title="执行流水线" padding="sm">
        <div className="flex items-center gap-1">
          {pipeline.steps.map((step, i) => (
            <React.Fragment key={step.id}>
              <div className={`
                flex-1 flex flex-col items-center gap-1.5 p-2 rounded-lg transition-colors
                ${step.status === 'active' ? 'bg-blue-500/10 border border-blue-500/20' : 'bg-gray-800/20 border border-transparent'}
              `}>
                <V3StatusDot status={stepStatusMap[step.status]} size="sm" pulse={step.status === 'active'} />
                <span className="text-[10px] text-gray-300 text-center leading-tight">{stepLabels[step.id]}</span>
                {step.status === 'passed' && <span className="text-[9px] text-emerald-400">PASS</span>}
                {step.status === 'failed' && <span className="text-[9px] text-red-400">FAIL</span>}
              </div>
              {i < pipeline.steps.length - 1 && (
                <div className={`w-4 h-px ${pipeline.steps[i + 1].status !== 'pending' ? 'bg-blue-500/30' : 'bg-gray-700/30'}`} />
              )}
            </React.Fragment>
          ))}
        </div>
      </V3Card>

      {/* 持仓状态 */}
      {position.isOpen && (
        <V3Card title="持仓状态" padding="sm">
          <div className="grid grid-cols-3 gap-2">
            <div className="p-2 rounded bg-gray-800/20 text-center">
              <div className="text-[10px] text-gray-400">入场价</div>
              <div className="text-xs font-semibold text-gray-200">{position.entryPrice}</div>
            </div>
            <div className="p-2 rounded bg-gray-800/20 text-center">
              <div className="text-[10px] text-gray-400">当前价</div>
              <div className="text-xs font-semibold text-gray-200">{position.currentPrice}</div>
            </div>
            <div className="p-2 rounded bg-gray-800/20 text-center">
              <div className="text-[10px] text-gray-400">未实现盈亏</div>
              <div className={`text-xs font-semibold ${position.unrealizedPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {position.unrealizedPnl >= 0 ? '+' : ''}{position.unrealizedPnl.toFixed(2)}
              </div>
            </div>
          </div>
        </V3Card>
      )}

      {/* 监控告警 */}
      {monitor.alertCount > 0 && (
        <V3Card title={`告警 (${monitor.alertCount})`} padding="sm">
          <div className="space-y-1.5">
            {monitor.activeAlerts.slice(0, 5).map((alert) => (
              <div key={alert.id} className="flex items-center gap-2 px-2 py-1.5 rounded bg-gray-800/20">
                <V3Badge variant={alert.severity === 'critical' ? 'danger' : alert.severity === 'warning' ? 'warning' : 'default'}>
                  {alert.severity}
                </V3Badge>
                <span className="text-xs text-gray-300 truncate flex-1">{alert.message}</span>
              </div>
            ))}
          </div>
        </V3Card>
      )}
    </div>
  );
}

export default Screen3Panel;
