// ============================================
// AI SDK UIMessage.parts → AgentPart 适配器（SPEC-20261111-B §3.3 / §3.6）
// ============================================
// 单向映射：业务组件只吃自有 AgentPart；AI SDK 版本漂移被收敛在本文件（宽松类型 + 未知忽略）。

import type { AgentPart, ToolPartState } from '@/types/agent-message';

/** AI SDK UIMessage part 的宽松形态（只取用到的字段） */
export interface LooseUIPart {
  type?: string;
  text?: string;
  toolCallId?: string;
  state?: string;
  input?: unknown;
  output?: unknown;
  errorText?: string;
}

export interface LooseUIMessage {
  parts?: unknown[];
}

function mapToolState(state?: string): ToolPartState {
  switch (state) {
    case 'output-available':
      return 'success';
    case 'output-error':
      return 'error';
    case 'input-streaming':
    case 'input-available':
      return 'running';
    default:
      return 'pending';
  }
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : undefined;
}

/**
 * 一条 UIMessage → AgentPart[]。
 * 兼容 text / reasoning / tool-<name>；step-start、source、file 等未知 part 忽略。
 */
export function uiMessageToParts(message: LooseUIMessage | null | undefined): AgentPart[] {
  const rawParts = Array.isArray(message?.parts) ? message?.parts ?? [] : [];
  const parts: AgentPart[] = [];

  for (const raw of rawParts) {
    if (!raw || typeof raw !== 'object') continue;
    const part = raw as LooseUIPart;
    if (typeof part.type !== 'string') continue;

    if (part.type === 'text') {
      if (part.text) parts.push({ type: 'text', text: part.text });
      continue;
    }

    if (part.type === 'reasoning') {
      if (part.text) parts.push({ type: 'reasoning', text: part.text });
      continue;
    }

    if (part.type.startsWith('tool-')) {
      parts.push({
        type: 'tool',
        callId: part.toolCallId ?? `tool_${parts.length}`,
        toolName: part.type.slice('tool-'.length),
        state: mapToolState(part.state),
        args: asRecord(part.input),
        result: part.output,
        error: part.errorText,
      });
      continue;
    }

    // 其他 AI SDK part（step-start / source-url / file / data-*）忽略
  }

  return parts;
}
