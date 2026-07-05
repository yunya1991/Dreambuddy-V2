'use client';

import React from 'react';
import { useChainStore } from '@/stores';
import { V3Card } from '@/components/V3Card';
import { V3Badge } from '@/components/V3Badge';
import { V3Empty } from '@/components/V3Empty';

export function CrossValidationPanel() {
  const { crossValidation } = useChainStore();

  if (!crossValidation.enabled || crossValidation.votes.length === 0) {
    return (
      <V3Card title="交叉验证" subtitle="三链投票" padding="sm">
        <V3Empty title="未启用" description="发起复杂任务后自动启用三链交叉验证" />
      </V3Card>
    );
  }

  return (
    <V3Card title="交叉验证" subtitle={`${crossValidation.votes.length} 链投票`} padding="sm">
      <div className="space-y-2">
        {crossValidation.votes.map((vote, i) => (
          <div key={i} className="flex items-center justify-between px-2 py-1.5 rounded bg-gray-800/20">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-gray-300">{vote.chainType}</span>
              <span className="text-xs text-gray-400">{vote.decision}</span>
            </div>
            <V3Badge variant={vote.confidence > 0.8 ? 'success' : vote.confidence > 0.5 ? 'warning' : 'danger'}>
              {(vote.confidence * 100).toFixed(0)}%
            </V3Badge>
          </div>
        ))}
        {crossValidation.finalDecision && (
          <div className="mt-2 pt-2 border-t border-gray-700/20 flex items-center gap-2">
            <span className="text-xs text-gray-400">最终决策:</span>
            <V3Badge variant="info">{crossValidation.finalDecision}</V3Badge>
          </div>
        )}
      </div>
    </V3Card>
  );
}

export default CrossValidationPanel;
