'use client';

import React from 'react';
import { useChainStore } from '@/stores';
import { V3Card, V3Badge, V3Empty } from '@/components';

export function CrossValidationPanel() {
  const { crossValidations } = useChainStore();

  if (crossValidations.length === 0) {
    return (
      <V3Card title="交叉验证" subtitle="三链投票" padding="sm">
        <V3Empty title="未启用" description="发起复杂任务后自动启用三链交叉验证" />
      </V3Card>
    );
  }

  return (
    <V3Card title={`交叉验证 (${crossValidations.length})`} subtitle="三链投票" padding="sm">
      <div className="space-y-2">
        {crossValidations.map((cv) => (
          <div key={cv.chainId} className="p-2 rounded-lg bg-slate-800/20 border border-slate-700/20">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-slate-300">{cv.chainId}</span>
              <V3Badge variant={cv.result === 'pass' ? 'success' : cv.result === 'fail' ? 'danger' : 'warning'}>
                {cv.result === 'pass' ? '通过' : cv.result === 'fail' ? '未通过' : '部分通过'}
              </V3Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-slate-400">置信度</span>
              <span className="text-xs text-slate-300">{(cv.confidence * 100).toFixed(0)}%</span>
            </div>
            {cv.disagreements.length > 0 && (
              <div className="mt-1 pt-1 border-t border-slate-700/20">
                <span className="text-[10px] text-amber-400">分歧: {cv.disagreements.join(', ')}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </V3Card>
  );
}

export default CrossValidationPanel;
