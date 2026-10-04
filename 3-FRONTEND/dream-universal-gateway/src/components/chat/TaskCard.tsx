"use client";

// ============================================================
// TaskCard — 对话内任务卡片
// 统一渲染：意图 → 决策链 DAG → 执行摘要 → 产物列表
// 组合 ThinkingCard（chain_trace DAG）+ 摘要/产物区
// 版本: v1.0 | 日期: 2026-09-23
// ============================================================

import { useState } from "react";
import type { ChainTrace } from "@/types";
import ThinkingCard from "./ThinkingCard";

interface StreamProgress {
  isStreaming: boolean;
  currentStep: string | null;
  currentSkill: string | null;
  planSteps: Array<{
    stepId: string;
    stage: string;
    chain: string;
    label?: string;
    status: 'pending' | 'active' | 'done' | 'skipped';
  }>;
  skillStatuses: Record<string, {
    status: 'pending' | 'active' | 'done';
    confidence?: number;
    latencyMs?: number;
  }>;
  contentAccumulated: string;
}

interface Artifact {
  file: string;
  type: string;
  chain_phase: string;
}

interface Props {
  trace?: ChainTrace | null;
  isLoading?: boolean;
  streamProgress?: StreamProgress | null;
  executionTimeMs?: number;
  executionSummary?: Record<string, unknown> | null;
  artifacts?: Artifact[];
  taskId?: string;
  intent?: string;
  confidence?: number;
}

// 产物阶段映射
const PHASE_MAP: Record<string, { name: string; icon: string; desc: string }> = {
  S1_RESEARCH: { name: 'S1 调研报告', icon: '🔍', desc: '市场数据 & 宏观环境' },
  S2_ANALYSIS: { name: 'S2 分析报告', icon: '🧠', desc: '多维度技术分析' },
  S3_DESIGN: { name: 'S3 策略方案', icon: '📐', desc: '入场出场点位' },
  S4_VALIDATE: { name: 'S4 验证报告', icon: '✅', desc: '回测 & 风险评估' },
  S5_EXECUTE: { name: 'S5 执行计划', icon: '⚡', desc: '下单 & 跟踪计划' },
  A2: { name: '分析报告', icon: '🧠', desc: '深度分析' },
  A6: { name: '情报简报', icon: '🔍', desc: '市场情报' },
};

export default function TaskCard({
  trace,
  isLoading,
  streamProgress,
  executionTimeMs,
  executionSummary,
  artifacts,
  taskId,
  intent,
  confidence,
}: Props) {
  const [showArtifacts, setShowArtifacts] = useState(true);

  const hasTrace = !!trace;
  const hasSummary = !!executionSummary;
  const hasArtifacts = artifacts && artifacts.length > 0;
  const isStreaming = isLoading || streamProgress?.isStreaming;

  // 无任何结构化数据且非加载中 → 不渲染
  if (!hasTrace && !hasSummary && !hasArtifacts && !isStreaming) return null;

  // 执行链路
  const chainExecuted = (executionSummary as any)?.chain_executed as string[] | undefined;
  const thinkingDepth = (executionSummary as any)?.thinking_depth as string | undefined;

  return (
    <div className="mb-2">
      {/* ── 决策链 DAG（复用 ThinkingCard） ── */}
      <ThinkingCard
        trace={trace ?? undefined}
        isLoading={isLoading}
        streamProgress={streamProgress ?? undefined}
        executionTimeMs={executionTimeMs}
      />

      {/* ── 执行摘要 ── */}
      {hasSummary && !isStreaming && (
        <div className="mt-1 px-3 py-2 bg-[#0d0d0d] border border-[#1a1a1a] rounded-lg text-[11px]">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-[#06b6d4] font-semibold">📊 执行摘要</span>
            {chainExecuted && chainExecuted.length > 0 && (
              <span className="text-[#8a8a8a]">
                链路: <span className="text-[#06b6d4]">{chainExecuted.join(' → ')}</span>
              </span>
            )}
            {thinkingDepth && (
              <span className="text-[#8a8a8a]">
                深度: <span className="text-purple-400">{thinkingDepth}</span>
              </span>
            )}
            {executionTimeMs && executionTimeMs > 0 && (
              <span className="text-[#8a8a8a]">
                耗时: <span className="text-green-400">
                  {executionTimeMs >= 1000 ? `${(executionTimeMs / 1000).toFixed(1)}s` : `${executionTimeMs}ms`}
                </span>
              </span>
            )}
            {confidence !== undefined && (
              <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                confidence >= 0.8 ? 'bg-green-500/20 text-green-400' :
                confidence >= 0.6 ? 'bg-yellow-500/20 text-yellow-400' :
                'bg-red-500/20 text-red-400'
              }`}>
                置信 {(confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
        </div>
      )}

      {/* ── 产物列表 ── */}
      {hasArtifacts && showArtifacts && (
        <div className="mt-1 px-3 py-2 bg-[#0d0d0d] border border-[#1a1a1a] rounded-lg">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] text-[#06b6d4] font-semibold">
              📎 产物 <span className="text-[#71717a] font-normal">({artifacts!.length})</span>
            </span>
            <button
              onClick={() => setShowArtifacts(false)}
              className="text-[10px] text-[#71717a] hover:text-[#06b6d4]"
            >
              收起
            </button>
          </div>
          <div className="grid grid-cols-1 gap-1.5">
            {artifacts!.map((art, idx) => {
              const info = PHASE_MAP[art.chain_phase] || { name: art.chain_phase, icon: '📄', desc: art.type };
              return (
                <div
                  key={idx}
                  className="flex items-center gap-2 px-2.5 py-1.5 bg-gradient-to-r from-cyan-500/10 to-purple-500/5 border border-cyan-500/30 rounded-lg hover:border-cyan-500/60 transition group cursor-pointer"
                  onClick={async () => {
                    try {
                      const res = await fetch(`/api/artifact?file=${encodeURIComponent(art.file)}`);
                      const data = await res.json();
                      if (data.success && data.content) {
                        alert(`📄 ${art.file}\n\n${data.content.slice(0, 2000)}${data.content.length > 2000 ? '\n\n...(更多内容)' : ''}`);
                      } else {
                        alert(`⚠️ 产物文件暂未生成\n\n文件名: ${art.file}\n类型: ${art.type}\n阶段: ${art.chain_phase}`);
                      }
                    } catch (e) {
                      alert(`❌ 读取失败: ${e instanceof Error ? e.message : '未知错误'}`);
                    }
                  }}
                >
                  <div className="text-base flex-shrink-0">{info.icon}</div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] font-semibold text-[#06b6d4] truncate">{info.name}</div>
                    <div className="text-[10px] text-[#71717a] truncate">{info.desc} · {art.file}</div>
                  </div>
                  <div className="text-[10px] text-[#71717a] group-hover:text-[#06b6d4] flex-shrink-0">
                    查看 →
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── 折叠态产物入口 ── */}
      {hasArtifacts && !showArtifacts && (
        <button
          onClick={() => setShowArtifacts(true)}
          className="mt-1 text-[11px] text-[#06b6d4] hover:underline"
        >
          📎 展开 {artifacts!.length} 个产物
        </button>
      )}
    </div>
  );
}
