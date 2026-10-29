'use client';

import { CycleThinkingPanel } from '@/components/features/cycle/CycleThinkingPanel';

/**
 * 周期研究面板（40-周期神经网络系统 路1 前端思考框架）
 *
 * 红线约束：
 * - 呈现标注研究建议，与交易 UI 隔离
 * - 消费 effective_confidence 而非原始置信度
 * - 只读消费 /api/cycle 端点，不触发任何下单动作
 */
export default function CyclePage() {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h1 className="text-lg font-bold text-slate-200">周期研究</h1>
        <p className="text-xs text-slate-500">
          40-周期神经网络系统 · 周期思考卡片（研究建议，非交易信号）
        </p>
      </div>
      <CycleThinkingPanel />
    </div>
  );
}
