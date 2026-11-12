// ============================================
// Agent 消息 Part 契约 — 交互内核统一渲染模型
// ============================================
// 依据：SPEC-20261111-B §3.3 / 原 SPEC §2.3。
// 只定义自有模型，不依赖 AI SDK 类型（AI SDK 经 adapters 单向映射进来）。

import type { PlanCard } from './plancard';

export type ToolPartState = 'pending' | 'running' | 'success' | 'error';

export type AgentPart =
  | { type: 'text'; text: string }
  | { type: 'reasoning'; text: string; durationMs?: number }
  | {
      type: 'tool';
      callId: string;
      toolName: string;
      state: ToolPartState;
      args?: Record<string, unknown>;
      result?: unknown;
      error?: string;
      durationMs?: number;
    }
  | { type: 'plan-card'; card: PlanCard }
  | { type: 'artifact'; artifactId: string; title: string; kind: 'report' | 'chart' | 'file' }
  | { type: 'verification'; verdict: 'PASS' | 'BLOCK' | 'INCONCLUSIVE'; evidenceRefs: string[] };

export type AgentPartType = AgentPart['type'];

export interface AgentMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  parts: AgentPart[];
  createdAt: number;
  status?: 'streaming' | 'done' | 'error';
  traceId?: string;
}

/** 渲染层对未知 part 的宽松形态（后端新增类型时 FAIL-OPEN 降级） */
export interface UnknownAgentPart {
  type: string;
  [key: string]: unknown;
}

export function isAgentPart(value: unknown): value is AgentPart {
  if (!value || typeof value !== 'object') return false;
  const type = (value as { type?: unknown }).type;
  return (
    type === 'text' ||
    type === 'reasoning' ||
    type === 'tool' ||
    type === 'plan-card' ||
    type === 'artifact' ||
    type === 'verification'
  );
}
