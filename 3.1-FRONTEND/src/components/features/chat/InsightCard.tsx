'use client';

// ============================================
// InsightCard — LLM 综合洞察卡片（支持折叠）
// ============================================

import React, { useState } from 'react';
import { V3Card } from '@/components/V3Card';
import { SynthesisChart, type ChartSpec } from './SynthesisChart';

export interface InsightItem {
  title: string;
  content: string;
  severity?: 'info' | 'warning' | 'critical';
  confidence?: number;
  source_modules?: string[];
  charts_ref?: ChartSpec[];
}

interface InsightCardProps {
  insights: InsightItem[];
  /** 是否默认展开第一项（深度分析报告建议 true） */
  defaultExpandFirst?: boolean;
}

const severityStyles = {
  info: {
    border: 'border-l-blue-500/50',
    badge: 'bg-blue-500/15 text-blue-300',
    label: '信息',
  },
  warning: {
    border: 'border-l-amber-500/50',
    badge: 'bg-amber-500/15 text-amber-300',
    label: '警告',
  },
  critical: {
    border: 'border-l-red-500/50',
    badge: 'bg-red-500/15 text-red-300',
    label: '关键',
  },
};

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`w-3.5 h-3.5 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
    </svg>
  );
}

export function InsightCard({ insights, defaultExpandFirst = true }: InsightCardProps) {
  if (!insights || insights.length === 0) return null;

  // 深度分析报告通常 >3 条洞察，启用折叠；普通少量洞察直接展开
  const useCollapse = insights.length > 3;
  const [openIdx, setOpenIdx] = useState<number | null>(defaultExpandFirst ? 0 : null);

  const toggle = (idx: number) => {
    setOpenIdx(prev => (prev === idx ? null : idx));
  };

  return (
    <V3Card
      title="AI 洞察"
      subtitle="基于多模块信号综合分析"
      icon={
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m7.5 0a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z" />
        </svg>
      }
      badge={
        <span className="text-[10px] text-gray-400 bg-gray-800/50 px-2 py-0.5 rounded-full">
          {insights.length} 条
        </span>
      }
    >
      <div className="space-y-1.5">
        {insights.map((insight, idx) => {
          const severity = insight.severity || 'info';
          const style = severityStyles[severity];
          const isOpen = !useCollapse || openIdx === idx;

          return (
            <div
              key={idx}
              className={`border-l-2 ${style.border} rounded-r-md bg-gray-800/20`}
            >
              {/* 可点击标题栏 */}
              <button
                type="button"
                onClick={() => useCollapse && toggle(idx)}
                className={`w-full flex items-center gap-2 px-3 py-2 text-left ${useCollapse ? 'cursor-pointer hover:bg-gray-700/20' : ''}`}
              >
                {useCollapse && (
                  <span className="text-gray-500 shrink-0">
                    <ChevronIcon open={isOpen} />
                  </span>
                )}
                <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${style.badge}`}>
                  {style.label}
                </span>
                <h4 className="text-sm font-medium text-gray-100 flex-1 truncate">
                  {insight.title}
                </h4>
                {insight.confidence !== undefined && (
                  <span className="text-[10px] text-gray-500 shrink-0">
                    {(insight.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </button>

              {/* 折叠内容 */}
              {isOpen && (
                <div className="px-3 pb-2.5 pt-0.5 space-y-1.5">
                  <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-wrap">
                    {insight.content}
                  </p>
                  {insight.source_modules && insight.source_modules.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {insight.source_modules.map((mod, i) => (
                        <span key={i} className="text-[9px] text-gray-500 bg-gray-800/40 px-1.5 py-0.5 rounded">
                          {mod}
                        </span>
                      ))}
                    </div>
                  )}
                  {insight.charts_ref && insight.charts_ref.length > 0 && (
                    <div className="space-y-1 pt-1">
                      {insight.charts_ref.map((chart, ci) => (
                        <SynthesisChart key={ci} chart={chart} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </V3Card>
  );
}

export default InsightCard;
