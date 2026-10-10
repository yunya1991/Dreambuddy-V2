'use client';

// ============================================
// DimensionHooks — 维度深度分析钩子
// 用户点击后触发对应维度的深度分析任务
// ============================================

import React from 'react';

export interface DimensionHook {
  id: string;           // technical | flow | sentiment | valuation | onchain | macro
  label: string;        // 显示文本
  icon: string;         // emoji 图标
  description: string;  // 简短描述
  prompt: string;       // 点击后发送的提示词
}

// 6 个标准维度钩子
export const DEFAULT_DIMENSION_HOOKS: DimensionHook[] = [
  {
    id: 'technical',
    label: '技术面',
    icon: '📈',
    description: 'RSI/MACD/均线/K线形态',
    prompt: '深入分析技术面',
  },
  {
    id: 'flow',
    label: '资金面',
    icon: '💰',
    description: '资金费率/大单流入/持仓量',
    prompt: '深入分析资金面',
  },
  {
    id: 'sentiment',
    label: '情绪面',
    icon: '😊',
    description: '恐惧贪婪指数/多空比',
    prompt: '深入分析情绪面',
  },
  {
    id: 'valuation',
    label: '基本面',
    icon: '📊',
    description: '估值/链上指标/经济模型',
    prompt: '深入分析基本面',
  },
  {
    id: 'onchain',
    label: '链上',
    icon: '⛓️',
    description: '活跃地址/大额转账/Gas',
    prompt: '深入分析链上数据',
  },
  {
    id: 'macro',
    label: '宏观',
    icon: '🌐',
    description: '利率/通胀/美元指数',
    prompt: '深入分析宏观环境',
  },
];

interface DimensionHooksProps {
  hooks?: DimensionHook[];
  onSelect: (hook: DimensionHook) => void;
  disabled?: boolean;
}

export function DimensionHooks({ hooks, onSelect, disabled }: DimensionHooksProps) {
  const availableHooks = hooks && hooks.length > 0 ? hooks : DEFAULT_DIMENSION_HOOKS;

  return (
    <div className="p-3 bg-gradient-to-b from-indigo-900/20 to-slate-900/40 rounded-lg border border-indigo-700/30">
      <div className="text-[10px] text-indigo-400 mb-2 flex items-center gap-1">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <span>维度深度分析（点击调用算法+大模型）</span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {availableHooks.map((hook) => (
          <button
            key={hook.id}
            onClick={() => onSelect(hook)}
            disabled={disabled}
            className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-indigo-500/50 hover:bg-indigo-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span className="text-base leading-none">{hook.icon}</span>
            <div className="min-w-0">
              <div className="text-xs font-medium text-slate-200 group-hover:text-indigo-300">
                {hook.label}
              </div>
              <div className="text-[9px] text-slate-500 truncate">{hook.description}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
