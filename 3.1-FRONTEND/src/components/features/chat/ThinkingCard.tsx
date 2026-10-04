'use client';

import React, { useState, useMemo } from 'react';
import { useChainStore, type ChainTraceNode } from '@/stores';

// S 链节点图标
const STEP_ICONS: Record<string, string> = {
  S1_RESEARCH: '🔍',
  S2_ANALYSIS: '🧠',
  S3_DESIGN: '📐',
  S4_VALIDATE: '✅',
  S5_EXECUTE: '⚡',
  S0_DIRECT_ANSWER: '💬',
};

const STAGE_ICONS: Record<string, string> = {
  research: '🔍',
  analysis: '🧠',
  design: '📐',
  validate: '✅',
  execute: '⚡',
};

const STAGE_LABELS: Record<string, string> = {
  research: '调研',
  analysis: '分析',
  design: '设计',
  validate: '验证',
  execute: '执行',
};

function getSkillIcon(skillId: string): string {
  if (skillId.startsWith('dream-')) return '🤖';
  if (skillId.startsWith('Regime') || skillId.startsWith('Classic')) return '📊';
  if (skillId.includes('fundamental') || skillId.includes('news')) return '📰';
  if (skillId.includes('risk')) return '🛡️';
  if (skillId.includes('execute') || skillId.includes('order')) return '🎯';
  return '⚙️';
}

function resolveNodeIcon(node: ChainTraceNode): string {
  if (node.icon) return node.icon;
  if (node.stage && STAGE_ICONS[node.stage]) return STAGE_ICONS[node.stage];
  if (STEP_ICONS[node.id]) return STEP_ICONS[node.id];
  if (node.is_skill) return getSkillIcon(node.id);
  return '⚙️';
}

interface ThinkingCardProps {
  isStreaming?: boolean;
}

/**
 * ThinkingCard — 对话内嵌思考链卡片
 *
 * 在 AI 回复顶部展示 S0-S5 / research→execute 思维链执行过程。
 * - 流式中：从 chain-store.steps 渲染实时进度
 * - 完成后：从 chain-store.chainTrace 渲染完整执行轨迹
 */
