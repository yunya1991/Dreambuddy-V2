'use client';

import React, { useCallback } from 'react';
import { useSessionStore, useChainStore } from '@/stores';
import { V3Card, V3Badge } from '@/components';

type InterventionAction = 'continue' | 'finalize' | 'skip';

/**
 * StepInterventionPanel — 常驻人工干预面板
 * 始终可见，用户可在任务执行中或等待确认时主动干预：
 *   继续 (continue) — 执行下一步
 *   完成 (finalize) — 提前结束当前链路
 *   跳过 (skip)     — 跳过当前步骤
 *
 * 与 ChatPanel 内的被动弹出面板互补：
 *   - 被动面板：后端 emit awaiting_confirmation 才显示
 *   - 本面板：常驻显示，支持执行中主动干预（无需后端暂停）
 */
export function StepInterventionPanel() {
  const { isStreaming, pendingStepConfirmation } = useSessionStore();
  const { steps, currentStepIndex } = useChainStore();

  const currentChainStep = currentStepIndex >= 0 ? steps[currentStepIndex] : undefined;
  // 优先展示后端等待确认的步骤名，其次链路当前步骤
  const stepName = pendingStepConfirmation?.current_step || currentChainStep?.name || '当前任务';
  const description = pendingStepConfirmation?.next_step;

  // 可干预状态：等待确认 或 执行中
  const canIntervene = !!pendingStepConfirmation || isStreaming;

  const handleIntervene = useCallback((action: InterventionAction) => {
    const storeState = useSessionStore.getState();
    const sessionId = storeState.activeSessionId;
    if (!sessionId) return;

    const pending = storeState.pendingStepConfirmation;
    const chainState = useChainStore.getState();
    const chainStep = chainState.currentStepIndex >= 0 ? chainState.steps[chainState.currentStepIndex] : undefined;
    const targetStepId = pending?.current_step || chainStep?.id || 'current';
    const targetStepName = pending?.current_step || chainStep?.name || '当前任务';

    // 清除待确认状态（若存在）
    if (pending) {
      storeState.setPendingStepConfirmation(null);
    }

    // 发送干预信号到后端（FAIL-OPEN：后端不可达时不阻塞）
    try {
      fetch('/api/task/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionId, stepId: targetStepId, action }),
      }).catch(() => {});
    } catch {
      // FAIL-OPEN
    }

    // 本地记录用户干预
    const actionLabel = action === 'continue' ? '继续执行' : action === 'finalize' ? '确认完成' : '跳过步骤';
    storeState.addMessage(sessionId, {
      id: `msg_${Date.now()}`,
      role: 'system',
      content: `⚡ 人工干预: ${actionLabel} — ${targetStepName}`,
      timestamp: Date.now(),
    });
  }, []);

  // 状态徽章
  const stateBadge = pendingStepConfirmation ? (
    <V3Badge variant="warning" dot pulse>等待确认</V3Badge>
  ) : isStreaming ? (
    <V3Badge variant="info" dot pulse>执行中</V3Badge>
  ) : (
    <V3Badge variant="default">就绪</V3Badge>
  );

  return (
    <V3Card title="人工干预" subtitle="提前介入" padding="sm" badge={stateBadge}>
      <div className="space-y-2">
        {/* 当前步骤 */}
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500">当前步骤:</span>
          <span className="font-medium text-slate-200 truncate">{stepName}</span>
        </div>
        {description && (
          <p className="text-[11px] text-amber-400/70 leading-relaxed">{description}</p>
        )}

        {/* 干预按钮 */}
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => handleIntervene('continue')}
            disabled={!canIntervene}
            className="flex-1 px-3 py-1.5 text-xs rounded-lg bg-emerald-600/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-600/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ✓ 继续
          </button>
          <button
            onClick={() => handleIntervene('finalize')}
            disabled={!canIntervene}
            className="flex-1 px-3 py-1.5 text-xs rounded-lg bg-blue-600/20 text-blue-300 border border-blue-500/30 hover:bg-blue-600/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ✓ 完成
          </button>
          <button
            onClick={() => handleIntervene('skip')}
            disabled={!canIntervene}
            className="flex-1 px-3 py-1.5 text-xs rounded-lg bg-slate-700/30 text-slate-400 border border-slate-600/30 hover:bg-slate-700/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ⏭ 跳过
          </button>
        </div>

        {!canIntervene && (
          <p className="text-[10px] text-slate-500 leading-relaxed">
            任务执行中或等待确认时可主动干预
          </p>
        )}
      </div>
    </V3Card>
  );
}

export default StepInterventionPanel;
