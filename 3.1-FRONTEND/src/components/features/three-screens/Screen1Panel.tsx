'use client';

import React from 'react';
import { useThreeScreensStore, type Screen1Data } from '@/stores';
import { V3Card } from '@/components/V3Card';
import { V3Badge } from '@/components/V3Badge';
import { V3StatusDot } from '@/components/V3StatusDot';
import { V3Empty } from '@/components/V3Empty';
import { V3Button } from '@/components/V3Button';
import { IconRefresh } from '@/components/V3InlineSVG';

// 七维颜色
const dimColors = ['blue', 'purple', 'amber', 'emerald', 'cyan', 'rose', 'orange'];

export function Screen1Panel() {
  const { screen1, propagateDirection } = useThreeScreensStore();

  if (!screen1 || screen1.status === 'idle') {
    return (
      <V3Card title="Screen 1 — 战略层" subtitle="周线方向判定" padding="lg">
        <V3Empty
          title="等待分析"
          description="执行战略层分析以获取七维牛熊评分和方向锚"
          action={
            <V3Button variant="primary" size="sm">
              启动 Screen1 分析
            </V3Button>
          }
        />
      </V3Card>
    );
  }

  const { dimensions, directionAnchor, debate, status } = screen1;
  const dims = Object.entries(dimensions) as [string, { score: number; signal: string }][];

  return (
    <div className="space-y-4">
      {/* 方向锚 */}
      <DirectionAnchorCard directionAnchor={directionAnchor} status={status} />

      {/* 七维评分 */}
      <V3Card title="七维牛熊评分" padding="sm">
        <div className="grid grid-cols-7 gap-2">
          {dims.map(([key, dim], i) => (
            <div key={key} className="flex flex-col items-center gap-1.5 p-2 rounded-lg bg-gray-800/30">
              <ScoreRing score={dim.score} size={48} colorIndex={i} />
              <span className="text-[10px] text-gray-400 text-center leading-tight">
                {formatDimLabel(key)}
              </span>
              <V3Badge variant={dim.signal === 'bullish' ? 'success' : dim.signal === 'bearish' ? 'danger' : 'default'} className="text-[9px]">
                {dim.signal}
              </V3Badge>
            </div>
          ))}
        </div>
      </V3Card>

      {/* 大师辩论 */}
      {debate && (
        <V3Card title="大师辩论" padding="sm">
          <div className="grid grid-cols-3 gap-3">
            <div className="p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/10">
              <h4 className="text-[10px] font-semibold text-emerald-400 mb-1">看多</h4>
              <p className="text-xs text-gray-300 leading-relaxed line-clamp-4">{debate.bullCase}</p>
            </div>
            <div className="p-3 rounded-lg bg-amber-500/5 border border-amber-500/10">
              <h4 className="text-[10px] font-semibold text-amber-400 mb-1">看空</h4>
              <p className="text-xs text-gray-300 leading-relaxed line-clamp-4">{debate.bearCase}</p>
            </div>
            <div className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/10">
              <h4 className="text-[10px] font-semibold text-blue-400 mb-1">综合</h4>
              <p className="text-xs text-gray-300 leading-relaxed line-clamp-4">{debate.synthesis}</p>
            </div>
          </div>
        </V3Card>
      )}
    </div>
  );
}

// 方向锚卡片
function DirectionAnchorCard({ directionAnchor, status }: { directionAnchor: Screen1Data['directionAnchor']; status: string }) {
  const isLong = directionAnchor.direction === 'LONG';
  return (
    <div className={`
      p-4 rounded-xl border-2 transition-all
      ${isLong ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-red-500/5 border-red-500/20'}
    `}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`
            w-10 h-10 rounded-lg flex items-center justify-center text-lg font-bold
            ${isLong ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}
          `}>
            {isLong ? 'L' : 'S'}
          </div>
          <div>
            <div className="text-sm font-semibold text-gray-100">
              {isLong ? '做多 (LONG)' : '做空 (SHORT)'}
            </div>
            <div className="text-xs text-gray-400 mt-0.5">
              综合评分: {directionAnchor.overallScore}/100 | 置信度: {(directionAnchor.confidence * 100).toFixed(0)}%
            </div>
          </div>
        </div>
        <div className="text-right">
          <V3Badge variant={status === 'done' ? 'success' : 'info'} dot pulse={status === 'analyzing'}>
            {status === 'done' ? '已确认' : status === 'analyzing' ? '分析中' : status}
          </V3Badge>
          <div className="text-[10px] text-gray-500 mt-1">
            MA200: {directionAnchor.ma200Status}
            {directionAnchor.threeDayConfirm ? ' (三日确认)' : ''}
          </div>
        </div>
      </div>
    </div>
  );
}

// 圆环评分（SVG circle 实现）
function ScoreRing({ score, size, colorIndex }: { score: number; size: number; colorIndex: number }) {
  const radius = (size - 6) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const colorClass = dimColors[colorIndex % dimColors.length];

  // 映射颜色到实际 stroke 值
  const strokeColorMap: Record<string, string> = {
    blue: '#3b82f6',
    purple: '#a855f7',
    amber: '#f59e0b',
    emerald: '#10b981',
    cyan: '#06b6d4',
    rose: '#f43f5e',
    orange: '#f97316',
  };
  const strokeColor = strokeColorMap[colorClass] || '#3b82f6';

  return (
    <svg width={size} height={size} className="transform -rotate-90">
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="currentColor" strokeWidth="3" className="text-gray-700" />
      <circle
        cx={size / 2} cy={size / 2} r={radius} fill="none"
        stroke={strokeColor}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        strokeWidth="3"
      />
      <text
        x={size / 2}
        y={size / 2}
        textAnchor="middle"
        dominantBaseline="central"
        className="fill-gray-200 text-[10px] font-semibold"
        transform={`rotate(90, ${size / 2}, ${size / 2})`}
      >
        {score}
      </text>
    </svg>
  );
}

/** 格式化维度标签 */
function formatDimLabel(key: string): string {
  const map: Record<string, string> = {
    technical: '技术面',
    halving: '减半',
    miner: '矿工',
    onchain: '链上',
    macro: '宏观',
    intermarket: '跨市场',
    sentiment: '情绪',
  };
  return map[key] || key;
}

export default Screen1Panel;
