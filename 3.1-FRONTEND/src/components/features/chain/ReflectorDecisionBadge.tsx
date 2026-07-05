'use client';

import React from 'react';
import type { ReflectorAction } from '@/stores';
import { V3Badge } from '@/components/V3Badge';

interface ReflectorDecisionBadgeProps {
  action: ReflectorAction;
  reason?: string;
  confidence?: number;
  showReason?: boolean;
}

const actionLabels: Record<ReflectorAction, string> = {
  CONTINUE: '继续',
  REDO: '重做',
  INSERT_BEFORE: '插入',
  JUMP_TO: '跳转',
  EARLY_TERMINATE: '终止',
  SKIP: '跳过',
};

const actionVariants: Record<ReflectorAction, 'success' | 'warning' | 'info' | 'danger' | 'default'> = {
  CONTINUE: 'success',
  REDO: 'warning',
  INSERT_BEFORE: 'info',
  JUMP_TO: 'warning',
  EARLY_TERMINATE: 'danger',
  SKIP: 'default',
};

export function ReflectorDecisionBadge({ action, reason, confidence, showReason = false }: ReflectorDecisionBadgeProps) {
  return (
    <div className="inline-flex items-center gap-1.5">
      <V3Badge variant={actionVariants[action]} dot={action !== 'CONTINUE' && action !== 'SKIP'}>
        {actionLabels[action]}
      </V3Badge>
      {confidence !== undefined && (
        <span className="text-[10px] text-gray-500">{(confidence * 100).toFixed(0)}%</span>
      )}
      {showReason && reason && (
        <span className="text-[10px] text-gray-400 ml-1 max-w-[200px] truncate" title={reason}>{reason}</span>
      )}
    </div>
  );
}

export default ReflectorDecisionBadge;
