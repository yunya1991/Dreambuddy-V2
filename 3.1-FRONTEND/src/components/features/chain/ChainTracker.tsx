'use client';

import React from 'react';
import { useChainStore } from '@/stores';
import type { ChainStep, ChainTraceNode } from '@/stores';
import { V3Badge, V3StatusDot, V3Empty } from '@/components';

// SACG 层颜色映射
const layerColors: Record<string, string> = {
  S: 'border-l-purple-500',
  A: 'border-l-blue-500',
  C: 'border-l-emerald-500',
  G: 'border-l-amber-500',
  B: 'border-l-indigo-500',
};

// 步骤状态颜色
const stepStatusColors: Record<string, string> = {
  pending: 'text-slate-500',
  running: 'text-blue-400',
  active: 'text-blue-400',
  done: 'text-emerald-400',
  failed: 'text-red-400',
  error: 'text-red-400',
  skipped: 'text-slate-600',
  idle: 'text-slate-600',
};

// 步骤状态指示
const stepStatusDot: Record<string, 'idle' | 'active' | 'success' | 'error' | 'loading'> = {
  pending: 'idle',
  running: 'active',
  active: 'active',
  done: 'success',
  failed: 'error',
  error: 'error',
  skipped: 'idle',
  idle: 'idle',
};

// Reflector 决策颜色
const reflectorColors: Record<string, string> = {
  CONTINUE: 'info',
  REDO: 'warning',
  INSERT_BEFORE: 'info',
  JUMP_TO: 'warning',
  EARLY_TERMINATE: 'danger',
  SKIP: 'default',
  proceed: 'info',
};

const chainTypeLabels: Record<string, string> = {
  research: '研究链',
  trading: '交易链',
  fundamental: '基本面链',
  risk: '风控链',
  custom: '自定义链',
};

