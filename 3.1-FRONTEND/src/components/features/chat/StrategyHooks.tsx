'use client';

// ============================================
// StrategyHooks — 第5层策略生成钩子
// 大模型+系统能力+开发SKILL，生成可执行交易策略
// 对接子交易系统(BDSM/BCRM/马丁) + 经典体系(Freqtrade)
// ============================================

import React from 'react';

export interface StrategyHook {
  id: string;
  label: string;
  icon: string;
  description: string;
  prompt: string;
  category: 'generate' | 'optimize';
}

export const DEFAULT_STRATEGY_HOOKS: StrategyHook[] = [
  // 策略生成
  {
    id: 'gen-bdsm',
    label: 'BDSM 子系统策略',
    icon: '🧠',
    description: '大脑决策系统生成策略',
    prompt: '生成一个BDSM子系统的交易策略',
    category: 'generate',
  },
  {
    id: 'gen-bcrm',
    label: 'BCRM 风控策略',
    icon: '🛡️',
    description: '风控增强型策略',
    prompt: '生成一个BCRM风控增强的交易策略',
    category: 'generate',
  },
  {
    id: 'gen-martingale',
    label: '马丁策略',
    icon: '📊',
    description: '经典马丁加仓策略',
    prompt: '生成一个马丁加仓策略',
    category: 'generate',
  },
  {
    id: 'gen-freqtrade',
    label: 'Freqtrade 策略',
    icon: '🐍',
    description: 'Freqtrade 框架策略代码',
    prompt: '生成一个Freqtrade框架的交易策略代码',
    category: 'generate',
  },
  {
    id: 'gen-custom',
    label: '自定义策略',
    icon: '✨',
    description: '基于偏好生成策略',
    prompt: '根据我的偏好生成一个交易策略',
    category: 'generate',
  },
  // 策略优化
  {
    id: 'opt-bayesian',
    label: '贝叶斯参数优化',
    icon: '🎯',
    description: '贝叶斯优化策略参数',
    prompt: '用贝叶斯优化当前策略参数',
    category: 'optimize',
  },
  {
    id: 'opt-compare',
    label: '策略对比',
    icon: '⚖️',
    description: '多策略回测对比',
    prompt: '对比多个交易策略的表现',
    category: 'optimize',
  },
  {
    id: 'opt-decay',
    label: '策略衰减监测',
    icon: '📉',
    description: 'Walk-forward 验证',
    prompt: '检测当前策略是否衰减',
    category: 'optimize',
  },
];

interface StrategyHooksProps {
  hooks?: StrategyHook[];
  onSelect: (hook: StrategyHook) => void;
  disabled?: boolean;
}

export function StrategyHooks({ hooks, onSelect, disabled }: StrategyHooksProps) {
  const availableHooks = hooks && hooks.length > 0 ? hooks : DEFAULT_STRATEGY_HOOKS;
  const genHooks = availableHooks.filter(h => h.category === 'generate');
  const optHooks = availableHooks.filter(h => h.category === 'optimize');

  return (
    <div className="p-3 bg-gradient-to-b from-emerald-900/20 to-slate-900/40 rounded-lg border border-emerald-700/30">
      <div className="text-[10px] text-emerald-400 mb-2 flex items-center gap-1">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
        <span>策略生成与优化</span>
      </div>

      {genHooks.length > 0 && (
        <div className="mb-2">
          <div className="text-[9px] text-slate-500 mb-1">生成策略</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {genHooks.map((hook) => (
              <button
                key={hook.id}
                onClick={() => onSelect(hook)}
                disabled={disabled}
                className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-emerald-500/50 hover:bg-emerald-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span className="text-base leading-none">{hook.icon}</span>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-200 group-hover:text-emerald-300">
                    {hook.label}
                  </div>
                  <div className="text-[9px] text-slate-500 truncate">{hook.description}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {optHooks.length > 0 && (
        <div>
          <div className="text-[9px] text-slate-500 mb-1">策略优化</div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {optHooks.map((hook) => (
              <button
                key={hook.id}
                onClick={() => onSelect(hook)}
                disabled={disabled}
                className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-emerald-500/50 hover:bg-emerald-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span className="text-base leading-none">{hook.icon}</span>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-200 group-hover:text-emerald-300">
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
