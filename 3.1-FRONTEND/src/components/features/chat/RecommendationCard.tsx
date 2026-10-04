'use client';

// ============================================
// RecommendationCard — LLM 综合建议卡片
// ============================================

import React from 'react';
import { V3Card } from '@/components/V3Card';
import { SynthesisChart, type ChartSpec } from './SynthesisChart';

export interface RecommendationItem {
  action: string;
  reason: string;
  priority?: 'low' | 'medium' | 'high';
  confidence?: number;
  source_modules?: string[];
  charts_ref?: ChartSpec[];
}

interface RecommendationCardProps {
  recommendations: RecommendationItem[];
}

const priorityStyles = {
  low: {
    border: 'border-l-gray-500/50',
    badge: 'bg-gray-500/15 text-gray-300',
    label: '低',
  },
  medium: {
    border: 'border-l-blue-500/50',
    badge: 'bg-blue-500/15 text-blue-300',
    label: '中',
  },
  high: {
    border: 'border-l-purple-500/50',
    badge: 'bg-purple-500/15 text-purple-300',
    label: '高',
  },
};

export function RecommendationCard({ recommendations }: RecommendationCardProps) {
  if (!recommendations || recommendations.length === 0) return null;

  return (
    <V3Card
      title="行动建议"
      subtitle="基于综合洞察的执行建议"
      icon={
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        </svg>
      }
      badge={
        <span className="text-[10px] text-gray-400 bg-gray-800/50 px-2 py-0.5 rounded-full">
          {recommendations.length} 条
        </span>
      }
    >
      <div className="space-y-2.5">
        {recommendations.map((rec, idx) => {
          const priority = rec.priority || 'medium';
          const style = priorityStyles[priority];
          return (
            <div
              key={idx}
              className={`border-l-2 ${style.border} pl-3 py-1.5`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-[10px] px-1.5 py-0.5 rounded ${style.badge}`}>
                  {style.label}优先
                </span>
                {rec.confidence !== undefined && (
                  <span className="text-[10px] text-gray-500">
                    置信度 {(rec.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              <h4 className="text-sm font-medium text-gray-100 mb-0.5">
                {rec.action}
              </h4>
              <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-wrap">
                {rec.reason}
              </p>
              {rec.source_modules && rec.source_modules.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {rec.source_modules.map((mod, i) => (
                    <span key={i} className="text-[9px] text-gray-500 bg-gray-800/40 px-1.5 py-0.5 rounded">
                      {mod}
                    </span>
                  ))}
                </div>
              )}
              {rec.charts_ref && rec.charts_ref.length > 0 && (
                <div className="mt-2 space-y-1">
                  {rec.charts_ref.map((chart, ci) => (
                    <SynthesisChart key={ci} chart={chart} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </V3Card>
  );
}

export default RecommendationCard;
