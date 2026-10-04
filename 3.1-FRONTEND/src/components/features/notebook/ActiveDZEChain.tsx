'use client';

// ============================================================
// ActiveDZEChain — D-Z-E 三链可视化 (3.1 Tailwind 版)
// 显示 d1→d2→d3→d4 → z1→z2→z3→z4 → e1→e2→e3
// ============================================================

import type { DZEChainState } from '@/lib/notebook/types';

interface Props {
  chain: DZEChainState | null;
  compact?: boolean;
}

const CHAIN_COLORS: Record<string, { text: string; bg: string; border: string; dot: string }> = {
  d: { text: 'text-cyan-400', bg: 'bg-cyan-950/30', border: 'border-cyan-800', dot: 'bg-cyan-500' },
  z: { text: 'text-amber-400', bg: 'bg-amber-950/30', border: 'border-amber-800', dot: 'bg-amber-500' },
  e: { text: 'text-emerald-400', bg: 'bg-emerald-950/30', border: 'border-emerald-800', dot: 'bg-emerald-500' },
};

const CHAIN_NAMES: Record<string, string> = {
  d: '调研链',
  z: '规划链',
  e: '执行链',
};

export default function ActiveDZEChain({ chain, compact }: Props) {
  if (!chain) {
    return (
      <div className="p-3 bg-slate-950 border border-dashed border-slate-700 rounded-lg text-xs text-slate-500 text-center">
        D-Z-E 链未初始化 · 完成 Step1 后自动生成
      </div>
    );
  }

  const grouped = [
    { group: 'd', items: chain.phases.filter((p) => p.id.startsWith('d')) },
    { group: 'z', items: chain.phases.filter((p) => p.id.startsWith('z')) },
    { group: 'e', items: chain.phases.filter((p) => p.id.startsWith('e')) },
  ];

  const totalDone = chain.phases.filter(
    (p) => p.status === 'done' || p.status === 'skipped'
  ).length;

  return (
    <div className={`p-3 bg-slate-950 border border-slate-800 rounded-lg`}>
      {/* 标题 */}
      <div className="flex justify-between items-center mb-2.5 text-xs text-slate-500">
        <span className="font-semibold text-slate-300">🔗 D-Z-E 思维链</span>
        <span>
          {totalDone}/{chain.phases.length} 阶段 · 范围: {chain.scope.slice(0, 20)}
        </span>
      </div>

      {/* 三组链 */}
      <div className="flex flex-col gap-1.5">
        {grouped.map((g) => {
          const groupDone = g.items.filter(
            (p) => p.status === 'done' || p.status === 'skipped'
          ).length;
          const color = CHAIN_COLORS[g.group];
          return (
            <div key={g.group} className={`p-2 ${color.bg} border border-slate-800 rounded-md`}>
              {/* 组标题 */}
              <div className="flex items-center text-[11px] mb-2 gap-1">
                <span className={`w-2 h-2 ${color.dot} rounded-sm`} />
                <span className="text-slate-400 mr-2">{CHAIN_NAMES[g.group]}</span>
                <span className={`ml-auto text-[10px] ${groupDone === g.items.length ? color.text : 'text-slate-600'}`}>
                  ({groupDone}/{g.items.length})
                </span>
              </div>
              {/* 阶段卡片 */}
              <div className="flex justify-between gap-1">
                {g.items.map((phase) => {
                  const isCurrent = chain.currentPhase === phase.id;
                  const isDone = phase.status === 'done' || phase.status === 'skipped';
                  return (
                    <div
                      key={phase.id}
                      className={`flex-1 text-center px-1 py-1.5 rounded text-[11px] min-w-[60px] border ${
                        isCurrent
                          ? `${color.bg} ${color.border} ${color.text} font-bold`
                          : isDone
                          ? `${color.text} border-slate-800 bg-slate-950`
                          : 'text-slate-500 border-slate-800 bg-slate-950'
                      }`}
                    >
                      <div className="text-xs font-bold uppercase">{phase.id}</div>
                      <div className="text-[9px] opacity-80 mt-0.5">
                        {phase.name.split(' ')[1] || phase.name}
                      </div>
                      {!compact && phase.output && (
                        <div className="text-[9px] text-slate-600 mt-1 leading-relaxed">
                          {phase.output.slice(0, 100)}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
