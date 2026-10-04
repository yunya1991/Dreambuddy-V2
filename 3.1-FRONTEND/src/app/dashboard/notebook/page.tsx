'use client';

// ============================================================
// /dashboard/notebook — 笔记本页面 (3.1 版)
// 渲染 NotebookPanel, 提供 mock 数据 fallback
// ============================================================

import { useEffect } from 'react';
import NotebookPanel from '@/components/features/notebook/NotebookPanel';
import { ArtifactGallery } from '@/components/features/notebook/ArtifactGallery';
import { useNotebookStore } from '@/stores/notebook-store';
import { STEP_DEFINITIONS } from '@/lib/notebook/types';
import type { NotebookTask } from '@/lib/notebook/types';

function nowISO(): string {
  return new Date().toISOString();
}

// Mock 任务: 当服务端无数据时用于前端展示
function createMockTask(title: string, intent: string, entity: string, activeStep: number): NotebookTask {
  const steps = STEP_DEFINITIONS.map((def, idx) => ({
    id: def.id,
    number: def.number,
    name: def.name,
    icon: def.icon,
    status: idx < activeStep ? 'done' as const : idx === activeStep ? 'active' as const : 'pending' as const,
    output: idx < activeStep ? `Step ${def.number} ${def.name} 已完成` : '',
    artifacts: [],
    notes: '',
    startedAt: idx <= activeStep ? nowISO() : undefined,
    completedAt: idx < activeStep ? nowISO() : undefined,
  }));

  return {
    id: `mock_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    sessionId: `mock_sess_${Date.now()}`,
    title,
    intent,
    userInput: title,
    phase: 'active',
    startedAt: nowISO(),
    lastActiveAt: nowISO(),
    steps,
    dzeChain: null,
    strategyChain: null,
    routing: { chain: ['deep_analysis'], thinkingMode: 'deep' },
    entities: { symbol: entity },
    credits: { estimated: 20, used: 0 },
  };
}

export default function NotebookPage() {
  const { tasks, currentTaskId, init, startTask } = useNotebookStore();

  useEffect(() => {
    init();
    // 如果没有任务, 创建 mock 数据用于展示
    if (tasks.length === 0) {
      // 延迟创建 mock, 等 init 完成
      const timer = setTimeout(() => {
        const store = useNotebookStore.getState();
        if (store.tasks.length === 0) {
          startTask({
            title: '黄金交易策略',
            userInput: '为我制定黄金交易策略',
            intent: 'triple_chain',
            sessionId: `mock_sess_${Date.now()}`,
            entities: { symbol: 'XAU' },
            routing: { chain: ['deep_analysis', 'strategy_verify'], thinkingMode: 'deep' },
          });
        }
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [init, tasks.length, startTask]);

  return (
    <div className="min-h-screen bg-[var(--color-bg-primary)] p-6">
      <div className="max-w-2xl mx-auto">
        <div className="mb-4">
          <h1 className="text-xl font-bold text-slate-200">📒 笔记本</h1>
          <p className="text-sm text-slate-500 mt-1">
            7步工作流管理面板 · 解决上下文压缩与工作漂移
          </p>
        </div>
        <NotebookPanel />
        {/* F7.5: 产物中台展示 */}
        <div className="mt-6">
          <ArtifactGallery />
        </div>
      </div>
    </div>
  );
}
