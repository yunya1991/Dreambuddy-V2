'use client';

import { V3Card, V3Button, V3StatusDot } from '@/components';
import { useMemoryStore } from '@/stores';

const chainColors = {
  D: { border: 'border-blue-500/30', bg: 'bg-blue-900/10', text: 'text-blue-400', dot: 'active' as const },
  Z: { border: 'border-purple-500/30', bg: 'bg-purple-900/10', text: 'text-purple-400', dot: 'active' as const },
  E: { border: 'border-amber-500/30', bg: 'bg-amber-900/10', text: 'text-amber-400', dot: 'active' as const },
};

const stepLabels: Record<string, string[]> = {
  D: ['D1 需求分析', 'D2 调研', 'D3 方案设计', 'D4 评审'],
  Z: ['Z1 架构', 'Z2 编码', 'Z3 测试', 'Z4 部署'],
  E: ['E1 自动评估', 'E2 人工审核', 'E3 发布'],
};

export function DZEChainView() {
  const { dzeChains, records, updateChainStatus } = useMemoryStore();

  return (
    <div className="space-y-4">
      {dzeChains.map(chain => {
        const colors = chainColors[chain.chain];
        const steps = stepLabels[chain.chain] || [];
        return (
          <V3Card key={chain.chain} className={`border ${colors.border}`} padding="sm">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <V3StatusDot status={chain.status === 'running' ? 'active' : chain.status === 'done' ? 'success' : chain.status === 'error' ? 'error' : 'idle'} size="sm" />
                <span className={`text-sm font-medium ${colors.text}`}>{chain.label}</span>
              </div>
              <span className="text-[10px] text-slate-500">{chain.currentStep}/{chain.totalSteps}</span>
            </div>
            <div className="space-y-1">
              {steps.map((step, i) => (
                <div key={i} className={`flex items-center gap-2 p-2 rounded text-[10px] ${i < chain.currentStep ? 'bg-slate-800/50 text-slate-400' : i === chain.currentStep ? `${colors.bg} ${colors.text} border ${colors.border}` : 'bg-slate-900/30 text-slate-600'}`}>
                  <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold ${i < chain.currentStep ? 'bg-emerald-900/30 text-emerald-400' : i === chain.currentStep ? 'bg-indigo-900/30 text-indigo-400' : 'bg-slate-800 text-slate-600'}`}>
                    {i < chain.currentStep ? '✓' : i + 1}
                  </span>
                  {step}
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2 mt-3">
              {chain.status !== 'running' && (
                <V3Button size="sm" variant="secondary" onClick={() => updateChainStatus(chain.chain, { status: 'running', currentStep: 0 })}>
                  执行
                </V3Button>
              )}
            </div>
          </V3Card>
        );
      })}
    </div>
  );
}
