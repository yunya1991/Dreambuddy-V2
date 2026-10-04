'use client';

// ============================================================
// StepActionMenu — 步骤决策菜单 (3.1 Tailwind 版)
// 提供 continue/skip/jump/finalize/pause 操作按钮
// ============================================================

import type { StepAction } from '@/lib/notebook/types';

interface Props {
  taskId: string;
  onAction: (action: StepAction, targetStep?: number, reason?: string) => void;
  totalSteps?: number;
  disabled?: boolean;
}

const actions: Array<{
  id: StepAction;
  label: string;
  description: string;
  color: string;
}> = [
  { id: 'continue', label: '继续下一步', description: '完成当前, 激活下一步', color: 'text-emerald-400 border-emerald-700/50' },
  { id: 'skip', label: '跳过当前步', description: '标记为 skipped, 进入下一步', color: 'text-slate-400 border-slate-600/50' },
  { id: 'finalize', label: '全部完成', description: '跳过剩余所有步骤, 任务结束', color: 'text-amber-400 border-amber-700/50' },
  { id: 'pause', label: '暂停任务', description: '当前步骤恢复 pending, 稍后继续', color: 'text-red-400 border-red-700/50' },
];

export default function StepActionMenu({ taskId, onAction, totalSteps = 7, disabled }: Props) {
  return (
    <div className="p-4 bg-slate-900/50 border border-slate-800 rounded-lg">
      <div className="text-sm text-slate-500 mb-3 font-semibold">
        🔰 每步完成后的决策菜单
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-2">
        {actions.map((action) => (
          <button
            key={action.id}
            onClick={() => onAction(action.id)}
            disabled={disabled}
            className={`p-3 text-left rounded-md border ${disabled ? 'bg-slate-900 border-slate-800 text-slate-700 cursor-not-allowed' : `bg-slate-950 ${action.color} hover:bg-slate-900 cursor-pointer`} text-xs font-medium transition-all`}
          >
            <div className="font-bold mb-1">{action.label}</div>
            <div className="text-[10px] opacity-70 leading-relaxed">{action.description}</div>
          </button>
        ))}
      </div>

      {/* 跳步 */}
      <div className="mt-2.5 text-[11px] text-slate-600 flex gap-2 items-center justify-between flex-wrap">
        <div className="flex items-center gap-1">
          <span className="text-slate-500">跳到 Step：</span>
          {Array.from({ length: totalSteps - 2 }, (_, i) => i + 2).map((n) => (
            <button
              key={n}
              onClick={() => onAction('jump', n)}
              disabled={disabled}
              className={`mx-0.5 px-2 py-0.5 rounded text-[11px] border ${
                disabled
                  ? 'bg-slate-900 border-slate-800 text-slate-700 cursor-not-allowed'
                  : 'bg-slate-800 border-slate-700 text-slate-400 hover:bg-slate-700 cursor-pointer'
              }`}
            >
              Step {n}
            </button>
          ))}
        </div>
        <span className="opacity-60">task: {taskId.slice(-8)}</span>
      </div>
    </div>
  );
}
