"use client";

// ============================================================
// MessageItem — 消息渲染分发
// 有 chain_trace/artifacts → TaskCard + 内容
// 无 → 纯文本气泡
// 版本: v1.0 | 日期: 2026-09-23
// ============================================================

import dynamic from "next/dynamic";
import type { ChatMessage } from "@/types";
import TaskCard from "./TaskCard";
import { V3Card } from "@/components/V3Card";
import { InsightCard } from "./InsightCard";
import { RecommendationCard } from "./RecommendationCard";
import { SynthesisChart } from "./SynthesisChart";
import { ReportExport } from "./ReportExport";

const ReactMarkdown = dynamic(() => import("react-markdown"), { ssr: false });

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

interface Props {
  message: ChatMessage;
  /** 是否为最后一条消息（用于流式进度） */
  isLast?: boolean;
  /** 流式进度（仅 thinking 状态的最后一条消息） */
  streamProgress?: StreamProgress | null;
  /** 执行耗时（ms） */
  executionTimeMs?: number;
  /** 子节点：额外的渲染区（notebook 进度、策略链等） */
  children?: React.ReactNode;
}

export default function MessageItem({
  message: msg,
  isLast,
  streamProgress,
  executionTimeMs,
  children,
}: Props) {
  const hasTaskCard = !!msg.chain_trace || !!(msg as any).artifacts_produced?.length || !!msg.execution_summary || msg.intent === "thinking";

  return (
    <>
      {/* ── 助手/用户头部 ── */}
      {msg.role === "assistant" && (
        <div className="text-[#06b6d4] text-xs mb-1.5 flex items-center gap-2 flex-wrap">
          <span>🤖 AI助手</span>
          {msg.intent && msg.intent !== "unknown" && msg.intent !== "thinking" && msg.intent !== "error" && (
            <span className="bg-[#0f3460] px-1.5 py-0.5 rounded text-[10px]">
              {msg.intent}
            </span>
          )}
          {msg.confidence !== undefined && (
            <span className={`px-1.5 py-0.5 rounded text-[10px] ${
              msg.confidence >= 0.8 ? 'bg-green-500/20 text-green-400' :
              msg.confidence >= 0.6 ? 'bg-yellow-500/20 text-yellow-400' :
              'bg-red-500/20 text-red-400'
            }`}>
              置信度 {(msg.confidence * 100).toFixed(0)}%
            </span>
          )}
          {msg.thinking_mode && msg.thinking_mode !== 'quick' && (
            <span className="bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded text-[10px]">
              🧠 深度
            </span>
          )}
        </div>
      )}
      {msg.role === "user" && (
        <div className="text-right text-xs mb-1.5 opacity-70">👤 你</div>
      )}

      {/* ── TaskCard（决策链 + 摘要 + 产物） ── */}
      {msg.role === "assistant" && hasTaskCard && msg.intent !== 'error' && (
        <TaskCard
          trace={msg.chain_trace}
          isLoading={msg.intent === 'thinking'}
          streamProgress={isLast ? streamProgress : undefined}
          executionTimeMs={executionTimeMs}
          executionSummary={msg.execution_summary}
          artifacts={(msg as any).artifacts_produced || (msg as any).artifacts}
          taskId={msg.task_id}
          intent={msg.intent}
          confidence={msg.confidence}
        />
      )}

      {/* ── F7.1: Muse 启发卡片（synthesized_cards 渲染分发，与 TaskCard 并列） ── */}
      {msg.role === "assistant" && msg.synthesized_cards && msg.intent !== 'error' && (
        <div className="mt-2 mb-2 space-y-2">
          {/* 导出按钮 */}
          <div className="flex justify-end">
            <ReportExport
              synthesis={msg.synthesized_cards}
              symbol={msg.metadata?.intent?.entities?.symbol || 'BTC'}
            />
          </div>
          {/* AI 洞察卡片 */}
          <InsightCard insights={msg.synthesized_cards.insights} />
          {/* 行动建议卡片 */}
          <RecommendationCard recommendations={msg.synthesized_cards.recommendations} />
          {/* 独立图表（未被 insight/recommendation 引用的 charts） */}
          {msg.synthesized_cards.charts && msg.synthesized_cards.charts.length > 0 && (
            <V3Card
              title="数据图表"
              subtitle="多模块信号可视化"
              icon={
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z" />
                </svg>
              }
              badge={
                <span className="text-[10px] text-gray-400 bg-gray-800/50 px-2 py-0.5 rounded-full">
                  {msg.synthesized_cards.charts.length} 张
                </span>
              }
            >
              <div className="space-y-2">
                {msg.synthesized_cards.charts.map((chart, ci) => (
                  <SynthesisChart key={ci} chart={chart} />
                ))}
              </div>
            </V3Card>
          )}
        </div>
      )}

      {/* ── Markdown 内容 ── */}
      <div className="text-sm prose prose-invert prose-sm max-w-none chat-markdown">
        <ReactMarkdown
          components={{
            a: ({ node, ...props }) => {
              const isReportLink = props.href?.startsWith('/reports/');
              const isInternal = props.href?.startsWith('/');
              return (
                <a
                  {...props}
                  target={isReportLink ? '_blank' : (isInternal ? undefined : '_blank')}
                  rel={isInternal && !isReportLink ? undefined : 'noopener noreferrer'}
                  className="text-blue-400 hover:text-blue-300 underline"
                />
              );
            },
            details: ({ node, children, ...props }) => (
              <details className="my-2 text-xs" {...props}>
                {children}
              </details>
            ),
            summary: ({ node, children, ...props }) => (
              <summary className="cursor-pointer text-gray-400 hover:text-gray-300" {...props}>
                {children}
              </summary>
            ),
          }}
        >
          {msg.content}
        </ReactMarkdown>
      </div>

      {/* ── 额外渲染区（notebook 进度、策略链、交易确认等） ── */}
      {children}
    </>
  );
}
