'use client';

// ============================================
// EnhancementHints — SKILL 增强提示卡片
// ============================================
// 当 synthesizer 检测到数据不足/信号冲突/低置信度时,
// 后端返回 enhancement_hints, 前端渲染为可选的 SKILL 调用入口.

import React, { useState } from 'react';
import { V3Card } from '@/components/V3Card';

export interface EnhancementHint {
  skill_key: string;
  skill_name: string;
  description?: string;
  reason: string;
  target_modules?: string[];
  priority?: 'low' | 'medium' | 'high';
}

interface EnhancementHintsProps {
  hints: EnhancementHint[];
}

const priorityStyles = {
  high: {
    badge: 'bg-red-500/15 text-red-300 border-red-500/30',
    dot: 'bg-red-400',
  },
  medium: {
    badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    dot: 'bg-amber-400',
  },
  low: {
    badge: 'bg-gray-500/15 text-gray-400 border-gray-500/30',
    dot: 'bg-gray-400',
  },
};

export function EnhancementHints({ hints }: EnhancementHintsProps) {
  const [invoked, setInvoked] = useState<Record<string, boolean>>({});

  if (!hints || hints.length === 0) return null;

  const handleInvoke = (skillKey: string) => {
    // 标记为已调用 (实际 SKILL 执行由 IDE/WorkBuddy 处理)
    setInvoked(prev => ({ ...prev, [skillKey]: true }));
  };

  return (
    <V3Card
      title="深度增强"
      subtitle="检测到可优化维度, 可调用 SKILL 进一步分析"
      icon={
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5 12 5.25l8.25 8.25M3.75 19.5 12 11.25l8.25 8.25" />
        </svg>
      }
      badge={
        <span className="text-[10px] text-gray-400 bg-gray-800/50 px-2 py-0.5 rounded-full">
          {hints.length} 项
        </span>
      }
    >
      <div className="space-y-1.5">
        {hints.map((hint, idx) => {
          const priority = hint.priority || 'medium';
          const style = priorityStyles[priority];
          const isInvoked = invoked[hint.skill_key];

          return (
            <div
              key={idx}
              className="flex items-start gap-2 p-2 rounded-md bg-gray-800/30 border border-gray-700/30"
            >
              <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${style.dot}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-gray-100">
                    {hint.description || hint.skill_name}
                  </span>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded border ${style.badge}`}>
                    {priority === 'high' ? '高优先级' : priority === 'medium' ? '中优先级' : '低优先级'}
                  </span>
                </div>
                <p className="text-xs text-gray-400 mt-0.5">{hint.reason}</p>
                {hint.target_modules && hint.target_modules.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {hint.target_modules.map((mod, i) => (
                      <span key={i} className="text-[9px] text-gray-500 bg-gray-800/40 px-1.5 py-0.5 rounded">
                        {mod}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => handleInvoke(hint.skill_key)}
                disabled={isInvoked}
                className={`shrink-0 text-[11px] px-2.5 py-1 rounded transition-colors ${
                  isInvoked
                    ? 'bg-green-500/15 text-green-300 cursor-default'
                    : 'bg-blue-500/15 text-blue-300 hover:bg-blue-500/25'
                }`}
              >
                {isInvoked ? '已触发' : '调用'}
              </button>
            </div>
          );
        })}
      </div>
      <p className="text-[10px] text-gray-500 mt-2 italic">
        SKILL 执行由 WorkBuddy 处理, 结果将补充到后续分析
      </p>
    </V3Card>
  );
}

export default EnhancementHints;
