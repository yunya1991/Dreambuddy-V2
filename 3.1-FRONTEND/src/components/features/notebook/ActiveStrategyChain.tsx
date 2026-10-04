'use client';

// ============================================================
// ActiveStrategyChain — S系列策略思维链可视化 (3.1 Tailwind 版)
// 显示 S1→S2→S3→S4→S5 策略思维链
// ============================================================

import type { StrategyChainState, StrategyStep } from '@/lib/strategy/types';

interface Props {
  chain: StrategyChainState | null;
  compact?: boolean;
  onStepClick?: (stepId: string) => void;
}

const STEP_INFO: Record<string, { name: string; desc: string }> = {
  S1_RESEARCH: { name: '调研', desc: '市场数据收集' },
  S2_ANALYSIS: { name: '分析', desc: '多维度分析' },
  S3_DESIGN: { name: '设计', desc: '策略方案制定' },
  S4_VALIDATE: { name: '验证', desc: '回测风险评估' },
  S5_EXECUTE: { name: '执行', desc: '执行计划跟踪' },
};

const statusStyles: Record<string, { bg: string; border: string; text: string }> = {
  pending: { bg: 'bg-slate-800', border: 'border-slate-700', text: 'text-slate-500' },
  active: { bg: 'bg-violet-900/40', border: 'border-violet-600', text: 'text-white' },
  done: { bg: 'bg-emerald-700', border: 'border-emerald-600', text: 'text-white' },
  skipped: { bg: 'bg-slate-600', border: 'border-slate-500', text: 'text-slate-300' },
};

function getStepIcon(status: string): string {
  switch (status) {
    case 'active': return '▶';
    case 'done': return '✓';
    case 'skipped': return '⏭';
    default: return '⬜';
  }
}

export default function ActiveStrategyChain({ chain, compact, onStepClick }: Props) {
  if (!chain) {
    return (
      <div className="p-3 bg-slate-950 border border-dashed border-slate-700 rounded-lg text-xs text-slate-500 text-center">
        S系列策略链未初始化 · 使用 /分析 等命令启动
      </div>
    );
  }

  const totalDone = chain.steps.filter(
    (s) => s.status === 'done' || s.status === 'skipped'
  ).length;
  const total = chain.steps.length;

  return (
    <div className={`p-3 bg-slate-950 border border-slate-800 rounded-lg`}>
      {/* 标题栏 */}
      <div className="flex justify-between items-center mb-2.5 text-xs text-slate-500">
        <span className="font-semibold text-slate-300">🎯 S系列策略思维链</span>
        <span>
          {totalDone}/{total} 步骤 · {chain.complexity === 'quick' ? '快速' : chain.complexity === 'standard' ? '标准' : '深度'}
        </span>
      </div>

      {/* 步骤流程 */}
      <div className="flex items-center justify-between gap-1">
        {chain.steps.map((step: StrategyStep, idx) => {
          const style = statusStyles[step.status];
          const isLast = idx === chain.steps.length - 1;
          const info = STEP_INFO[step.id] || { name: step.id, desc: '' };

          return (
            <div key={step.id} className={`flex items-center ${isLast ? '' : 'flex-1'}`}>
              <div
                onClick={() => onStepClick?.(step.id)}
                title={`${info.name} - ${info.desc}`}
                className={`${compact ? 'w-12 h-12' : 'w-15 h-15'} rounded-full ${style.bg} border-2 ${style.border} ${style.text} flex flex-col items-center justify-center ${compact ? 'text-sm' : 'text-base'} ${onStepClick ? 'cursor-pointer' : ''} shrink-0 transition-all hover:opacity-80`}
                style={{ width: compact ? 48 : 60, height: compact ? 48 : 60 }}
              >
                <span className={compact ? 'text-[10px]' : 'text-xs'}>{getStepIcon(step.status)}</span>
                <span className={`${compact ? 'text-[10px]' : 'text-[11px]'} mt-0.5`}>{step.number}</span>
              </div>
              {!isLast && (
                <div
                  className={`flex-1 h-0.5 -mx-0.5 min-w-[8px] ${
                    chain.steps[idx + 1]?.status !== 'pending' ? 'bg-violet-600' : 'bg-slate-700'
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* 步骤名称 */}
      {!compact && (
        <div className="mt-3 flex justify-between gap-1">
          {chain.steps.map((step) => {
            const style = statusStyles[step.status];
            const info = STEP_INFO[step.id] || { name: step.id, desc: '' };
            return (
              <div
                key={step.id}
                onClick={() => onStepClick?.(step.id)}
                className={`flex-1 text-center text-[11px] rounded p-1 ${
                  step.status === 'active'
                    ? 'text-violet-400 font-bold bg-violet-950/20'
                    : step.status === 'done'
                    ? 'text-emerald-400'
                    : style.text
                } ${onStepClick ? 'cursor-pointer' : ''}`}
              >
                <div className="font-semibold">{info.name}</div>
                <div className="text-[9px] opacity-70 mt-0.5">
                  {step.status === 'active' ? '进行中' : step.status === 'done' ? '已完成' : step.status === 'skipped' ? '已跳过' : '待开始'}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 当前步骤详情 */}
      {chain.currentStep && !compact && (
        <div className="mt-3 p-2 bg-slate-900 rounded-md text-[11px] text-slate-500">
          <span className="text-violet-400 font-semibold">
            当前: {chain.currentStep}
          </span>
          {chain.scope && (
            <span className="ml-2">
              范围: {chain.scope.slice(0, 30)}{chain.scope.length > 30 ? '...' : ''}
            </span>
          )}
        </div>
      )}

      {/* 进度条 */}
      <div className="mt-3 h-1 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-violet-600 transition-all"
          style={{ width: `${Math.round((totalDone / total) * 100)}%` }}
        />
      </div>
      <div className="mt-1.5 text-[10px] text-slate-500 text-center">
        进度 {totalDone}/{total} · {Math.round((totalDone / total) * 100)}%
      </div>
    </div>
  );
}
