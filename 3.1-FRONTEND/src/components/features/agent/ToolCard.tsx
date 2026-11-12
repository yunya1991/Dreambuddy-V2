'use client';

// ============================================
// ToolCard — 工具调用四态卡片（SPEC-20261111-B §3.4）
// ============================================
// 四态：pending 排队中 / running 进行中 / success 完成 / error 失败。
// 默认展开规则：error 默认展开，其余默认折叠；长结果超过 12 行折叠。
// 重试按钮仅在调用方注入 onRetry 时显示（协议层），交易域不传。

import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { IconCopy } from '@/components';
import type { AgentPart, ToolPartState } from '@/types/agent-message';

export type ToolAgentPart = Extract<AgentPart, { type: 'tool' }>;

/** 长结果折叠阈值（行） */
export const TOOL_FOLD_LINE_THRESHOLD = 12;

const STATE_META: Record<ToolPartState, { dot: string; label: string; tone: string }> = {
  pending: { dot: 'bg-gray-500', label: '排队中', tone: 'text-gray-400' },
  running: { dot: 'bg-blue-400 animate-pulse', label: '进行中', tone: 'text-blue-300' },
  success: { dot: 'bg-emerald-500', label: '完成', tone: 'text-emerald-300' },
  error: { dot: 'bg-red-500', label: '失败', tone: 'text-red-300' },
};

function formatDuration(ms?: number): string | null {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null;
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function resultToText(result: unknown): string {
  if (result === undefined || result === null) return '';
  if (typeof result === 'string') return result;
  try {
    return JSON.stringify(result, null, 2);
  } catch {
    return String(result);
  }
}

function firstLine(text: string, max = 60): string {
  const line = text.split('\n').find((l) => l.trim().length > 0) ?? '';
  return line.length > max ? `${line.slice(0, max)}…` : line;
}

interface ToolCardProps {
  part: ToolAgentPart;
  /** 仅协议层注入；存在时 error 态显示重试 */
  onRetry?: () => void;
}

export function ToolCard({ part, onRetry }: ToolCardProps) {
  const meta = STATE_META[part.state] ?? STATE_META.pending;
  const [expanded, setExpanded] = useState(part.state === 'error');
  const [showAll, setShowAll] = useState(false);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

  const resultText = resultToText(part.result);
  const lines = resultText ? resultText.split('\n') : [];
  const foldable = lines.length > TOOL_FOLD_LINE_THRESHOLD;
  const visibleResult = foldable && !showAll
    ? lines.slice(0, TOOL_FOLD_LINE_THRESHOLD).join('\n')
    : resultText;
  const duration = formatDuration(part.durationMs);
  const summary = part.state === 'success' ? firstLine(resultText) : part.state === 'error' ? firstLine(part.error ?? '') : '';

  async function handleCopy() {
    const text = part.error ?? resultText;
    if (!text) return;
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
      setCopyState('failed');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopyState('copied');
      setTimeout(() => setCopyState('idle'), 1500);
    } catch {
      setCopyState('failed');
    }
  }

  return (
    <div
      data-testid="tool-card"
      data-state={part.state}
      className="rounded-lg border border-slate-700/60 bg-slate-900/50 text-xs"
    >
      <div className="flex items-center gap-2 px-3 py-2">
        <span data-testid="tool-state-dot" className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
        <span className="font-mono text-[11px] text-slate-200">{part.toolName}</span>
        <span data-testid="tool-state-label" className={`${meta.tone}`}>{meta.label}</span>
        {duration && <span className="text-slate-500">{duration}</span>}
        {summary && (
          <span className="truncate max-w-[40%] text-slate-500" title={summary}>{summary}</span>
        )}
        <span className="ml-auto flex items-center gap-2">
          {part.state === 'error' && onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="rounded border border-red-500/40 px-2 py-0.5 text-red-300 hover:bg-red-500/10"
            >
              重试
            </button>
          )}
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
            className="rounded border border-slate-700 px-2 py-0.5 text-slate-400 hover:text-slate-200"
          >
            {expanded ? '收起' : part.state === 'success' ? '展开结果' : '查看明细'}
          </button>
        </span>
      </div>

      {expanded && (
        <div className="border-t border-slate-700/60 px-3 py-2 space-y-2">
          {part.error && (
            <div data-testid="tool-error" className="text-red-300 whitespace-pre-wrap break-words">
              {part.error}
            </div>
          )}
          {part.args && Object.keys(part.args).length > 0 && (
            <div>
              <div className="mb-1 text-slate-500">参数</div>
              <pre className="max-h-48 overflow-auto rounded bg-slate-950/60 p-2 text-[11px] text-slate-300">
                {JSON.stringify(part.args, null, 2)}
              </pre>
            </div>
          )}
          {visibleResult && (
            <div>
              <div className="mb-1 flex items-center gap-2 text-slate-500">
                <span>结果</span>
                <button
                  type="button"
                  onClick={handleCopy}
                  className="inline-flex items-center gap-1 hover:text-slate-300"
                >
                  <IconCopy className="w-3 h-3" />
                  <span data-testid="tool-copy-label">
                    {copyState === 'copied' ? '已复制' : copyState === 'failed' ? '复制不可用' : '复制'}
                  </span>
                </button>
              </div>
              <div className="max-h-64 overflow-auto rounded bg-slate-950/60 p-2 text-[11px] text-slate-300">
                {typeof part.result === 'string' ? (
                  <div className="markdown-body [&_p]:my-1 [&_ul]:my-1 [&_li]:my-0.5">
                    <ReactMarkdown>{visibleResult}</ReactMarkdown>
                  </div>
                ) : (
                  <pre className="whitespace-pre-wrap break-words">{visibleResult}</pre>
                )}
              </div>
              {foldable && (
                <button
                  type="button"
                  onClick={() => setShowAll((v) => !v)}
                  className="mt-1 text-slate-400 hover:text-slate-200"
                >
                  {showAll ? '收起' : `展开全部（${lines.length} 行）`}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ToolCard;
