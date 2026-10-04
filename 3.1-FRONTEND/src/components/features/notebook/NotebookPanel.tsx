'use client';

// ============================================================
// NotebookPanel — 笔记本主面板 (3.1 Tailwind 版)
// 整合 StepProgress + StepActionMenu + ActiveDZEChain + TaskCard
// 并与 API 路由同步
// ============================================================

import { useEffect, useState } from 'react';
import StepProgress from './StepProgress';
import StepActionMenu from './StepActionMenu';
import TaskCard from './TaskCard';
import ActiveDZEChain from './ActiveDZEChain';
import ActiveStrategyChain from './ActiveStrategyChain';
import { useNotebookStore } from '@/stores/notebook-store';
import { notebookApi } from '@/lib/v3/api';
import type { NotebookTask, StepAction, NotebookState } from '@/lib/notebook/types';

interface Props {
  onNewTask?: (prompt: string) => void;
}

// S系列策略链意图列表
const STRATEGY_INTENTS = [
  'deep_analysis', 'scenario_sim', 'strategy_verify', 'execute_trade',
  'triple_chain', 'market_query', 'asset_comparison', 'entry_timing',
  'exit_timing', 'risk_analysis', 'position_sizing', 'market_sentiment',
  'trend_analysis', 'technical_signal', 'support_resistance',
  'portfolio_allocation', 'portfolio_rebalance', 'event_analysis',
  'concept_explain', 'strategy_recommendation', 'backtest_help',
  'volatility_analysis', 'macro_analysis', 'dca_strategy',
  'arbitrage_opportunity', 'sector_rotation',
];

function isStrategyTask(task: NotebookTask): boolean {
  return STRATEGY_INTENTS.includes(task.intent) ||
    task.steps.some(s => s.id.startsWith('S'));
}

const TAB_STYLES: Record<string, { active: string; idle: string }> = {
  current: { active: 'bg-indigo-950/40 text-indigo-400', idle: '' },
  history: { active: 'bg-emerald-950/40 text-emerald-400', idle: '' },
};

