'use client';

// ============================================
// PartRenderer — 消息 part 注册表（SPEC-20261111-B §3.3）
// ============================================
// 6 类 part：text / reasoning / tool / plan-card / artifact / verification。
// 未知类型：UnknownPart（JSON 折叠 + console.warn），FAIL-OPEN 不白屏。
// 新增 part 类型只需在 RENDERERS 注册，不改消息列表。

import React, { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { ToolCard } from './ToolCard';
import { PlanCardView } from './PlanCardView';
import type { AgentPart, AgentMessage, UnknownAgentPart } from '@/types/agent-message';

export interface PartRenderProps {
  part: AgentPart;
}

const MARKDOWN_CLASS =
  'markdown-body [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_p]:my-1 [&_ul]:my-1 [&_li]:my-0.5 [&_h1]:text-base [&_h2]:text-base [&_h3]:text-sm [&_blockquote]:border-l-2 [&_blockquote]:border-gray-500/50 [&_blockquote]:pl-3 [&_blockquote]:text-gray-300';

function TextPart({ part }: PartRenderProps) {
  if (part.type !== 'text') return null;
  return (
    <div className={MARKDOWN_CLASS}>
      <ReactMarkdown>{part.text || ''}</ReactMarkdown>
    </div>
  );
}

function ReasoningPart({ part }: PartRenderProps) {
  if (part.type !== 'reasoning') return null;
  const duration =
    typeof part.durationMs === 'number' && part.durationMs >= 0
      ? part.durationMs < 1000
        ? `${Math.round(part.durationMs)}ms`
        : `${(part.durationMs / 1000).toFixed(1)}s`
      : null;
  return (
    <details data-testid="reasoning-part" className="rounded-lg border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-xs">
      <summary className="cursor-pointer text-slate-400">
        推理过程{duration ? `（${duration}）` : ''}
      </summary>
      <div className={`mt-2 text-slate-300 ${MARKDOWN_CLASS}`}>
        <ReactMarkdown>{part.text || ''}</ReactMarkdown>
      </div>
    </details>
  );
}

function ToolPart({ part }: PartRenderProps) {
  if (part.type !== 'tool') return null;
  return <ToolCard part={part} />;
}

function PlanCardPart({ part }: PartRenderProps) {
  if (part.type !== 'plan-card') return null;
  return <PlanCardView card={part.card} />;
}

const ARTIFACT_KIND_LABEL: Record<'report' | 'chart' | 'file', string> = {
  report: '报告',
  chart: '图表',
  file: '文件',
};

function ArtifactPart({ part }: PartRenderProps) {
  if (part.type !== 'artifact') return null;
  const label = ARTIFACT_KIND_LABEL[part.kind] ?? '文件';
  const isLink = /^(https?:\/\/|\/)/.test(part.artifactId);
  return (
    <div data-testid="artifact-part" className="flex items-center gap-2 rounded-lg border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-xs">
      <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[11px] text-slate-300">{label}</span>
      {isLink ? (
        <a href={part.artifactId} className="truncate text-indigo-300 hover:underline" target="_blank" rel="noreferrer">
          {part.title}
        </a>
      ) : (
        <span className="truncate text-slate-200">{part.title}</span>
      )}
      <span className="ml-auto font-mono text-[10px] text-slate-500">{part.artifactId}</span>
    </div>
  );
}

const VERDICT_META: Record<'PASS' | 'BLOCK' | 'INCONCLUSIVE', { label: string; tone: string }> = {
  PASS: { label: 'PASS', tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  BLOCK: { label: 'BLOCK', tone: 'bg-red-500/15 text-red-300 border-red-500/40' },
  INCONCLUSIVE: { label: 'INCONCLUSIVE', tone: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
};

function VerificationPart({ part }: PartRenderProps) {
  if (part.type !== 'verification') return null;
  const meta = VERDICT_META[part.verdict] ?? VERDICT_META.INCONCLUSIVE;
  return (
    <div data-testid="verification-part" className="rounded-lg border border-slate-700/60 bg-slate-900/40 px-3 py-2 text-xs">
      <div className="flex items-center gap-2">
        <span className={`rounded border px-1.5 py-0.5 text-[11px] ${meta.tone}`}>{meta.label}</span>
        <span className="text-slate-400">验证结论</span>
      </div>
      {part.evidenceRefs.length > 0 && (
        <ul className="mt-1 list-disc pl-4 text-slate-400">
          {part.evidenceRefs.map((ref) => (
            <li key={ref} className="font-mono text-[11px]">{ref}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 未知 part 降级：JSON 折叠 + console.warn，不抛错 */
export function UnknownPart({ part }: { part: UnknownAgentPart }) {
  useEffect(() => {
    console.warn('[PartRenderer] 未知 part 类型，已降级为 JSON 折叠：', part.type);
  }, [part.type]);

  return (
    <details
      data-testid="unknown-part"
      className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-200"
    >
      <summary className="cursor-pointer">未知消息类型：{part.type}（点击查看原始 JSON）</summary>
      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[11px] text-slate-300">
        {safeStringify(part)}
      </pre>
    </details>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

const RENDERERS: Record<AgentPart['type'], React.ComponentType<PartRenderProps>> = {
  text: TextPart,
  reasoning: ReasoningPart,
  tool: ToolPart,
  'plan-card': PlanCardPart,
  artifact: ArtifactPart,
  verification: VerificationPart,
};

export interface PartRendererProps {
  /** 已注册 part 或任意未知类型（宽松接收，未知走降级） */
  part: AgentPart | UnknownAgentPart;
}

export function PartRenderer({ part }: PartRendererProps) {
  const Renderer = RENDERERS[(part as AgentPart).type as AgentPart['type']];
  if (!Renderer) {
    return <UnknownPart part={part as UnknownAgentPart} />;
  }
  return <Renderer part={part as AgentPart} />;
}

/** 一条消息的 part 列表渲染入口 */
export function PartList({ parts }: { parts: Array<AgentPart | UnknownAgentPart> }) {
  return (
    <div className="space-y-2">
      {parts.map((part, index) => (
        <PartRenderer key={`${(part as AgentPart).type ?? 'unknown'}-${index}`} part={part} />
      ))}
    </div>
  );
}

/** 消息列表渲染入口（part 版 MessageItem 的替代，交易域不改用） */
export function AgentMessageList({ messages }: { messages: AgentMessage[] }) {
  return (
    <div className="space-y-4">
      {messages.map((message) => (
        <div key={message.id} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
          <div className="max-w-[80%]">
            <PartList parts={message.parts} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default PartRenderer;