export function ChainTracker() {
  const {
    activeChain, chainId, steps, currentStepIndex,
    reflectorHistory, artifacts, chainTrace, qualityScore,
  } = useChainStore();

  // 如果有 chain_trace (来自后端真实数据),优先渲染
  if (chainTrace && chainTrace.nodes.length > 0) {
    return <ChainTraceView trace={chainTrace} qualityScore={qualityScore} artifacts={artifacts} />;
  }

  // 没有链路数据时的空状态
  if (!activeChain) {
    return (
      <V3Empty title="暂无活跃链路" description="发起对话后可查看执行链路追踪" />
    );
  }

  const chainColor = layerColors[activeChain] || 'border-l-slate-500';

  return (
    <div className="space-y-3">
      {/* 链信息头 */}
      <div className={`border-l-2 ${chainColor} pl-3 py-2 bg-slate-900/40 rounded-r-lg`}>
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-slate-200">
                {chainTypeLabels[activeChain] || activeChain}
              </span>
              <V3Badge variant="sacg-s" dot pulse>
                {activeChain}
              </V3Badge>
            </div>
            {chainId && (
              <p className="text-xs text-slate-500 mt-0.5">
                ID: {chainId.slice(0, 8)}...
              </p>
            )}
          </div>
          <V3Badge variant="info">
            {steps.filter(s => s.status === 'done').length}/{steps.length}
          </V3Badge>
        </div>
      </div>

      {/* 步骤列表 */}
      <div className="space-y-1.5">
        {steps.map((step, index) => (
          <ChainStepRow key={step.id} step={step} isActive={index === currentStepIndex} />
        ))}
      </div>

      {/* Reflector 决策 */}
      {reflectorHistory.length > 0 && (
        <div className="mt-3 pt-3 border-t border-slate-700/30">
          <h4 className="text-xs font-semibold text-slate-400 mb-2">Reflector 决策</h4>
          <div className="space-y-1.5">
            {reflectorHistory.slice(0, 5).map((rd, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="text-slate-500 w-16 truncate">{rd.stepId}</span>
                <V3Badge variant={reflectorColors[rd.action] || 'default'}>
                  {rd.action}
                </V3Badge>
                <span className="text-slate-400 truncate flex-1">{rd.reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 产物 */}
      {artifacts.length > 0 && (
        <div className="mt-3 pt-3 border-t border-slate-700/30">
          <h4 className="text-xs font-semibold text-slate-400 mb-2">链产物 ({artifacts.length})</h4>
          <div className="space-y-1">
            {artifacts.map((a) => (
              <div key={a.id} className="flex items-center gap-2 text-xs text-slate-300 px-2 py-1 rounded bg-slate-800/30">
                <span className="text-slate-500">[{a.type}]</span>
                <span className="truncate">{a.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// === chain_trace 真实数据视图 ===
function ChainTraceView({ trace, qualityScore, artifacts }: {
  trace: NonNullable<ReturnType<typeof useChainStore.getState>['chainTrace']>;
  qualityScore: number | null;
  artifacts: Array<{ id: string; type: string; title: string; createdAt: number }>;
}) {
  const totalTokens = trace.nodes.reduce((sum, n) => sum + (n.tokens_used || 0), 0);
  const completedNodes = trace.nodes.filter(n => n.status === 'done').length;

  return (
    <div className="space-y-3">
      {/* 计划信息 */}
      {trace.plan && (
        <div className="border-l-2 border-l-blue-500 pl-3 py-2 bg-slate-900/40 rounded-r-lg">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-200">编排链路</span>
                <V3Badge variant="sacg-a" dot>{trace.plan.chain_id}</V3Badge>
              </div>
              <p className="text-[10px] text-slate-500 mt-0.5 truncate">
                {trace.plan.chain_name}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {qualityScore !== null && (
                <V3Badge variant={qualityScore >= 0.7 ? 'success' : 'warning'}>
                  质量 {(qualityScore * 100).toFixed(0)}%
                </V3Badge>
              )}
              <V3Badge variant="info">
                {completedNodes}/{trace.nodes.length}
              </V3Badge>
            </div>
          </div>
          {trace.plan.complexity && (
            <div className="mt-1.5 flex items-center gap-2 text-[10px] text-slate-500">
              <span>复杂度: {trace.plan.complexity}</span>
              <span>·</span>
              <span>预算: {trace.plan.total_budget} tok</span>
              <span>·</span>
              <span>实际: {totalTokens} tok</span>
            </div>
          )}
        </div>
      )}

      {/* 意图信息 */}
      {trace.intent && (
        <div className="px-3 py-2 bg-purple-950/20 border border-purple-800/20 rounded-lg">
          <div className="flex items-center gap-2">
            <V3Badge variant="sacg-s" dot>S 层</V3Badge>
            <span className="text-xs font-medium text-slate-200">意图: {trace.intent.type}</span>
            <span className="text-[10px] text-slate-500">
              置信度 {(trace.intent.confidence * 100).toFixed(0)}%
            </span>
            <span className="text-[10px] text-slate-600">({trace.intent.method})</span>
          </div>
        </div>
      )}

      {/* 节点列表 */}
      <div className="space-y-1">
        {trace.nodes.map((node, index) => (
          <ChainNodeRow key={`${node.id}-${index}`} node={node} />
        ))}
      </div>

      {/* 最终评估 */}
      {trace.final && (
        <div className="mt-3 pt-3 border-t border-slate-700/30">
          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-slate-800/30 rounded-lg p-2">
              <p className="text-[10px] text-slate-500">质量评分</p>
              <p className={`text-sm font-bold ${(trace.final.quality_score || 0) >= 0.7 ? 'text-emerald-400' : 'text-amber-400'}`}>
                {((trace.final.quality_score || 0) * 100).toFixed(0)}
              </p>
            </div>
            <div className="bg-slate-800/30 rounded-lg p-2">
              <p className="text-[10px] text-slate-500">风险评分</p>
              <p className={`text-sm font-bold ${(trace.final.risk_score || 0) >= 0.5 ? 'text-red-400' : 'text-emerald-400'}`}>
                {((trace.final.risk_score || 0) * 100).toFixed(0)}
              </p>
            </div>
            <div className="bg-slate-800/30 rounded-lg p-2">
              <p className="text-[10px] text-slate-500">评级</p>
              <p className="text-sm font-bold text-blue-400">{trace.final.grade || '-'}</p>
            </div>
          </div>
        </div>
      )}

      {/* 产物 */}
      {artifacts.length > 0 && (
        <div className="mt-3 pt-3 border-t border-slate-700/30">
          <h4 className="text-xs font-semibold text-slate-400 mb-2">链产物 ({artifacts.length})</h4>
          <div className="space-y-1">
            {artifacts.map((a) => (
              <div key={a.id} className="flex items-center gap-2 text-xs text-slate-300 px-2 py-1 rounded bg-slate-800/30">
                <span className="text-slate-500">[{a.type}]</span>
                <span className="truncate">{a.title}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// === chain_trace 节点行 ===
function ChainNodeRow({ node }: { node: ChainTraceNode }) {
  const layerColor = layerColors[node.layer] || 'border-l-slate-500';
  const isSkill = node.is_skill;
  const statusKey = node.status || 'idle';

  return (
    <div className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg bg-slate-800/20 border-l-2 ${layerColor} ${isSkill ? 'ml-3' : ''}`}>
      <V3StatusDot status={stepStatusDot[statusKey] || 'idle'} size="sm" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          {node.icon && <span className="text-xs">{node.icon}</span>}
          <span className={`text-xs font-medium truncate ${stepStatusColors[statusKey] || 'text-slate-400'}`}>
            {node.name}
          </span>
          {isSkill && (
            <V3Badge variant="default" className="text-[9px]">SKILL</V3Badge>
          )}
          {node.chain && (
            <span className="text-[9px] text-slate-600 uppercase">{node.chain}链</span>
          )}
        </div>
        {node.reflect_action && node.reflect_action !== 'proceed' && (
          <p className="text-[10px] text-amber-400/70 mt-0.5">
            ⚡ {node.reflect_action}
          </p>
        )}
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        {node.confidence !== undefined && node.confidence > 0 && (
          <span className="text-[9px] text-slate-500">{(node.confidence * 100).toFixed(0)}%</span>
        )}
        {node.tokens_used !== undefined && node.tokens_used > 0 && (
          <span className="text-[9px] text-slate-500">{node.tokens_used}tok</span>
        )}
        {node.latency_ms !== undefined && node.latency_ms > 0 && (
          <span className="text-[9px] text-slate-500">{node.latency_ms}ms</span>
        )}
      </div>
    </div>
  );
}

// 单步骤行 (用于 live progress)
function ChainStepRow({ step, isActive }: { step: ChainStep; isActive: boolean }) {
  return (
    <div className={`
      flex items-center gap-2.5 px-3 py-2 rounded-lg transition-colors
      ${isActive ? 'bg-blue-500/10 border border-blue-500/20' : 'bg-slate-800/20 border border-transparent hover:bg-slate-800/40'}
    `}>
      <V3StatusDot status={stepStatusDot[step.status] || 'idle'} size="sm" pulse={isActive} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-medium truncate ${stepStatusColors[step.status] || 'text-slate-400'}`}>
            {step.name}
          </span>
          {step.reflectorDecision && (
            <V3Badge variant={reflectorColors[step.reflectorDecision] || 'default'} className="text-[10px]">
              {step.reflectorDecision}
            </V3Badge>
          )}
        </div>
        {step.reflectorReason && (
          <p className="text-[10px] text-slate-500 mt-0.5 truncate">{step.reflectorReason}</p>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {step.tokens && (
          <span className="text-[10px] text-slate-500">{step.tokens}tok</span>
        )}
        {step.latencyMs && (
          <span className="text-[10px] text-slate-500">{step.latencyMs}ms</span>
        )}
      </div>
    </div>
  );
}

export default ChainTracker;
