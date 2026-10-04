'use client';

import { V3Card, V3Badge, V3Empty } from '@/components';
import { useChainStore, type ReflectorAction } from '@/stores';

/**
 * C 层反思决策面板
 * 对应 SPEC §C: /dashboard/monitor/compute
 * 数据源: useChainStore.reflectorHistory + steps.reflectorDecision
 */

const actionStyles: Record<ReflectorAction, { bg: string; text: string; label: string }> = {
  CONTINUE: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', label: '继续' },
  REDO: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: '重做' },
  INSERT_BEFORE: { bg: 'bg-blue-500/15', text: 'text-blue-400', label: '前插' },
  JUMP_TO: { bg: 'bg-purple-500/15', text: 'text-purple-400', label: '跳转' },
  EARLY_TERMINATE: { bg: 'bg-rose-500/15', text: 'text-rose-400', label: '终止' },
  SKIP: { bg: 'bg-slate-700/30', text: 'text-slate-500', label: '跳过' },
};

export function ReflectorPanel() {
  const { reflectorHistory, steps } = useChainStore();

  const actionCounts = reflectorHistory.reduce((acc, r) => {
    acc[r.action] = (acc[r.action] || 0) + 1;
    return acc;
  }, {} as Record<ReflectorAction, number>);

  const totalDecisions = reflectorHistory.length;
  const continueCount = actionCounts.CONTINUE || 0;
  const redoCount = actionCounts.REDO || 0;
  const redoRate = totalDecisions > 0 ? (redoCount / totalDecisions) * 100 : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300">C 层 — 反思决策</h2>
        <V3Badge variant="sacg-c" dot pulse>C</V3Badge>
      </div>

      {/* 决策统计 */}
      <div className="grid grid-cols-3 gap-3">
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">总决策</p>
          <p className="text-lg font-bold text-slate-200">{totalDecisions}</p>
        </V3Card>
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">继续</p>
          <p className="text-lg font-bold text-emerald-400">{continueCount}</p>
        </V3Card>
        <V3Card padding="sm">
          <p className="text-[10px] text-slate-500">重做率</p>
          <p className="text-lg font-bold text-amber-400">{redoRate.toFixed(0)}%</p>
        </V3Card>
      </div>

      {/* 决策分布 */}
      {totalDecisions > 0 && (
        <V3Card title="决策分布" padding="sm">
          <div className="space-y-2">
            {(Object.keys(actionStyles) as ReflectorAction[]).map(action => {
              const count = actionCounts[action] || 0;
              if (count === 0) return null;
              const pct = (count / totalDecisions) * 100;
              const style = actionStyles[action];
              return (
                <div key={action} className="flex items-center gap-2">
                  <span className={`text-[10px] px-2 py-0.5 rounded ${style.bg} ${style.text} w-12 text-center`}>
                    {style.label}
                  </span>
                  <div className="flex-1 h-1.5 rounded-full bg-slate-700 overflow-hidden">
                    <div className={`h-full ${style.bg.replace('/15', '/80')}`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-[10px] text-slate-400 w-8 text-right">{count}</span>
                </div>
              );
            })}
          </div>
        </V3Card>
      )}

      {/* 决策历史 */}
      <V3Card title="决策历史" padding="sm">
        {reflectorHistory.length > 0 ? (
          <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
            {reflectorHistory.slice().reverse().map((r, i) => {
              const style = actionStyles[r.action];
              const step = steps.find(s => s.id === r.stepId);
              return (
                <div key={i} className="flex items-start gap-2 p-2 rounded bg-slate-800/30">
                  <span className={`text-[10px] px-2 py-0.5 rounded ${style.bg} ${style.text} shrink-0`}>
                    {style.label}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-slate-300 truncate">
                      {step?.name || r.stepId}
                    </p>
                    {r.reason && (
                      <p className="text-[10px] text-slate-500 truncate">{r.reason}</p>
                    )}
                  </div>
                  <span className="text-[10px] text-slate-600 shrink-0">
                    {new Date(r.timestamp).toLocaleTimeString('zh-CN')}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <V3Empty title="暂无反思决策" description="等待 Reflector 运行" />
        )}
      </V3Card>
    </div>
  );
}
