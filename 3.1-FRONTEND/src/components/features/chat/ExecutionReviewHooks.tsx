'use client';

// ============================================
// ExecutionReviewHooks — 第6层交易执行 + 第7层复盘迭代钩子
// 第6层: 订单管理/滑点控制/成本分析
// 第7层: 交易复盘/绩效归因/策略迭代
// ============================================

import React from 'react';

export interface ExecutionReviewHook {
  id: string;
  label: string;
  icon: string;
  description: string;
  prompt: string;
  category: 'execution' | 'review';
}

export const DEFAULT_EXECUTION_REVIEW_HOOKS: ExecutionReviewHook[] = [
  // 第6层：交易执行
  {
    id: 'order-market',
    label: '市价单执行',
    icon: '⚡',
    description: '立即市价成交',
    prompt: '用市价单执行当前交易',
    category: 'execution',
  },
  {
    id: 'order-limit',
    label: '限价单设置',
    icon: '📋',
    description: '设置限价买入/卖出',
    prompt: '设置限价单',
    category: 'execution',
  },
  {
    id: 'order-stop',
    label: '止损单设置',
    icon: '🛑',
    description: '设置止损止盈单',
    prompt: '设置止损止盈单',
    category: 'execution',
  },
  {
    id: 'order-trailing',
    label: '追踪止损',
    icon: '🎢',
    description: '移动止损锁定利润',
    prompt: '设置追踪止损',
    category: 'execution',
  },
  {
    id: 'slippage-control',
    label: '滑点控制',
    icon: '📉',
    description: '分单执行/TWAP/VWAP',
    prompt: '用分单执行控制滑点',
    category: 'execution',
  },
  {
    id: 'cost-analysis',
    label: '成本分析',
    icon: '💰',
    description: '手续费+滑点+费率',
    prompt: '分析本次交易的总成本',
    category: 'execution',
  },
  // 第7层：复盘迭代
  {
    id: 'trade-review',
    label: '交易复盘',
    icon: '🔍',
    description: '每笔交易入场/出场/盈亏',
    prompt: '复盘最近的交易',
    category: 'review',
  },
  {
    id: 'perf-attribution',
    label: '绩效归因',
    icon: '📊',
    description: '盈亏来源分析',
    prompt: '分析盈亏来源',
    category: 'review',
  },
  {
    id: 'strategy-iterate',
    label: '策略迭代',
    icon: '🔄',
    description: '基于复盘优化策略',
    prompt: '基于复盘结果优化策略',
    category: 'review',
  },
];

interface ExecutionReviewHooksProps {
  hooks?: ExecutionReviewHook[];
  onSelect: (hook: ExecutionReviewHook) => void;
  disabled?: boolean;
}

export function ExecutionReviewHooks({ hooks, onSelect, disabled }: ExecutionReviewHooksProps) {
  const availableHooks = hooks && hooks.length > 0 ? hooks : DEFAULT_EXECUTION_REVIEW_HOOKS;
  const execHooks = availableHooks.filter(h => h.category === 'execution');
  const reviewHooks = availableHooks.filter(h => h.category === 'review');

  return (
    <div className="space-y-3">
      {/* 第6层：交易执行 */}
      <div className="p-3 bg-gradient-to-b from-blue-900/20 to-slate-900/40 rounded-lg border border-blue-700/30">
        <div className="text-[10px] text-blue-400 mb-2 flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          <span>交易执行</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {execHooks.map((hook) => (
            <button
              key={hook.id}
              onClick={() => onSelect(hook)}
              disabled={disabled}
              className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-blue-500/50 hover:bg-blue-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="text-base leading-none">{hook.icon}</span>
              <div className="min-w-0">
                <div className="text-xs font-medium text-slate-200 group-hover:text-blue-300">
                  {hook.label}
                </div>
                <div className="text-[9px] text-slate-500 truncate">{hook.description}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 第7层：复盘迭代 */}
      <div className="p-3 bg-gradient-to-b from-purple-900/20 to-slate-900/40 rounded-lg border border-purple-700/30">
        <div className="text-[10px] text-purple-400 mb-2 flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <span>复盘迭代</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {reviewHooks.map((hook) => (
            <button
              key={hook.id}
              onClick={() => onSelect(hook)}
              disabled={disabled}
              className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-purple-500/50 hover:bg-purple-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="text-base leading-none">{hook.icon}</span>
              <div className="min-w-0">
                <div className="text-xs font-medium text-slate-200 group-hover:text-purple-300">
                  {hook.label}
                </div>
                <div className="text-[9px] text-slate-500 truncate">{hook.description}</div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
