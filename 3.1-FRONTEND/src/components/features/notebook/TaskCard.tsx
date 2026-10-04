'use client';

// ============================================================
// TaskCard — 任务摘要卡片 (3.1 Tailwind 版)
// 显示单个任务的标题/阶段/进度/时间
// ============================================================

import type { NotebookTask } from '@/lib/notebook/types';

interface Props {
  task: NotebookTask;
  isCurrent?: boolean;
  onClick?: () => void;
}

const phaseStyles: Record<string, { bg: string; border: string; label: string; bar: string }> = {
  todo: { bg: 'bg-amber-950/30', border: 'border-amber-800', label: '待办', bar: 'bg-amber-600' },
  active: { bg: 'bg-indigo-950/30', border: 'border-indigo-700', label: '活跃', bar: 'bg-indigo-600' },
  done: { bg: 'bg-emerald-950/30', border: 'border-emerald-700', label: '已完成', bar: 'bg-emerald-600' },
  archive: { bg: 'bg-slate-950/30', border: 'border-slate-700', label: '归档', bar: 'bg-slate-600' },
};

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default function TaskCard({ task, isCurrent, onClick }: Props) {
  const style = phaseStyles[task.phase] || phaseStyles.active;
  const doneCount = task.steps.filter((s) => s.status === 'done' || s.status === 'skipped').length;
  const percent = Math.round((doneCount / task.steps.length) * 100);

  return (
    <div
      onClick={onClick}
      className={`p-3.5 rounded-lg border mb-2 transition-all ${
        isCurrent
          ? `${style.bg} ${style.border}`
          : 'bg-slate-950 border-slate-800 hover:border-slate-700'
      } ${onClick ? 'cursor-pointer' : ''}`}
    >
      {/* 标题 + 阶段标签 */}
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-semibold text-slate-200">{task.title}</div>
        <span className={`text-[10px] px-2 py-0.5 rounded ${style.bg} ${style.border} border text-white font-semibold`}>
          {style.label}
        </span>
      </div>

      {/* intent + entities */}
      <div className="text-[11px] text-slate-500 mb-2 leading-relaxed">
        <span className="text-slate-600">intent: </span>
        <span className="text-cyan-400">{task.intent}</span>
        {Object.keys(task.entities || {}).length > 0 && (
          <>
            <span className="text-slate-600"> · </span>
            {Object.entries(task.entities).map(([k, v], i) => (
              <span key={k} className="text-cyan-300">
                {i > 0 && ', '}
                {v || k}
              </span>
            ))}
          </>
        )}
      </div>

      {/* 进度条 */}
      <div className="h-1 bg-slate-800 rounded-full overflow-hidden mb-1.5">
        <div
          className={`h-full ${style.bar} transition-all`}
          style={{ width: `${percent}%` }}
        />
      </div>

      {/* 底部摘要 */}
      <div className="flex justify-between text-[10px] text-slate-600">
        <span>{doneCount}/{task.steps.length} 步</span>
        <span>{formatDate(task.lastActiveAt)}</span>
      </div>
    </div>
  );
}
