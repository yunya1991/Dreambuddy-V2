'use client';

import React from 'react';
import type { StepConfirmation as StepConfirmationData } from '@/stores';

const STEP_NAME_MAP: Record<string, string> = {
  S1_RESEARCH: 'S1 调研',
  S2_ANALYSIS: 'S2 分析',
  S3_DESIGN: 'S3 设计',
  S4_VALIDATE: 'S4 验证',
  S5_EXECUTE: 'S5 执行',
};

interface StepConfirmationProps {
  data: StepConfirmationData;
  onChoose: (action: 'continue' | 'finalize' | 'skip') => void;
  disabled?: boolean;
}

export function StepConfirmation({ data, onChoose, disabled }: StepConfirmationProps) {
  const currentName = STEP_NAME_MAP[data.current_step] || data.current_step;
  const nextName = data.next_step ? STEP_NAME_MAP[data.next_step] || data.next_step : null;

  const recommendedKey = data.next_step ? data.options[0]?.key : data.options[1]?.key || data.options[0]?.key;

  return (
    <div className="mt-3 pt-3 border-t border-slate-700/50">
      <div className="flex items-center gap-2 mb-2 text-xs">
        <span className="px-1.5 py-0.5 bg-purple-500/20 text-purple-300 rounded font-mono">{currentName}</span>
        <span className="text-slate-500">已完成 ·</span>
        {nextName && (
          <>
            <span className="text-slate-500">下一步:</span>
            <span className="px-1.5 py-0.5 bg-cyan-500/20 text-cyan-300 rounded font-mono">{nextName}</span>
          </>
        )}
      </div>
      <div className="text-xs text-slate-300 mb-2 font-medium">🔗 请选择下一步操作：</div>
      <div className="flex flex-col gap-2">
        {data.options.map((opt, idx) => {
          const isRecommended = opt.key === recommendedKey;
          return (
            <button
              key={opt.key || idx}
              onClick={() => onChoose(opt.action)}
              disabled={disabled}
              className={`group flex items-start gap-3 px-3 py-2.5 text-left text-xs rounded-lg transition border ${
                isRecommended
                  ? 'bg-gradient-to-r from-purple-500/20 to-cyan-500/10 border-purple-500/60 hover:from-purple-500/30 hover:to-cyan-500/20'
                  : 'bg-slate-900 border-slate-700 hover:bg-slate-800 hover:border-slate-600'
              } disabled:opacity-50`}
            >
              <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center font-bold text-sm ${
                isRecommended ? 'bg-purple-500 text-white' : 'bg-slate-700 text-slate-300 group-hover:bg-slate-600'
              }`}>
                {opt.key || idx + 1}
              </div>
              <div className="flex-1 min-w-0">
                <div className={`font-semibold ${isRecommended ? 'text-purple-200' : 'text-slate-200'}`}>
                  {opt.label || opt.key}
                  {isRecommended && (
                    <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 bg-cyan-500/20 text-cyan-300 rounded text-[9px] font-bold">
                      💡 系统推荐
                    </span>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
