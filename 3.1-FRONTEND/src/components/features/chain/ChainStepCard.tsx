'use client';

import React, { useState } from 'react';
import type { ChainStep } from '@/stores';
import { V3StatusDot } from '@/components';
import { V3Badge } from '@/components';
import { IconChevronDown } from '@/components';

interface ChainStepCardProps {
  step: ChainStep;
  isActive: boolean;
}

const statusLabels: Record<string, string> = {
  pending: '等待中',
  active: '执行中',
  done: '已完成',
  failed: '失败',
  skipped: '跳过',
};

const statusDotMap: Record<string, 'idle' | 'active' | 'success' | 'error' | 'loading'> = {
  pending: 'idle',
  active: 'active',
  done: 'success',
  failed: 'error',
  skipped: 'idle',
};

export function ChainStepCard({ step, isActive }: ChainStepCardProps) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = step.reflectorReason || step.artifact;

  return (
    <div
      className={`
        rounded-lg border transition-all cursor-pointer
        ${isActive ? 'bg-blue-500/10 border-blue-500/20' : 'bg-gray-800/20 border-gray-700/20 hover:border-gray-600/30'}
      `}
      onClick={() => hasDetails && setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2.5 px-3 py-2">
        <V3StatusDot status={statusDotMap[step.status]} size="sm" pulse={isActive} />
        <span className="text-xs font-medium text-gray-200 flex-1 truncate">{step.name}</span>
        <V3Badge variant={step.status === 'done' ? 'success' : step.status === 'active' ? 'info' : step.status === 'failed' ? 'danger' : 'default'}>
          {statusLabels[step.status]}
        </V3Badge>
        {hasDetails && (
          <IconChevronDown className={`w-3.5 h-3.5 text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        )}
      </div>

      {expanded && hasDetails && (
        <div className="px-3 pb-2.5 space-y-2 border-t border-gray-700/20 pt-2">
          {step.reflectorAction && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-gray-500">Reflector:</span>
              <span className="text-amber-400 font-medium">{step.reflectorAction}</span>
            </div>
          )}
          {step.reflectorReason && (
            <p className="text-xs text-gray-400">{step.reflectorReason}</p>
          )}
          {step.artifact && (
            <div className="text-xs text-gray-400 bg-gray-800/30 rounded p-2">
              <span className="text-gray-500">产物: </span>{step.artifact}
            </div>
          )}
          {(step.tokensUsed || step.latencyMs) && (
            <div className="flex gap-3 text-[10px] text-gray-500">
              {step.tokensUsed && <span>tokens: {step.tokensUsed}</span>}
              {step.latencyMs && <span>latency: {step.latencyMs}ms</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ChainStepCard;
