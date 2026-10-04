'use client';

import { useClassicStore } from '@/stores';
import { V3StatusDot } from '@/components';

const statusColors: Record<string, string> = {
  idle: 'text-slate-500', running: 'text-blue-400', done: 'text-emerald-400', failed: 'text-red-400', skipped: 'text-slate-600',
};

const dotStatus: Record<string, 'idle' | 'active' | 'success' | 'warning' | 'error'> = {
  idle: 'idle', running: 'active', done: 'success', failed: 'error', skipped: 'warning',
};

export function ClassicPhaseIndicator() {
  const { activePhase, phases, setActivePhase, pipelinePhase, pipelineOnline } = useClassicStore();

  // 如果经典系统在线且有真实阶段，高亮对应阶段
  const liveActivePhase = (pipelineOnline && pipelinePhase) ? pipelinePhase as any : activePhase;

  return (
    <div className="flex items-center gap-1 p-3 rounded-xl bg-slate-800/50 border border-slate-700/50">
      {phases.map((phase, i) => {
        const isActive = phase.phase === liveActivePhase;
        // 如果在线且阶段已过，标记为 done
        const isDone = pipelineOnline && pipelinePhase &&
          phases.findIndex(p => p.phase === pipelinePhase) > i;
        const effectiveStatus = isDone ? 'done' : phase.status;
        return (
          <div key={phase.phase} className="flex items-center gap-1">
            <button
              onClick={() => setActivePhase(phase.phase)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${isActive ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30' : 'text-slate-400 hover:bg-slate-800'}`}
            >
              <V3StatusDot status={dotStatus[effectiveStatus]} size="sm" />
              <span className={statusColors[effectiveStatus]}>{phase.phase}</span>
              <span className="text-[10px] opacity-60">{phase.name}</span>
            </button>
            {i < phases.length - 1 && <span className="text-slate-700 mx-0.5">→</span>}
          </div>
        );
      })}
    </div>
  );
}
