'use client';

import { useThreeScreensStore } from '@/stores';
import { V3Card, V3StatusDot, V3Badge } from '@/components';

export function PipelineView() {
  const { screen1, screen2, screen3, propagationStatus } = useThreeScreensStore();

  const stages = [
    { id: 's1', label: 'Screen1 战略层', sub: '周线方向', done: !!screen1?.directionAnchor, color: screen1?.directionAnchor === 'bullish' ? 'border-emerald-500/30 bg-emerald-900/10' : screen1?.directionAnchor === 'bearish' ? 'border-red-500/30 bg-red-900/10' : 'border-slate-700/30 bg-slate-800/30' },
    { id: 's2', label: 'Screen2 战术层', sub: '日线预设', done: !!screen2?.presets?.length, color: 'border-blue-500/30 bg-blue-900/10' },
    { id: 's3', label: 'Screen3 执行层', sub: 'A7→A9', done: screen3?.pipeline.some(p => p.status === 'done'), color: 'border-green-500/30 bg-green-900/10' },
  ];

  const statusLabel: Record<string, string> = { idle: '空闲', s1_complete: 'S1完成', s2_complete: 'S2完成', s3_running: 'S3执行', complete: '完成' };

  return (
    <V3Card title="全链路约束流" badge={statusLabel[propagationStatus]}>
      <div className="space-y-4">
        <div className="flex items-center gap-2 justify-center">
          {stages.map((stage, i) => (
            <div key={stage.id} className="flex items-center gap-2">
              <div className={`flex flex-col items-center p-3 rounded-lg border min-w-[140px] ${stage.done ? stage.color : 'border-slate-700/30 bg-slate-800/30'}`}>
                <V3StatusDot status={stage.done ? 'success' : 'idle'} size="sm" label={stage.label} />
                <span className="text-[10px] text-slate-500 mt-1">{stage.sub}</span>
              </div>
              {i < stages.length - 1 && (
                <svg className="w-6 h-6 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
              )}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="p-2 rounded bg-slate-900/30">
            <p className="text-[10px] text-slate-500">方向约束</p>
            <p className={`text-sm font-semibold ${screen1?.directionAnchor === 'bullish' ? 'text-emerald-400' : screen1?.directionAnchor === 'bearish' ? 'text-red-400' : 'text-slate-500'}`}>
              {screen1?.directionAnchor || '--'}
            </p>
          </div>
          <div className="p-2 rounded bg-slate-900/30">
            <p className="text-[10px] text-slate-500">预设数量</p>
            <p className="text-sm font-semibold text-slate-300">{screen2?.presets?.length || 0}</p>
          </div>
          <div className="p-2 rounded bg-slate-900/30">
            <p className="text-[10px] text-slate-500">流水线进度</p>
            <p className="text-sm font-semibold text-slate-300">
              {screen3 ? `${screen3.pipeline.filter(p => p.status === 'done').length}/${screen3.pipeline.length}` : '--'}
            </p>
          </div>
        </div>
      </div>
    </V3Card>
  );
}
