'use client';

// ============================================
// MonitorHooks — 第0层市场监控 + 第8层持续监控钩子
// 第0层: 市场扫描/机会预警/组合概览（前置主动）
// 第8层: 实时监控/异动预警/定时报告（后置主动）
// ============================================

import React from 'react';

export interface MonitorHook {
  id: string;
  label: string;
  icon: string;
  description: string;
  prompt: string;
  category: 'scan' | 'monitor';
}

export const DEFAULT_MONITOR_HOOKS: MonitorHook[] = [
  // 第0层：市场扫描（前置）
  {
    id: 'market-scan',
    label: '全市场扫描',
    icon: '📡',
    description: '扫描全市场交易机会',
    prompt: '扫描全市场，找出当前的交易机会',
    category: 'scan',
  },
  {
    id: 'opportunity-alert',
    label: '机会预警',
    icon: '🔔',
    description: '设置条件预警通知',
    prompt: '设置交易机会预警',
    category: 'scan',
  },
  {
    id: 'portfolio-overview',
    label: '组合概览',
    icon: '📊',
    description: '当前持仓与盈亏',
    prompt: '查看我的投资组合概览',
    category: 'scan',
  },
  // 第8层：持续监控（后置）
  {
    id: 'realtime-monitor',
    label: '实时监控',
    icon: '👁️',
    description: '持仓/信号/风险监控',
    prompt: '实时监控我的持仓和信号',
    category: 'monitor',
  },
  {
    id: 'anomaly-alert',
    label: '异动预警',
    icon: '⚠️',
    description: '价格/成交量/链上异动',
    prompt: '检查是否有市场异动',
    category: 'monitor',
  },
  {
    id: 'daily-report',
    label: '日报',
    icon: '📅',
    description: '当日盈亏与表现',
    prompt: '生成今日交易日报',
    category: 'monitor',
  },
  {
    id: 'weekly-report',
    label: '周报',
    icon: '📆',
    description: '周度策略表现',
    prompt: '生成本周交易周报',
    category: 'monitor',
  },
  {
    id: 'monthly-report',
    label: '月报',
    icon: '🗓️',
    description: '月度综合评估',
    prompt: '生成本月交易月报',
    category: 'monitor',
  },
];

interface MonitorHooksProps {
  hooks?: MonitorHook[];
  onSelect: (hook: MonitorHook) => void;
  disabled?: boolean;
}

export function MonitorHooks({ hooks, onSelect, disabled }: MonitorHooksProps) {
  const availableHooks = hooks && hooks.length > 0 ? hooks : DEFAULT_MONITOR_HOOKS;
  const scanHooks = availableHooks.filter(h => h.category === 'scan');
  const monitorHooks = availableHooks.filter(h => h.category === 'monitor');

  return (
    <div className="space-y-3">
      {/* 第0层：市场扫描 */}
      <div className="p-3 bg-gradient-to-b from-cyan-900/20 to-slate-900/40 rounded-lg border border-cyan-700/30">
        <div className="text-[10px] text-cyan-400 mb-2 flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
          </svg>
          <span>市场扫描</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {scanHooks.map((hook) => (
            <button
              key={hook.id}
              onClick={() => onSelect(hook)}
              disabled={disabled}
              className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-cyan-500/50 hover:bg-cyan-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="text-base leading-none">{hook.icon}</span>
              <div className="min-w-0">
                <div className="text-xs font-medium text-slate-200 group-hover:text-cyan-300">
                  {hook.label}
                </div>
                <div className="text-[9px] text-slate-500 truncate">{hook.description}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* 第8层：持续监控 */}
      <div className="p-3 bg-gradient-to-b from-teal-900/20 to-slate-900/40 rounded-lg border border-teal-700/30">
        <div className="text-[10px] text-teal-400 mb-2 flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
          </svg>
          <span>持续监控</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {monitorHooks.map((hook) => (
            <button
              key={hook.id}
              onClick={() => onSelect(hook)}
              disabled={disabled}
              className="group flex items-start gap-2 p-2 rounded-md bg-slate-800/50 border border-slate-700/40 hover:border-teal-500/50 hover:bg-teal-900/20 transition-all text-left disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <span className="text-base leading-none">{hook.icon}</span>
              <div className="min-w-0">
                <div className="text-xs font-medium text-slate-200 group-hover:text-teal-300">
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
