'use client';

import React from 'react';
import { useChainStore } from '@/stores';
import type { ChainStep, ReflectorDecision } from '@/stores';
import { V3Card } from '@/components/V3Card';
import { V3Badge } from '@/components/V3Badge';
import { V3StatusDot } from '@/components/V3StatusDot';
import { V3Empty } from '@/components/V3Empty';

// SACG 层颜色映射
const layerColors: Record<string, string> = {
  S: 'border-l-purple-500',
  A: 'border-l-blue-500',
  C: 'border-l-emerald-500',
  F: 'border-l-amber-500',
  D: 'border-l-gray-500',
  Z: 'border-l-gray-500',
  E: 'border-l-gray-500',
};

// 步骤状态颜色
const stepStatusColors: Record<string, string> = {
  pending: 'text-gray-500',
  active: 'text-blue-400',
  done: 'text-emerald-400',
  failed: 'text-red-400',
  skipped: 'text-gray-600',
};

// 步骤状态指示
const stepStatusDot: Record<string, 'idle' | 'active' | 'success' | 'error' | 'loading'> = {
  pending: 'idle',
  active: 'active',
  done: 'success',
  failed: 'error',
  skipped: 'idle',
};

// Reflector 决策颜色
const reflectorColors: Record<string, string> = {
  CONTINUE: 'info',
  REDO: 'warning',
  INSERT_BEFORE: 'info',
  JUMP_TO: 'warning',
  EARLY_TERMINATE: 'danger',
  SKIP: 'default',
} as const;

export function ChainTracker() {
  const {
    activeChain, steps, activeStepIndex,
    reflectorHistory, artifacts,
  } = useChainStore();

  if (!activeChain) {
    return (
      <V3Card title="链路追踪" padding="md">
        <V3Empty title="暂无活跃链路" description="发起对话后可查看执行链路追踪" />
      </V3Card>
    );
  }

  const chainColor = layerColors[activeChain.chainType] || 'border-l-gray-500';

  return (
    <div className="space-y-3">
      {/* 链信息头 */}
      <div className={`border-l-2 ${chainColor} pl-3 py-2 bg-gray-900/40 rounded-r-lg`}>
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-gray-100">{activeChain.chainName}</span>
              <V3Badge variant={`sacg-${activeChain.chainType.toLowerCase()}` as any} dot pulse={activeChain.status === 'running'}>
                {activeChain.chainType}
              </V3Badge>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              ID: {activeChain.chainId.slice(0, 8)}...
            </p>
          </div>
          <V3Badge variant={activeChain.status === 'running' ? 'info' : activeChain.status === 'completed' ? 'success' : activeChain.status === 'failed' ? 'danger' : 'default'}>
            {activeChain.status}
          </V3Badge>
        </div>
      </div>

      {/* 步骤列表 */}
      <div className="space-y-1.5">
        {steps.map((step, index) => (
          <ChainStepRow key={step.id} step={step} isActive={index === activeStepIndex} />
        ))}
      </div>

      {/* Reflector 决策 */}
      {reflectorHistory.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700/30">
          <h4 className="text-xs font-semibold text-gray-400 mb-2">Reflector 决策</h4>
          <div className="space-y-1.5">
            {reflectorHistory.slice(0, 5).map((rd, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="text-gray-500 w-16 truncate">{rd.stepId}</span>
                <V3Badge variant={reflectorColors[rd.action] || 'default'}>
                  {rd.action}
                </V3Badge>
                <span className="text-gray-400 truncate flex-1">{rd.reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 产物 */}
      {artifacts.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700/30">
          <h4 className="text-xs font-semibold text-gray-400 mb-2">链产物 ({artifacts.length})</h4>
          <div className="space-y-1">
            {artifacts.map((a) => (
              <div key={a.id} className="flex items-center gap-2 text-xs text-gray-300 px-2 py-1 rounded bg-gray-800/30">
                <span className="text-gray-500">[{a.type}]</span>
                <span className="truncate">{a.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// 单步骤行
function ChainStepRow({ step, isActive }: { step: ChainStep; isActive: boolean }) {
  return (
    <div className={`
      flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors
      ${isActive ? 'bg-blue-500/10 border border-blue-500/20' : 'bg-gray-800/20 border border-transparent hover:bg-gray-800/40'}
    `}>
      <V3StatusDot status={stepStatusDot[step.status]} size="sm" pulse={isActive} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-medium truncate ${stepStatusColors[step.status]}`}>
            {step.name}
          </span>
          {step.reflectorAction && (
            <V3Badge variant={reflectorColors[step.reflectorAction] || 'default'} className="text-[10px]">
              {step.reflectorAction}
            </V3Badge>
          )}
        </div>
        {step.reflectorReason && (
          <p className="text-[10px] text-gray-500 mt-0.5 truncate">{step.reflectorReason}</p>
        )}
      </div>
      {step.tokensUsed && (
        <span className="text-[10px] text-gray-500 shrink-0">{step.tokensUsed}tok</span>
      )}
      {step.latencyMs && (
        <span className="text-[10px] text-gray-500 shrink-0">{step.latencyMs}ms</span>
      )}
    </div>
  );
}

export default ChainTracker;
