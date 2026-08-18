'use client';

import React from 'react';
import { useThreeScreensStore, type Screen1Data } from '@/stores';
import { V3Card, V3Badge, V3StatusDot, V3Empty, V3Button } from '@/components';

// 七维颜色
const dimColors = ['blue', 'purple', 'amber', 'emerald', 'cyan', 'rose', 'orange'];
const dimLabels: Record<string, string> = {
  macro: '宏观', onchain: '链上', technical: '技术面',
  sentiment: '情绪', fundamental: '基本面', timing: '时机', risk: '风险',
};

export function Screen1Panel() {
  const { screen1, propagationStatus } = useThreeScreensStore();

  if (!screen1) {
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

  const { dimensions, directionAnchor } = screen1;
  const dims = Object.entries(dimensions) as [string, { score: number; label: string }][];
  const isLong = directionAnchor === 'bullish';
  const isShort = directionAnchor === 'bearish';

  return (
    <div className="space-y-4">
      {/* 方向锚 */}
      <div className={`
        p-4 rounded-xl border-2 transition-all
        ${isLong ? 'bg-emerald-500/5 border-emerald-500/20' : isShort ? 'bg-red-500/5 border-red-500/20' : 'bg-slate-800/30 border-slate-600/20'}
      `}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`
              w-10 h-10 rounded-lg flex items-center justify-center text-lg font-bold
              ${isLong ? 'bg-emerald-500/20 text-emerald-400' : isShort ? 'bg-red-500/20 text-red-400' : 'bg-slate-600/20 text-slate-400'}
            `}>
              {isLong ? 'L' : isShort ? 'S' : 'N'}
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-200">
                {isLong ? '做多 (LONG)' : isShort ? '做空 (SHORT)' : '中性 (NEUTRAL)'}
              </div>
              <div className="text-xs text-slate-400 mt-0.5">
                方向锚定: {directionAnchor || '未设置'}
              </div>
            </div>
          </div>
          <div className="text-right">
            <V3Badge variant={propagationStatus === 's1_complete' ? 'success' : 'info'} dot pulse={propagationStatus === 'idle'}>
              {propagationStatus === 's1_complete' ? '已完成' : '分析中'}
            </V3Badge>
          </div>
        </div>
      </div>

      {/* 七维评分 */}
      <V3Card title="七维牛熊评分" padding="sm">
        <div className="grid grid-cols-4 gap-3 sm:grid-cols-7">
          {dims.map(([key, dim], i) => (
            <div key={key} className="flex flex-col items-center gap-1.5 p-2 rounded-lg bg-slate-800/30">
              <ScoreRing score={dim.score} size={48} colorIndex={i} />
              <span className="text-[10px] text-slate-400 text-center leading-tight">
                {dimLabels[key] || key}
              </span>
              <span className="text-[9px] text-slate-300">{dim.label}</span>
            </div>
          ))}
        </div>
      </V3Card>

      {/* 辩论摘要 */}
      {screen1.debate && (
        <V3Card title="大师辩论" padding="sm">
          <div className="p-3 rounded-lg bg-slate-800/20 border border-slate-700/20">
            <p className="text-xs text-slate-300 leading-relaxed">{screen1.debate}</p>
          </div>
        </V3Card>
      )}
    </div>
  );
}

// 圆环评分（SVG circle 实现）
function ScoreRing({ score, size, colorIndex }: { score: number; size: number; colorIndex: number }) {
  const radius = (size - 6) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const colorClass = dimColors[colorIndex % dimColors.length];

  const strokeColorMap: Record<string, string> = {
    blue: '#3b82f6', purple: '#a855f7', amber: '#f59e0b',
    emerald: '#10b981', cyan: '#06b6d4', rose: '#f43f5e', orange: '#f97316',
  };
  const strokeColor = strokeColorMap[colorClass] || '#3b82f6';

  return (
    <svg width={size} height={size} className="transform -rotate-90">
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="currentColor" strokeWidth="3" className="text-slate-700" />
      <circle
        cx={size / 2} cy={size / 2} r={radius} fill="none"
        stroke={strokeColor} strokeDasharray={circumference}
        strokeDashoffset={offset} strokeLinecap="round" strokeWidth="3"
      />
      <text
        x={size / 2} y={size / 2} textAnchor="middle" dominantBaseline="central"
        className="fill-slate-200 text-[10px] font-semibold"
        transform={`rotate(90, ${size / 2}, ${size / 2})`}
      >
        {score}
      </text>
    </svg>
  );
}

export default Screen1Panel;
