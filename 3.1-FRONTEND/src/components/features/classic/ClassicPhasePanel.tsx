'use client';

import { useClassicStore } from '@/stores';
import { useClassicSystem } from './use-classic-system';
import { V3Card, V3Button, V3StatusDot, V3Spinner } from '@/components';

export function ClassicPhasePanel() {
  const {
    activePhase,
    phases,
    runPhase,
    pipelineLoading,
    pipelineOnline,
    pipelineError,
    pipelinePhase,
    pipelineCurrent,
  } = useClassicStore();
  useClassicSystem();

  const current = phases.find(p => p.phase === activePhase);
  if (!current) return null;

  // 离线降级 UI
  if (pipelineLoading) {
    return (
      <V3Card title={`阶段 ${current.phase}: ${current.name}`} padding="lg">
        <div className="flex items-center gap-2 p-3 rounded-lg bg-blue-900/10 border border-blue-500/20">
          <V3Spinner size="sm" />
          <span className="text-xs text-blue-400">正在连接经典系统...</span>
        </div>
      </V3Card>
    );
  }

  if (!pipelineOnline) {
    return (
      <V3Card title={`阶段 ${current.phase}: ${current.name}`} badge="offline" padding="lg">
        <div className="space-y-3">
          <div className="flex items-center gap-2 p-3 rounded-lg bg-amber-900/10 border border-amber-500/20">
            <V3StatusDot status="warning" size="sm" />
            <span className="text-xs text-amber-400">
              经典系统离线 — 展示本地阶段信息（{pipelineError || '不可达'}）
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-300">
              {current.status === 'running' ? '执行中...' : current.status === 'done' ? '已完成' : '待执行'}
            </span>
            {current.status !== 'running' && (
              <V3Button size="sm" onClick={() => runPhase(current.phase)}>执行</V3Button>
            )}
          </div>
        </div>
      </V3Card>
    );
  }

  // 在线 — 展示真实流水线阶段
  const livePhase = pipelinePhase || current.phase;

  return (
    <V3Card title={`阶段 ${current.phase}: ${current.name}`} badge={current.status} padding="lg">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <V3StatusDot status={current.status === 'running' ? 'active' : current.status === 'done' ? 'success' : current.status === 'failed' ? 'error' : 'idle'} />
            <span className="text-sm text-slate-300 capitalize">{current.status === 'running' ? '执行中...' : current.status === 'done' ? '已完成' : current.status === 'failed' ? '失败' : '待执行'}</span>
          </div>
          {current.status !== 'running' && (
            <V3Button size="sm" onClick={() => runPhase(current.phase)}>执行</V3Button>
          )}
        </div>
        {current.status === 'running' && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-blue-900/10 border border-blue-500/20">
            <V3Spinner size="sm" />
            <span className="text-xs text-blue-400">正在处理...</span>
          </div>
        )}
        {pipelineCurrent && (
          <div className="p-2 rounded bg-slate-900/30 border border-slate-700/20">
            <p className="text-[10px] text-slate-500">经典系统当前阶段</p>
            <p className="text-xs text-emerald-400">{pipelineCurrent}</p>
          </div>
        )}
        {current.output && (
          <div className="p-3 rounded-lg bg-slate-900/50 border border-slate-700/30">
            <p className="text-[10px] text-slate-500 mb-1">输出摘要</p>
            <p className="text-xs text-slate-400 whitespace-pre-wrap">{current.output}</p>
          </div>
        )}
        {current.status === 'done' && (
          <div className="flex items-center gap-2">
            <V3Button size="sm" variant="secondary" onClick={() => {
              const idx = phases.findIndex(p => p.phase === current.phase);
              if (idx < phases.length - 1) runPhase(phases[idx + 1].phase);
            }}>
              下一阶段 →
            </V3Button>
          </div>
        )}
        <div className="border-t border-slate-700/30 pt-3">
          <p className="text-[10px] text-slate-500 mb-2">阶段进度</p>
          <div className="flex gap-1">
            {phases.map(p => (
              <div key={p.phase} className={`flex-1 h-1.5 rounded-full ${p.status === 'done' ? 'bg-emerald-500' : p.status === 'running' ? 'bg-blue-500 animate-pulse' : p.status === 'failed' ? 'bg-red-500' : 'bg-slate-700'}`} />
            ))}
          </div>
        </div>
      </div>
    </V3Card>
  );
}
