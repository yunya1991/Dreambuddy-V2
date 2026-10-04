'use client';

import { WorkflowCard } from '@/components/features/workflow/WorkflowCard';
import type { WorkflowType } from '@/components/features/workflow/WorkflowCard';
import type { WorkflowStep } from '@/components/features/workflow/WorkflowStepList';
import OrchestrationPanel from '@/components/features/orchestration/OrchestrationPanel';
import { useChainStore } from '@/stores/chain-store';

// ── Mock 工作流数据 ──────────────────────────────────

interface MockWorkflow {
  workflowId: string;
  workflowType: WorkflowType;
  title: string;
  executionStatus: string;
  steps: WorkflowStep[];
  startedAt: string;
  finishedAt?: string;
}

const MOCK_WORKFLOWS: MockWorkflow[] = [
  {
    workflowId: 'wf_legacy_001',
    workflowType: 'legacy_chain',
    title: 'BTC 多周期分析链路',
    executionStatus: 'delivered',
    steps: [
      { id: 'a1', label: 'A1 感知 Feed', status: 'success', description: 'K线 + 指标聚合' },
      { id: 'a2', label: 'A2 基本面注入', status: 'success', description: 'MVRV + 净流入' },
      { id: 'a3', label: 'A3 策略基因匹配', status: 'success', description: 'Trend_Set 匹配' },
      { id: 'a5', label: 'A5 风控评估', status: 'success', description: 'ATR 止损 2%' },
      { id: 'a9', label: 'A9 执行交付', status: 'success', description: '标准仓位 0.7' },
    ],
    startedAt: new Date(Date.now() - 3600_000).toISOString(),
    finishedAt: new Date(Date.now() - 3500_000).toISOString(),
  },
  {
    workflowId: 'wf_trading_v2_002',
    workflowType: 'trading_v2',
    title: 'ETH 事件驱动交易',
    executionStatus: 'in_progress',
    steps: [
      { id: 'intel', label: '情报采集', status: 'success', description: '新闻 + 链上异动' },
      { id: 'research', label: '深度研究', status: 'success', description: '矛盾驱动分析' },
      { id: 'strategy', label: '策略构建', status: 'running', description: '小单试探中' },
      { id: 'risk', label: '风控审核', status: 'pending' },
      { id: 'execute', label: '执行交付', status: 'pending' },
    ],
    startedAt: new Date(Date.now() - 600_000).toISOString(),
  },
  {
    workflowId: 'wf_legacy_003',
    workflowType: 'legacy_chain',
    title: 'SOL 区间震荡扫描',
    executionStatus: 'failed',
    steps: [
      { id: 'a1', label: 'A1 感知 Feed', status: 'success' },
      { id: 'a2', label: 'A2 基本面注入', status: 'skipped', description: '数据源超时' },
      { id: 'a3', label: 'A3 策略基因匹配', status: 'error', description: '无匹配组合' },
    ],
    startedAt: new Date(Date.now() - 7200_000).toISOString(),
    finishedAt: new Date(Date.now() - 7150_000).toISOString(),
  },
];

export default function WorkflowPage() {
  const chainTrace = useChainStore((s) => s.chainTrace);

  return (
    <div className="px-6 py-4">
      <h1 className="text-xl font-bold text-white mb-1">工作流 / 编排可视化</h1>
      <p className="text-xs text-slate-400 mb-4">
        查看工作流执行链路与 SACG 三层编排追踪
      </p>

      {/* ── 工作流卡片列表 ── */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-slate-300 mb-3">工作流列表</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {MOCK_WORKFLOWS.map((wf) => (
            <WorkflowCard
              key={wf.workflowId}
              workflowId={wf.workflowId}
              workflowType={wf.workflowType}
              title={wf.title}
              executionStatus={wf.executionStatus}
              steps={wf.steps}
              startedAt={wf.startedAt}
              finishedAt={wf.finishedAt}
            />
          ))}
        </div>
      </section>

      {/* ── 编排追踪面板 ── */}
      <section>
        <h2 className="text-sm font-semibold text-slate-300 mb-3">编排追踪</h2>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 max-w-2xl">
          <OrchestrationPanel trace={chainTrace} />
        </div>
      </section>
    </div>
  );
}
