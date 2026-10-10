'use client';

// ============================================
// DecisionHooks — 第4层单点决策钩子
// 基于维度分析，聚焦具体交易决策点
// 调用 A 系列 SKILL：screen(入场)/exit(离场)/risk(仓位风控)
// ============================================

import React from 'react';

export interface DecisionHook {
  id: string;
  label: string;
  icon: string;
  description: string;
  prompt: string;
  category: 'decision' | 'risk';
}

export const DEFAULT_DECISION_HOOKS: DecisionHook[] = [
  // 决策类
  {
    id: 'entry',
    label: '是否适合入场',
    icon: '🎯',
    description: 'Screen1/2/3 入场条件验证',
    prompt: '评估当前是否适合入场',
    category: 'decision',
  },
  {
    id: 'addon',
    label: '是否适合加仓',
    icon: '📈',
    description: '加仓条件评估与比例',
    prompt: '评估当前是否适合加仓',
    category: 'decision',
  },
  {
    id: 'exit',
    label: '是否适合离场',
    icon: '🚪',
    description: '止盈/止损信号与离场时机',
    prompt: '评估当前是否适合离场',
    category: 'decision',
  },
  {
    id: 'stoploss',
    label: '止损设置',
    icon: '🛡️',
    description: '止损位计算与策略',
    prompt: '计算合理的止损位',
    category: 'decision',
  },
  {
    id: 'position',
    label: '仓位配置',
    icon: '⚖️',
    description: '仓位比例与风控参数',
    prompt: '计算合理的仓位配置',
    category: 'decision',
  },
  // 风控类
  {
    id: 'risk-assess',
    label: '风险评估',
    icon: '⚠️',
    description: '单笔/组合风险评估',
    prompt: '评估当前交易风险',
    category: 'risk',
  },
  {
    id: 'extreme-alert',
    label: '极端行情预警',
    icon: '🌪️',
    description: '波动率/流动性/黑天鹅监测',
    prompt: '检查是否存在极端行情风险',
    category: 'risk',
  },
];

interface DecisionHooksProps {
  hooks?: DecisionHook[];
  onSelect: (hook: DecisionHook) => void;
  disabled?: boolean;
}

export function DecisionHooks({ hooks, onSelect, disabled }: DecisionHooksProps) {
  const availableHooks = hooks && hooks.length > 0 ? hooks : DEFAULT_DECISION_HOOKS;
  const decisionHooks = availableHooks.filter(h => h.category === 'decision');
  const riskHooks = availableHooks.filter(h => h.category === 'risk');

  return (
    <div className="p-3 bg-gradient-to-b from-amber-900/20 to-slate-900/40 rounded-lg border border-amber-700/30">
      <div className="text-[10px] text-amber-400 mb-2 flex items-center gap-1">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
        </svg>
        <span>交易决策（调用A系列SKILL）</span>
      </div>

      {decisionHooks.length > 0 && (
        <div className="mb-2">
          <div className="text-[9px] text-slate-500 mb-1">决策点</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {decisionHooks.map((hook) => (
              <button
                key={hook.id}
                onClick={() => onSelect(hook)}
                disabled={disabled}
                className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-amber-500/50 hover:bg-amber-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span className="text-base leading-none">{hook.icon}</span>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-200 group-hover:text-amber-300">
                    {hook.label}
                  </div>
                  <div className="text-[9px] text-slate-500 truncate">{hook.description}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {riskHooks.length > 0 && (
        <div>
          <div className="text-[9px] text-slate-500 mb-1">风险管理</div>
          <div className="grid grid-cols-2 gap-2">
            {riskHooks.map((hook) => (
              <button
                key={hook.id}
                onClick={() => onSelect(hook)}
                disabled={disabled}
                className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-red-500/50 hover:bg-red-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span className="text-base leading-none">{hook.icon}</span>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-200 group-hover:text-red-300">
                    {hook.label}
                  </div>
                  <div className="text-[9px] text-slate-500 truncate">{hook.description}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
