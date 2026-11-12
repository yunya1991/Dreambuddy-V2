// ============================================
// 交易域 SSE → AgentPart 适配器（SPEC-20261111-B §3.3）
// ============================================
// 单向映射：只把 sse-client 的既有事件翻译为 part，不改 sse-dispatcher / ChatPanel 的现有行为。
// 事件名以 src/lib/sse-client.ts 的 SSEEventType 为准；未识别事件忽略，不抛错。

import type { AgentPart } from '@/types/agent-message';

export interface LooseSSEEvent {
  type?: string;
  data?: Record<string, unknown>;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function strArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

function artifactKind(type?: string): 'report' | 'chart' | 'file' {
  if (type === 'report') return 'report';
  if (type === 'chart' || type === 'market' || type === 'signal') return 'chart';
  return 'file';
}

function progressToolState(data: Record<string, unknown>, nested: Record<string, unknown>): 'running' | 'success' | 'error' {
  const status = str(data.status) ?? str(nested.status);
  if (status === 'done' || status === 'skipped') return 'success';
  if (status === 'failed') return 'error';
  if (status === 'running' || status === 'active') return 'running';
  const evtType = str(data.type);
  if (evtType === 'step_end') return 'success';
  return 'running';
}

/**
 * 单个 SSE 事件 → 0..N 个 AgentPart。
 * @param index 同批次事件序号，用于生成稳定的 callId（缺 stepId 时）
 */
export function sseEventToParts(
  type: string | undefined,
  data: Record<string, unknown> = {},
  index = 0,
): AgentPart[] {
  const nested = asRecord(data.data);

  switch (type) {
    case 'thinking': {
      const text = str(data.content);
      return text ? [{ type: 'reasoning', text }] : [];
    }

    case 'text_delta': {
      const text = str(data.delta);
      return text ? [{ type: 'text', text }] : [];
    }

    case 'progress': {
      const callId = str(data.stepId) ?? str(nested.stepId) ?? `step_${index}`;
      const toolName = str(data.stepName) ?? str(nested.stepName) ?? str(data.message) ?? callId;
      const durationMs = typeof data.durationMs === 'number' ? data.durationMs : undefined;
      return [
        {
          type: 'tool',
          callId,
          toolName,
          state: progressToolState(data, nested),
          durationMs,
        },
      ];
    }

    case 'cross_validation': {
      const issues = strArray(data.issuesFound).length > 0 ? strArray(data.issuesFound) : strArray(nested.issuesFound);
      const gatePassed = (data.gatePassed ?? nested.gatePassed) as boolean | undefined;
      return [
        {
          type: 'verification',
          verdict: gatePassed === false ? 'BLOCK' : 'PASS',
          evidenceRefs: issues,
        },
      ];
    }

    case 'data_card': {
      const artifactId = str(data.cardId) ?? `card_${index}`;
      const title = str(data.title) ?? '数据卡片';
      return [{ type: 'artifact', artifactId, title, kind: artifactKind(str(data.cardType)) }];
    }

    case 'artifact_ref': {
      const artifactId = str(data.artifactId) ?? `art_${index}`;
      return [
        {
          type: 'artifact',
          artifactId,
          title: str(data.title) ?? '未命名产物',
          kind: artifactKind(str(data.artifactType)),
        },
      ];
    }

    case 'action_required': {
      return [
        {
          type: 'tool',
          callId: `action_${index}`,
          toolName: str(data.action) ?? 'action_required',
          state: 'pending',
          args: data,
        },
      ];
    }

    case 'done': {
      const text = str(data.content);
      return text ? [{ type: 'text', text }] : [];
    }

    case 'error': {
      const message = str(data.error) ?? str(data.message) ?? '未知错误';
      const parts: AgentPart[] = [{ type: 'text', text: `错误：${message}` }];
      if (data.blocked === true) {
        parts.push({ type: 'verification', verdict: 'BLOCK', evidenceRefs: [message] });
      }
      return parts;
    }

    default:
      // started / 未知事件：忽略并交由调用方计数，不抛错
      return [];
  }
}

/** 批量事件流 → 扁平 part 列表（保持事件顺序） */
export function sseEventsToParts(events: LooseSSEEvent[]): AgentPart[] {
  return events.flatMap((event, index) => sseEventToParts(event.type, asRecord(event.data), index));
}
