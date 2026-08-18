'use client';

import React from 'react';
import { V3StatusDot } from '@/components';
import { V3Badge } from '@/components';

interface StreamingIndicatorProps {
  /** 是否处于流式输出状态 */
  isActive: boolean;
  /** 当前步骤名称 */
  stepName?: string;
  /** 当前步骤索引 */
  stepIndex?: number;
  /** 总步骤数 */
  totalSteps?: number;
  /** 额外样式 */
  className?: string;
}

/**
 * StreamingIndicator — 流式输出进度指示
 *
 * 显示当前处理状态，包含：
 * - 脉冲状态点
 * - 步骤名称
 * - 步骤进度（如 2/5）
 *
 * isActive 为 false 时不渲染。
 */
export function StreamingIndicator({
  isActive,
  stepName,
  stepIndex,
  totalSteps,
  className = '',
}: StreamingIndicatorProps) {
  if (!isActive) return null;

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-800/40 border border-gray-700/20 ${className}`}>
      {/* 脉冲状态点 */}
      <V3StatusDot status="active" size="sm" pulse />

      {/* 步骤名称 */}
      <span className="text-xs text-gray-300">
        {stepName || '处理中'}
      </span>

      {/* 步骤进度 */}
      {stepIndex !== undefined && totalSteps !== undefined && (
        <span className="text-[10px] text-gray-500">
          {stepIndex + 1}/{totalSteps}
        </span>
      )}
    </div>
  );
}

export default StreamingIndicator;
