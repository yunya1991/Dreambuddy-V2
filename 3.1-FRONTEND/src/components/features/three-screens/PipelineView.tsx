'use client';

import React from 'react';
import { useThreeScreensStore } from '@/stores';
import { V3Card, V3Badge, V3StatusDot } from '@/components';

/**
 * 全链路方向约束传递可视化
 * Screen1 -> Screen2 -> Screen3 数据流
 */
export function PipelineView() {
  const { screen1, screen2, screen3, propagationStatus } = useThreeScreensStore();

  const hasS1 = !!screen1;
  const hasS2 = !!screen2;
  const hasS3 = !!screen3;

  return (
    <div className="space-y-4">
      {/* 交易对标识 */}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-slate-200">BTC/USDT</span>
        <V3Badge variant="default">三屏交易系统</V3Badge>
      </div>

      {/* 全链路流程图 */}
      <div className="flex items-start gap-0">
        <PipelineBlock
          title="Screen 1"
          subtitle="战略层"
          isActive={propagationStatus === 'idle'}
          isDone={hasS1}
          output={hasS1 && screen1!.directionAnchor ? `方向: ${screen1!.directionAnchor}` : null}
          color="purple"
        />

        <ConstraintArrow
          label="方向约束"
          status={hasS1 ? 'passed' : 'pending'}
          value={screen1?.directionAnchor || null}
        />

        <PipelineBlock
          title="Screen 2"
          subtitle="战术层"
          isActive={propagationStatus === 's1_complete'}
          isDone={hasS2}
          output={hasS2 && screen2!.presets.length > 0 ? `预设: ${screen2!.presets.length} 个` : null}
          color="blue"
        />

        <ConstraintArrow
          label="预设约束"
          status={hasS2 ? 'passed' : 'pending'}
          value={hasS2 ? '已传递' : null}
        />

        <PipelineBlock
          title="Screen 3"
          subtitle="执行层"
          isActive={propagationStatus === 's2_complete'}
          isDone={hasS3}
          output={hasS3 && screen3!.positionState ? `持仓中 | PnL: ${screen3!.positionState.pnl.toFixed(2)}` : null}
          color="emerald"
        />
      </div>

      {/* 链路健康度 */}
      <V3Card title="链路健康度" padding="sm">
        <div className="grid grid-cols-3 gap-3">
          <div className="text-center p-3 rounded-lg bg-slate-800/20">
            <V3Badge variant={hasS1 ? 'success' : 'default'}>{hasS1 ? '正常' : '未启动'}</V3Badge>
            <div className="text-[10px] text-slate-400 mt-1">战略层</div>
          </div>
          <div className="text-center p-3 rounded-lg bg-slate-800/20">
            <V3Badge variant={hasS2 ? 'success' : hasS1 ? 'warning' : 'default'}>
              {hasS2 ? '正常' : hasS1 ? '等待' : '未启动'}
            </V3Badge>
            <div className="text-[10px] text-slate-400 mt-1">战术层</div>
          </div>
          <div className="text-center p-3 rounded-lg bg-slate-800/20">
            <V3Badge variant={hasS3 ? 'success' : hasS2 ? 'warning' : 'default'}>
              {hasS3 ? '执行中' : hasS2 ? '等待' : '未启动'}
            </V3Badge>
            <div className="text-[10px] text-slate-400 mt-1">执行层</div>
          </div>
        </div>
      </V3Card>
    </div>
  );
}

/** 管道块组件 */
function PipelineBlock({ title, subtitle, isActive, isDone, output, color }: {
  title: string;
  subtitle: string;
  isActive: boolean;
  isDone: boolean;
  output: string | null;
  color: string;
}) {
  const colorClasses: Record<string, string> = {
    purple: 'border-purple-500/30',
    blue: 'border-blue-500/30',
    emerald: 'border-emerald-500/30',
  };
  return (
    <div className={`
      flex-1 p-3 rounded-xl border transition-all
      ${colorClasses[color] || 'border-slate-700/30'}
      ${isActive ? 'bg-slate-800/50 shadow-lg' : 'bg-slate-900/50'}
    `}>
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-xs font-semibold text-slate-200">{title}</span>
        <span className="text-[10px] text-slate-500">{subtitle}</span>
      </div>
      <V3Badge variant={isDone ? 'success' : isActive ? 'info' : 'default'}>
        {isDone ? '完成' : isActive ? '进行中' : '待启动'}
      </V3Badge>
      {output && (
        <p className="text-[10px] text-slate-400 mt-2 leading-tight">{output}</p>
      )}
    </div>
  );
}

/** 约束传递箭头 */
function ConstraintArrow({ label, status, value }: {
  label: string;
  status: 'passed' | 'pending';
  value: string | null;
}) {
  return (
    <div className="flex flex-col items-center gap-1 w-20 shrink-0">
      <div className={`w-full h-px ${status === 'passed' ? 'bg-blue-500/50' : 'bg-slate-700/30'}`} />
      <span className="text-[9px] text-slate-500">{label}</span>
      {value && (
        <V3Badge variant={status === 'passed' ? 'success' : 'default'} className="text-[9px]">{value}</V3Badge>
      )}
      <svg className="w-3 h-3 text-slate-600" viewBox="0 0 12 12" fill="currentColor">
        <path d="M2 4l4 4 4-4" />
      </svg>
    </div>
  );
}

export default PipelineView;