export function ThinkingCard({ isStreaming }: ThinkingCardProps) {
  const { steps, chainTrace, qualityScore } = useChainStore();
  const [expanded, setExpanded] = useState(false);

  // 从 chainTrace 或 steps 构建节点列表
  const aNodes = useMemo<ChainTraceNode[]>(() => {
    if (chainTrace?.nodes) {
      return chainTrace.nodes.filter(n => n.layer === 'A' || n.layer === 'a');
    }
    // 从 steps 构建
    return steps.map(s => ({
      id: s.id,
      name: s.name || s.id,
      layer: s.layer,
      status: s.status === 'running' ? 'active' : s.status === 'done' ? 'done' : s.status === 'skipped' ? 'skipped' : s.status === 'failed' ? 'failed' : 'pending',
      confidence: undefined,
      tokens_used: s.tokens,
      latency_ms: s.latencyMs,
    }));
  }, [chainTrace, steps]);

  const hasStages = aNodes.some(n => n.stage);
  const stageOrder = ['research', 'analysis', 'design', 'validate', 'execute'];

  // 按阶段分组 — 必须在 early return 之前调用（React hooks 规则）
  const grouped = useMemo(() => {
    if (!hasStages) return null;
    const map = new Map<string, ChainTraceNode[]>();
    for (const node of aNodes) {
      const key = node.stage || 'other';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(node);
    }
    return [...stageOrder.filter(s => map.has(s)), ...[...map.keys()].filter(s => !stageOrder.includes(s))].map(s => ({ stage: s, nodes: map.get(s) || [] }));
  }, [aNodes, hasStages]);

  if (aNodes.length === 0 && !isStreaming) return null;

  const totalSteps = aNodes.length || 5;
  const doneSteps = aNodes.filter(n => n.status === 'done').length;
  const progress = isStreaming
    ? totalSteps > 0 ? (doneSteps / totalSteps) * 100 : 30
    : 100;

  return (
    <div className="mb-2 rounded-xl bg-slate-900/60 border border-slate-700/30 overflow-hidden">
      {/* 头部（折叠态也可见） */}
      <div
        onClick={() => setExpanded(!expanded)}
        className="px-3 py-2.5 cursor-pointer flex items-center justify-between gap-2 select-none hover:bg-slate-800/30 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm">🧠</span>
          <span className="text-xs font-semibold text-slate-300">
            {isStreaming ? '思考中...' : '思考过程'}
          </span>
          {chainTrace?.intent && (
            <span className="text-[10px] text-blue-400">
              · {chainTrace.intent.type}
            </span>
          )}
          {chainTrace?.final?.grade && !isStreaming && (
            <span className={`text-[10px] font-semibold ${
              chainTrace.final.grade === 'excellent' ? 'text-green-400' :
              chainTrace.final.grade === 'good' ? 'text-emerald-400' :
              'text-amber-400'
            }`}>
              · {chainTrace.final.grade}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* 节点 icon 流 */}
          <div className="flex items-center gap-0.5">
            {aNodes.length > 0 ? (
              aNodes.slice(0, 8).map((node, idx) => (
                <span
                  key={`${idx}-${node.id}`}
                  className={`text-xs transition-opacity`}
                  style={{ opacity: node.status === 'done' || node.status === 'active' ? 1 : 0.3 }}
                  title={node.name}
                >
                  {resolveNodeIcon(node)}
                </span>
              ))
            ) : isStreaming ? (
              <span className="text-xs animate-pulse">🔄</span>
            ) : null}
          </div>
          <span className={`text-[10px] text-slate-500 transition-transform ${expanded ? 'rotate-180' : ''}`}>▼</span>
        </div>
      </div>

      {/* 进度条 */}
      <div className="h-0.5 bg-slate-800">
        <div
          className={`h-full transition-all duration-400 ${isStreaming ? 'bg-blue-500' : 'bg-green-500'}`}
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* 展开详情 */}
      {expanded && (
        <div className="px-3 py-3 border-t border-slate-700/30 text-xs space-y-3">
          {/* 意图 & 链路信息 */}
          {chainTrace?.intent && (
            <div className="grid grid-cols-2 gap-2">
              <div>
                <span className="text-slate-500">意图: </span>
                <span className="text-blue-400 font-semibold">{chainTrace.intent.type}</span>
              </div>
              <div>
                <span className="text-slate-500">置信度: </span>
                <span className="text-green-400 font-semibold">
                  {(chainTrace.intent.confidence * 100).toFixed(0)}%
                </span>
              </div>
              {chainTrace.plan && (
                <div>
                  <span className="text-slate-500">模式: </span>
                  <span className="text-slate-300">{chainTrace.plan.complexity}</span>
                </div>
              )}
              {chainTrace.final && (
                <div>
                  <span className="text-slate-500">质量: </span>
                  <span className="text-green-400 font-semibold">
                    {(chainTrace.final.quality_score * 100).toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          )}

          {/* A 层节点详情 */}
          {aNodes.length > 0 && (
            <div>
              <div className="text-slate-500 mb-1.5 font-semibold">执行节点</div>
              {grouped ? (
                <div className="flex flex-col gap-1.5">
                  {grouped.map(({ stage, nodes }) => {
                    const stageNode = nodes.find(n => !n.is_skill);
                    const skillNodes = nodes.filter(n => n.is_skill);
                    const stageIcon = stageNode?.icon || STAGE_ICONS[stage] || '⚙️';
                    const stageLabel = stageNode?.name || STAGE_LABELS[stage] || stage;
                    const stageStatus = stageNode?.status || 'done';

                    return (
                      <div key={stage}>
                        <div className={`flex items-center gap-2 px-2 py-1 rounded ${
                          stageStatus === 'done' ? 'bg-green-950/20' :
                          stageStatus === 'active' ? 'bg-blue-950/20' : ''
                        }`}>
                          <span className="text-xs">
                            {stageStatus === 'done' ? '✓' : stageStatus === 'active' ? '▶' : '○'}
                          </span>
                          <span className="text-xs">{stageIcon}</span>
                          <span className="text-xs text-slate-300 font-semibold flex-1">{stageLabel}</span>
                          {stageNode?.confidence !== undefined && (
                            <span className="text-[10px] text-green-400">
                              {(stageNode.confidence * 100).toFixed(0)}%
                            </span>
                          )}
                        </div>
                        {skillNodes.length > 0 && (
                          <div className="ml-6 mt-0.5 flex flex-col gap-0.5">
                            {skillNodes.map(node => (
                              <NodeRowItem key={node.id} node={node} compact />
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="flex flex-col gap-1">
                  {aNodes.map(node => (
                    <NodeRowItem key={node.id} node={node} />
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 自省结果 */}
          {chainTrace?.final && (
            <div className="px-2 py-2 rounded-lg bg-slate-950/40 border border-slate-700/20">
              <div className="text-slate-500 mb-1 font-semibold">🧠 自省结果</div>
              <div className="flex gap-4">
                <div>
                  <span className="text-slate-500">质量: </span>
                  <span className="text-green-400 font-semibold">
                    {(chainTrace.final.quality_score * 100).toFixed(0)}%
                  </span>
                </div>
                <div>
                  <span className="text-slate-500">风险: </span>
                  <span className={`font-semibold ${
                    chainTrace.final.risk_score > 0.5 ? 'text-red-400' : 'text-amber-400'
                  }`}>
                    {(chainTrace.final.risk_score * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 单个节点行 ──
function NodeRowItem({ node, compact = false }: { node: ChainTraceNode; compact?: boolean }) {
  return (
    <div className={`flex items-center gap-2 rounded ${
      compact ? 'px-2 py-0.5' : 'px-2 py-1'
    } ${
      node.status === 'done' ? 'bg-green-950/20' :
      node.status === 'active' ? 'bg-blue-950/20' : ''
    }`}>
      <span className={compact ? 'text-[11px]' : 'text-xs'}>
        {node.status === 'done' ? '✓' : node.status === 'active' ? '▶' : '○'}
      </span>
      <span className={compact ? 'text-[11px]' : 'text-xs'}>{resolveNodeIcon(node)}</span>
      <span className={`${compact ? 'text-[11px]' : 'text-xs'} text-slate-400 flex-1`}>{node.name}</span>
      {node.confidence !== undefined && (
        <span className="text-[10px] text-green-400">
          {(node.confidence * 100).toFixed(0)}%
        </span>
      )}
      {node.tokens_used !== undefined && node.tokens_used > 0 && (
        <span className="text-[9px] text-slate-600">{node.tokens_used.toLocaleString()}t</span>
      )}
    </div>
  );
}

export default ThinkingCard;
