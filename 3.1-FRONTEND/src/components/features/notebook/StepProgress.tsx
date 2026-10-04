'use client';

// ============================================================
// StepProgress — 7步进度指示器 (3.1 Tailwind 版)
// 显示 7 个圆形步骤 + 连接线 + 状态图标
// ============================================================

import type { NotebookStep } from '@/lib/notebook/types';

interface Props {
  steps: NotebookStep[];
  onStepClick?: (stepNumber: number) => void;
  compact?: boolean;
}

const statusStyles: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  pending: { bg: 'bg-slate-800', border: 'border-slate-700', text: 'text-slate-500', icon: '⬜' },
  active: { bg: 'bg-indigo-600', border: 'border-indigo-500', text: 'text-white', icon: '▶' },
  done: { bg: 'bg-emerald-700', border: 'border-emerald-600', text: 'text-white', icon: '✓' },
  skipped: { bg: 'bg-slate-600', border: 'border-slate-500', text: 'text-slate-300', icon: '⏭' },
};

export default function StepProgress({ steps, onStepClick, compact }: Props) {
  const progress = steps.filter((s) => s.status !== 'pending').length;
  const total = steps.length;

  return (
    <div className={`w-full ${compact ? 'py-2' : 'py-4 px-2'}`}>
      {/* 步骤圆形指示器 */}
      <div className="flex items-center justify-between relative">
        {steps.map((step, idx) => {
          const style = statusStyles[step.status];
          const isLast = idx === steps.length - 1;
          const cursor = onStepClick ? 'cursor-pointer' : 'cursor-default';
          return (
            <div key={step.id} className={`flex items-center ${isLast ? '' : 'flex-1'}`}>
              <div
                onClick={() => onStepClick?.(step.number)}
                title={step.name}
                className={`${cursor} ${compact ? 'w-8 h-8' : 'w-11 h-11'} rounded-full ${style.bg} border-2 ${style.border} ${style.text} flex flex-col items-center justify-center font-semibold ${compact ? 'text-xs' : 'text-sm'} relative z-10 shrink-0 transition-all hover:opacity-80`}
              >
                <span className={`leading-none ${compact ? 'text-xs' : 'text-sm'}`}>
                  {compact ? step.icon : style.icon}
                </span>
                {!compact && (
                  <span className="text-[10px] mt-0.5 opacity-85">S{step.number}</span>
                )}
              </div>
              {!isLast && (
                <div
                  className={`flex-1 h-0.5 -mx-0.5 z-0 min-w-[10px] ${
                    steps[idx + 1]?.status !== 'pending' ? 'bg-emerald-600' : 'bg-slate-700'
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* 步骤名称 */}
      {!compact && (
        <div className="mt-4 flex flex-wrap gap-2 justify-between">
          {steps.map((step) => {
            const style = statusStyles[step.status];
            return (
              <div
                key={step.id}
                onClick={() => onStepClick?.(step.number)}
                className={`flex-1 min-w-[60px] max-w-[100px] text-[11px] text-center ${
                  step.status === 'active'
                    ? 'text-indigo-400 font-bold'
                    : step.status === 'done'
                    ? 'text-emerald-400'
                    : style.text
                } ${onStepClick ? 'cursor-pointer' : ''}`}
              >
                <div className={step.status === 'active' ? 'font-bold' : 'font-medium'}>
                  {step.name}
                </div>
                {step.status !== 'pending' && step.status !== 'active' && (
                  <div className="text-[10px] opacity-60 mt-0.5">
                    {step.status === 'done' ? '完成' : '跳过'}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 进度摘要 */}
      <div className="mt-3 text-[11px] text-slate-500 text-center">
        进度 {progress}/{total} · 已完成 {Math.round((progress / total) * 100)}%
      </div>
    </div>
  );
}
