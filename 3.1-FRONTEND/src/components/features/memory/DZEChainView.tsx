'use client';

import { useEffect, useState } from 'react';
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

// P2: DZE 链 → 4-MEMORY 分类轴映射（SPEC §3.3）
// SPEC 设计意图（4-MEMORY 7 类分类轴）:
//   D 链 → 3-架构记忆 + 0-元记忆
//   Z 链 → 5-通用经验 + 1-原则记忆
//   E 链 → 2-方法论记忆 + 4-信息记忆单元
// 后端实际 type_distribution key: experience/knowledge/observation
// 双映射: 既匹配 SPEC 4-MEMORY 分类轴，也 fallback 匹配后端实际 key
const chainTypeMapping: Record<string, { label: string; matchers: string[] }[]> = {
  D: [
    { label: '3-架构记忆', matchers: ['架构', '3-', 'knowledge'] },
    { label: '0-元记忆', matchers: ['元记忆', '0-'] },
  ],
  Z: [
    { label: '5-通用经验', matchers: ['通用经验', '5-', 'experience'] },
    { label: '1-原则记忆', matchers: ['原则', '1-'] },
  ],
  E: [
    { label: '2-方法论记忆', matchers: ['方法论', '2-'] },
    { label: '4-信息记忆单元', matchers: ['信息', '4-', 'observation'] },
  ],
};

function matchTypeCount(typeDist: Record<string, number> | undefined, matchers: string[]): number {
  if (!typeDist) return 0;
  let total = 0;
  for (const [key, count] of Object.entries(typeDist)) {
    if (matchers.some(m => key.includes(m))) {
      total += count;
    }
  }
  return total;
}

export function DZEChainView() {
  const { dzeChains, updateChainStatus } = useMemoryStore();
  // P2: 本地 state 持有 type_distribution（避免依赖 store 的 fetchStats）
  const [typeDist, setTypeDist] = useState<Record<string, number> | null>(null);

  // P2: 挂载时内联 fetch /api/cognitive/stats 获取 type_distribution
  useEffect(() => {
    let cancelled = false;
    fetch('/api/cognitive/stats')
      .then(r => r.ok ? r.json() : null)
      .catch(() => null)
      .then(data => {
        if (cancelled || !data || !data.memory) return;
        const td = data.memory.type_distribution || {};
        setTypeDist(td);
      });
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="space-y-4">
      {/* P2: 分类轴真实记忆数概览 */}
      {typeDist && Object.keys(typeDist).length > 0 && (
        <V3Card title="4-MEMORY 分类轴分布（DZE 概念对齐）" padding="sm">
          <p className="text-[10px] text-slate-500 mb-2">
            从 /api/cognitive/stats 拉取 type_distribution，按 DZE 三链映射展示
          </p>
          <div className="grid grid-cols-3 gap-3">
            {(['D', 'Z', 'E'] as const).map(chain => {
              const colors = chainColors[chain];
              const mapping = chainTypeMapping[chain];
              const total = mapping.reduce((sum, m) => sum + matchTypeCount(typeDist, m.matchers), 0);
              return (
                <div key={chain} className={`p-2 rounded border ${colors.border} ${colors.bg}`}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className={`text-xs font-bold ${colors.text}`}>{chain} 链</span>
                    <span className={`text-sm font-bold ${colors.text}`}>{total}</span>
                  </div>
                  <div className="space-y-0.5">
                    {mapping.map(m => {
                      const count = matchTypeCount(typeDist, m.matchers);
                      return (
                        <div key={m.label} className="flex items-center justify-between text-[10px]">
                          <span className="text-slate-400">{m.label}</span>
                          <span className="text-slate-300">{count}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </V3Card>
      )}

      {dzeChains.map(chain => {
        const colors = chainColors[chain.chain];
        const steps = stepLabels[chain.chain] || [];
        return (
          <V3Card key={chain.chain} className={`border ${colors.border}`} padding="sm">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <V3StatusDot status={chain.status === 'running' ? 'active' : chain.status === 'done' ? 'success' : chain.status === 'error' ? 'error' : 'idle'} size="sm" />
                <span className={`text-sm font-medium ${colors.text}`}>{chain.label}</span>
                {/* P2: 显示该链对应的 4-MEMORY 分类轴真实记忆数 */}
                {typeDist && (
                  <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] ${colors.bg} ${colors.text} border ${colors.border}`}>
                    {chainTypeMapping[chain.chain].reduce((sum, m) => sum + matchTypeCount(typeDist, m.matchers), 0)} VM
                  </span>
                )}
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
