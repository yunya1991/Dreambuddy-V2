'use client';

import React from 'react';
import { useThreeScreensStore } from '@/stores';
import { V3Card } from '@/components/V3Card';
import { V3Badge } from '@/components/V3Badge';

/**
 * 全链路方向约束传递可视化
 * Screen1 -> Screen2 -> Screen3 数据流
 */
export function PipelineView() {
  const { screen1, screen2, screen3, directionConstraint, presetConstraint, symbol } = useThreeScreensStore();

  const hasS1 = screen1 && screen1.status === 'done';
  const hasS2 = screen2 && screen2.status === 'done';
  const hasS3 = screen3 && (screen3.status === 'executing' || screen3.status === 'done');

  return (
    <div className="space-y-4">
      {/* 交易对标识 */}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-semibold text-gray-100">{symbol}</span>
        <V3Badge variant="default">三屏交易系统</V3Badge>
      </div>

      {/* 全链路流程图 */}
      <div className="flex items-start gap-0">
        {/* Screen1 战略层 */}
        <PipelineBlock
          title="Screen 1"
          subtitle="战略层"
          status={screen1?.status || 'idle'}
          output={hasS1 ? `方向: ${screen1!.directionAnchor.direction} (${screen1!.directionAnchor.overallScore}分)` : null}
          color="purple"
          isActive={screen1?.status === 'analyzing'}
        />

        {/* 连接箭头 + 方向约束 */}
        <ConstraintArrow
          label="方向约束"
          status={directionConstraint ? 'passed' : 'pending'}
          value={directionConstraint?.direction}
        />

        {/* Screen2 战术层 */}
        <PipelineBlock
          title="Screen 2"
          subtitle="战术层"
          status={screen2?.status || 'idle'}
          output={hasS2 ? `入场: ${screen2!.presets.entry.price} | 止盈: ${screen2!.presets.takeProfit.price}` : null}
          color="blue"
          isActive={screen2?.status === 'computing'}
        />

        {/* 连接箭头 + 预设约束 */}
        <ConstraintArrow
          label="预设约束"
          status={presetConstraint ? 'passed' : 'pending'}
          value={presetConstraint ? '已传递' : null}
        />

        {/* Screen3 执行层 */}
        <PipelineBlock
          title="Screen 3"
          subtitle="执行层"
          status={screen3?.status || 'idle'}
          output={hasS3 && screen3!.position.isOpen ? `持仓中 | PnL: ${screen3!.position.unrealizedPnl.toFixed(2)}` : null}
          color="emerald"
          isActive={screen3?.status === 'executing'}
        />
      </div>

      {/* 链路健康度 */}
      <V3Card title="链路健康度" padding="sm">
        <div className="grid grid-cols-3 gap-3">
          <div className="text-center p-3 rounded-lg bg-gray-800/20">
            <V3Badge variant={hasS1 ? 'success' : 'default'}>{hasS1 ? '正常' : '未启动'}</V3Badge>
            <div className="text-[10px] text-gray-400 mt-1">战略层</div>
          </div>
          <div className="text-center p-3 rounded-lg bg-gray-800/20">
            <V3Badge variant={hasS2 ? 'success' : directionConstraint ? 'warning' : 'default'}>
              {hasS2 ? '正常' : directionConstraint ? '等待' : '未启动'}
            </V3Badge>
            <div className="text-[10px] text-gray-400 mt-1">战术层</div>
          </div>
          <div className="text-center p-3 rounded-lg bg-gray-800/20">
            <V3Badge variant={hasS3 ? 'success' : presetConstraint ? 'warning' : 'default'}>
              {hasS3 ? '执行中' : presetConstraint ? '等待' : '未启动'}
            </V3Badge>
            <div className="text-[10px] text-gray-400 mt-1">执行层</div>
          </div>
        </div>
      </V3Card>
    </div>
  );
}

/** 管道块组件 */
function PipelineBlock({ title, subtitle, status, output, color, isActive }: {
  title: string;
  subtitle: string;
  status: string;
  output: string | null;
  color: string;
  isActive: boolean;
}) {
  const colorClasses: Record<string, string> = {
    purple: 'border-purple-500/30',
    blue: 'border-blue-500/30',
    emerald: 'border-emerald-500/30',
  };
  return (
    <div className={`
      flex-1 p-3 rounded-xl border transition-all
      ${colorClasses[color] || 'border-gray-700/30'}
      ${isActive ? 'bg-gray-800/50 shadow-lg' : 'bg-gray-900/50'}
    `}>
      <div className="flex items-center gap-1.5 mb-1">
        <span className="text-xs font-semibold text-gray-200">{title}</span>
        <span className="text-[10px] text-gray-500">{subtitle}</span>
      </div>
      <V3Badge variant={
        status === 'done' ? 'success'
        : status === 'analyzing' || status === 'computing' || status === 'executing' ? 'info'
        : status === 'error' ? 'danger'
        : 'default'
      }>
        {status}
      </V3Badge>
      {output && (
        <p className="text-[10px] text-gray-400 mt-2 leading-tight">{output}</p>
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
      <div className={`w-full h-px ${status === 'passed' ? 'bg-blue-500/50' : 'bg-gray-700/30'}`} />
      <span className="text-[9px] text-gray-500">{label}</span>
      {value && (
        <V3Badge variant={status === 'passed' ? 'success' : 'default'} className="text-[9px]">{value}</V3Badge>
      )}
      {/* 向下箭头 */}
      <svg className="w-3 h-3 text-gray-600" viewBox="0 0 12 12" fill="currentColor">
        <path d="M2 4l4 4 4-4" />
      </svg>
    </div>
  );
}

export default PipelineView;