export default function NotebookPanel({ onNewTask }: Props) {
  const { currentTaskId, tasks, startTask, applyStepAction, syncFromServer, init } = useNotebookStore();
  const [tab, setTab] = useState<'current' | 'history'>('current');
  const [busy, setBusy] = useState(false);
  const [serverState, setServerState] = useState<NotebookState | null>(null);

  useEffect(() => {
    init();
    fetchServer();
  }, [init]);

  async function fetchServer() {
    try {
      const data = await notebookApi.getState();
      if (data) {
        const state = data as unknown as NotebookState;
        setServerState(state);
        syncFromServer(state);
      }
    } catch {
      // 静默失败 — dev 环境服务端可能未启动
    }
  }

  async function handleAction(action: StepAction, targetStep?: number, reason?: string) {
    if (!currentTaskId) return;
    setBusy(true);
    try {
      applyStepAction(currentTaskId, action, targetStep, reason);
      // TODO: migrate to domain client — uses PATCH, but notebookApi.updateStep is POST
      const res = await fetch('/api/notebook/step', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ taskId: currentTaskId, action, targetStep, reason }),
      });
      const data = await res.json();
      if (data.success && data.data?.state) {
        syncFromServer(data.data.state);
      }
    } catch (e) {
      console.warn('Notebook action sync failed:', e);
    } finally {
      setBusy(false);
    }
  }

  async function handleStartNewTask(title: string, prompt: string, intent: string = 'triple_chain') {
    setBusy(true);
    try {
      // TODO: migrate to domain client — POST /api/notebook has no matching notebookApi method
      const res = await fetch('/api/notebook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title,
          userInput: prompt,
          intent,
          sessionId: `sess_${Date.now()}`,
          entities: {},
          routing: null,
        }),
      });
      const data = await res.json();
      if (data.success) {
        syncFromServer(data.data.state);
      } else {
        // 服务端失败时用本地 store 创建
        startTask({
          title,
          userInput: prompt,
          intent,
          sessionId: `sess_${Date.now()}`,
          entities: {},
          routing: null,
        });
      }
    } catch (e) {
      console.warn('Notebook start task failed, using local store:', e);
      startTask({
        title,
        userInput: prompt,
        intent,
        sessionId: `sess_${Date.now()}`,
        entities: {},
        routing: null,
      });
    } finally {
      setBusy(false);
    }
  }

  const currentTask: NotebookTask | null = tasks.find((t: NotebookTask) => t.id === currentTaskId) || null;
  const completedTasks = tasks.filter((t: NotebookTask) => t.phase === 'done');
  const activeTasks = tasks.filter((t: NotebookTask) => t.phase === 'active' && t.id !== currentTaskId);

  return (
    <div className="w-full max-w-2xl bg-slate-950 text-slate-300">
      {/* Header */}
      <div className="px-4 py-3.5 border-b border-slate-800 flex justify-between items-center">
        <div>
          <div className="text-base font-bold text-white">📒 笔记本</div>
          <div className="text-[11px] text-slate-600 mt-0.5">
            {tasks.length} 个任务 · {completedTasks.length} 已完成
            {serverState && ' · 已同步'}
          </div>
        </div>
        <div className="flex gap-1 bg-slate-900 rounded-md p-0.5">
          {(Object.keys(TAB_STYLES) as Array<'current' | 'history'>).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                tab === t ? TAB_STYLES[t].active : 'text-slate-600 hover:text-slate-400'
              }`}
            >
              {t === 'current' ? '当前' : '历史'}
            </button>
          ))}
        </div>
      </div>

      <div className="p-4">
        {tab === 'current' && (
          <>
            {currentTask ? (
              <div>
                {/* Step Progress */}
                <div className="mb-4">
                  <div className="text-xs font-semibold mb-1 text-slate-300">
                    📊 7步进度
                  </div>
                  <StepProgress steps={currentTask.steps} />
                </div>

                {/* 思维链可视化 */}
                <div className="mb-4">
                  <div className="text-xs font-semibold mb-2 text-slate-300">
                    {isStrategyTask(currentTask) ? '🎯 策略思维链' : '🔗 D-Z-E 思维链'}
                  </div>
                  {isStrategyTask(currentTask) ? (
                    <ActiveStrategyChain
                      chain={currentTask.strategyChain || null}
                      onStepClick={(stepId) => console.log('Step clicked:', stepId)}
                    />
                  ) : (
                    <ActiveDZEChain chain={currentTask.dzeChain} />
                  )}
                </div>

                {/* 当前步骤内容 */}
                <ActiveStepContent task={currentTask} onUpdate={() => fetchServer()} />

                {/* 决策菜单 */}
                <StepActionMenu
                  taskId={currentTask.id}
                  onAction={handleAction}
                  totalSteps={currentTask.steps.length}
                  disabled={busy}
                />
              </div>
            ) : (
              <div className="text-center py-5">
                <div className="text-[13px] text-slate-500 mb-3">
                  暂无活跃任务 · 在上方对话中提出需求会自动创建
                </div>
                <button
                  onClick={() => handleStartNewTask('黄金交易策略', '为我制定黄金交易策略', 'triple_chain')}
                  disabled={busy}
                  className={`px-4 py-2.5 rounded-md text-xs font-semibold text-white transition-colors ${
                    busy ? 'bg-slate-800 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-500 cursor-pointer'
                  }`}
                >
                  🚀 试试：制定黄金交易策略
                </button>
              </div>
            )}
          </>
        )}

        {tab === 'history' && (
          <div>
            {tasks.length === 0 ? (
              <div className="text-xs text-slate-600 text-center py-5">
                暂无历史任务
              </div>
            ) : (
              <>
                {completedTasks.length > 0 && (
                  <div className="mb-4">
                    <div className="text-[11px] text-emerald-400 mb-2 font-semibold">
                      ✅ 已完成 ({completedTasks.length})
                    </div>
                    {completedTasks.slice(0, 5).map((t: NotebookTask) => (
                      <TaskCard key={t.id} task={t} />
                    ))}
                  </div>
                )}

                {activeTasks.length > 0 && (
                  <div className="mb-4">
                    <div className="text-[11px] text-indigo-400 mb-2 font-semibold">
                      ▶ 其他活跃 ({activeTasks.length})
                    </div>
                    {activeTasks.slice(0, 5).map((t: NotebookTask) => (
                      <TaskCard key={t.id} task={t} />
                    ))}
                  </div>
                )}

                <div className="text-[11px] text-slate-500 mb-2 font-semibold">
                  📋 全部任务 ({tasks.length})
                </div>
                {tasks.slice(0, 20).map((t) => (
                  <TaskCard
                    key={t.id}
                    task={t}
                    isCurrent={t.id === currentTaskId}
                    onClick={() => {
                      useNotebookStore.setState({ currentTaskId: t.id });
                      setTab('current');
                    }}
                  />
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Bottom note */}
      <div className="p-3 text-[10px] text-slate-600 border-t border-slate-800 text-center">
        Notebook v3.1 · 解决上下文压缩 & 工作漂移问题
      </div>
    </div>
  );
}

// ============================================================
// ActiveStepContent — 当前活跃步骤的内容展示
// ============================================================

function ActiveStepContent({
  task,
  onUpdate,
}: {
  task: NotebookTask;
  onUpdate: () => void;
}) {
  const [output, setOutput] = useState('');

  const activeStep = task.steps.find((s) => s.status === 'active');
  const lastCompleted = [...task.steps].reverse().find((s) => s.status === 'done');

  useEffect(() => {
    if (activeStep) {
      setOutput(activeStep.output || defaultOutput(activeStep.number, task));
    } else {
      setOutput('');
    }
  }, [activeStep?.id, task.id]);

  if (!activeStep) {
    return (
      <div className="mb-4 p-3 bg-emerald-950/30 border border-emerald-800 rounded-md">
        <div className="text-xs text-emerald-400 font-semibold">
          ✅ 全部步骤完成
        </div>
      </div>
    );
  }

  return (
    <div className="mb-4">
      <div className="text-xs font-semibold mb-2 text-indigo-400">
        {activeStep.icon} Step {activeStep.number} {activeStep.name} · 当前活跃
      </div>

      {/* 前一步的产出 */}
      {lastCompleted && lastCompleted.number < activeStep.number && lastCompleted.output && (
        <div className="p-2.5 bg-emerald-950/20 border-l-2 border-emerald-700 rounded mb-2.5 text-[11px] text-slate-400 leading-relaxed">
          <div className="text-emerald-400 font-semibold mb-1">
            Step {lastCompleted.number} 产出:
          </div>
          <div className="whitespace-pre-wrap">{lastCompleted.output.slice(0, 500)}{lastCompleted.output.length > 500 ? '...' : ''}</div>
        </div>
      )}

      {/* 自动生成的当前步建议 */}
      <div className="p-3 bg-indigo-950/20 border-l-2 border-indigo-600 rounded mb-2.5 text-[11px] text-slate-300 leading-relaxed">
        <div className="text-indigo-400 font-semibold mb-1.5">
          ✨ 本步建议产出
        </div>
        <div className="whitespace-pre-wrap">{output}</div>
      </div>

      <textarea
        value={output}
        onChange={(e) => setOutput(e.target.value)}
        placeholder="在下方编辑此步骤的产出内容..."
        className="w-full min-h-[60px] p-2.5 bg-slate-900 border border-slate-700 rounded text-slate-300 text-[11px] resize-y leading-relaxed focus:outline-none focus:border-indigo-600"
      />
    </div>
  );
}

// ============================================================
// defaultOutput — 默认输出内容生成
// ============================================================

function defaultOutput(stepNumber: number, task: NotebookTask): string {
  const intent = task.intent;
  const entity = task.entities.symbol || '标的';

  switch (stepNumber) {
    case 2:
      return `根据需求 "${task.title}"，建议通过 S 系列策略思维链展开：

🎯 S1 调研 — 市场数据收集
  - ${entity} 宏观行情与资金流向分析
  - ${entity} 技术结构与关键位识别
  - 多情景推演与压力测试

🧠 S2 分析 — 多维度分析
  - 第一性原理分析框架
  - 支撑/阻力位识别
  - 趋势判断与动量分析

📐 S3 设计 — 策略方案制定
  - 策略方向选择（突破/趋势/均值回归）
  - 时间框架与入场时机
  - 风险控制与仓位管理

✅ S4 验证 — 回测风险评估
  - 历史回测与参数优化
  - 风险评估与最大回撤
  - 策略稳定性验证

⚡ S5 执行 — 执行计划跟踪
  - 执行步骤分解
  - 实时监控与调整
  - 复盘总结与迭代

↓ 继续下一步，进入 S1 调研`;

    case 3:
      return `知识库检索建议：
  - 从 ${entity} 的历史数据中提取 1-3 篇最相关文档
  - 结合知识库中的策略模板与 ${entity} 最新行情
  - 补充回测结果，形成知识 + 数据双驱动`;

    case 4:
      return `方法论借鉴：
  - 参考 A 系列方法论（已集成到智能路由）
  - 基于 "调研 → 分析 → 推演 → 规格" 四步流程
  - 当前意图: ${intent}`;

    case 5:
      return `索引更新：
  - 策略文档保存到 0-NOTEBOOK/
  - 更新知识库索引
  - 记录关键指标与参数`;

    case 6:
      return `协作归档：
  - 策略规格已写入 Markdown
  - 飞书 Base / Wiki 同步建议
  - 供团队其他成员复用`;

    case 7:
      return `记忆蒸馏：
  - 本次任务的关键发现
  - 可复用的方法论片段
  - 未来改进建议`;

    default:
      return '';
  }
}
