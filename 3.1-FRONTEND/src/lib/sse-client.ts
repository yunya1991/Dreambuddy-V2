// ============================================
// v3 SSE Client — 流式事件处理
// ============================================

// === SSE 事件类型 ===
export type SSEEventType =
  | 'started'
  | 'thinking'
  | 'progress'
  | 'text_delta'
  | 'data_card'
  | 'artifact_ref'
  | 'action_required'
  | 'done'
  | 'error';

// === SSE 事件数据 ===
export interface SSEEvent {
  type: SSEEventType;
  data: Record<string, unknown>;
  timestamp: string;
}

// === 各事件类型的具体数据结构 ===
export interface SSEStartedEvent {
  chainId: string;
  chainName: string;
  chainType: string;
  totalSteps: number;
}

export interface SSEThinkingEvent {
  content: string;
  stepId?: string;
}

export interface SSEProgressEvent {
  stepId: string;
  stepName: string;
  stepIndex: number;
  totalSteps: number;
  status: 'active' | 'done' | 'skipped' | 'failed';
  reflectorAction?: string;
  reflectorReason?: string;
}

export interface SSETextDeltaEvent {
  delta: string;
}

export interface SSEDataCardEvent {
  cardId: string;
  cardType: 'market' | 'balance' | 'position' | 'signal' | 'report';
  title: string;
  content: unknown;
}

export interface SSEArtifactRefEvent {
  artifactId: string;
  artifactType: string;
  title: string;
  summary?: string;
}

export interface SSEActionRequiredEvent {
  action: string;
  message: string;
  options?: { label: string; value: string }[];
}

export interface SSEDoneEvent {
  chainId: string;
  totalTokens: number;
  duration: number;
  grade?: string;
}

export interface SSEErrorEvent {
  code: number;
  message: string;
  recoverable: boolean;
}

// === 事件处理器映射 ===
export type SSEEventHandler<T = unknown> = (data: T) => void;

export interface SSEHandlerMap {
  started?: SSEEventHandler<SSEStartedEvent>;
  thinking?: SSEEventHandler<SSEThinkingEvent>;
  progress?: SSEEventHandler<SSEProgressEvent>;
  text_delta?: SSEEventHandler<SSETextDeltaEvent>;
  data_card?: SSEEventHandler<SSEDataCardEvent>;
  artifact_ref?: SSEEventHandler<SSEArtifactRefEvent>;
  action_required?: SSEEventHandler<SSEActionRequiredEvent>;
  done?: SSEEventHandler<SSEDoneEvent>;
  error?: SSEEventHandler<SSEErrorEvent>;
}

// === SSE 连接 ===
export interface SSEConnection {
  close: () => void;
  readyState: number;
}

// === 创建 SSE 连接 ===
export function createSSEConnection(
  url: string,
  body: unknown,
  handlers: SSEHandlerMap,
  options?: { onError?: (error: Error) => void }
): SSEConnection {
  const controller = new AbortController();

  // 使用 fetch + ReadableStream 实现 POST-based SSE
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        handlers.error?.({
          code: response.status,
          message: `SSE 连接失败: ${response.statusText}`,
          recoverable: false,
        });
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        handlers.error?.({ code: 0, message: '无法获取响应流', recoverable: false });
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEventType: SSEEventType | null = null;
        let currentData = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEventType = line.slice(7).trim() as SSEEventType;
          } else if (line.startsWith('data: ')) {
            currentData = line.slice(6);
          } else if (line === '' && currentEventType && currentData) {
            // 空行表示事件结束，分发
            try {
              const parsed = JSON.parse(currentData);
              dispatchSSEEvent(currentEventType, parsed, handlers);
            } catch {
              // data 不是 JSON，尝试按纯文本处理
              dispatchSSEEvent(currentEventType, { raw: currentData }, handlers);
            }
            currentEventType = null;
            currentData = '';
          }
        }
      }
    })
    .catch((err) => {
      if (controller.signal.aborted) return;
      options?.onError?.(err instanceof Error ? err : new Error(String(err)));
    });

  return {
    close: () => controller.abort(),
    readyState: controller.signal.aborted ? 3 : 0, // 0=CONNECTING, 3=CLOSED
  };
}

// === 事件分发 ===
function dispatchSSEEvent(type: SSEEventType, data: Record<string, unknown>, handlers: SSEHandlerMap) {
  switch (type) {
    case 'started':
      handlers.started?.(data as unknown as SSEStartedEvent);
      break;
    case 'thinking':
      handlers.thinking?.(data as unknown as SSEThinkingEvent);
      break;
    case 'progress':
      handlers.progress?.(data as unknown as SSEProgressEvent);
      break;
    case 'text_delta':
      handlers.text_delta?.(data as unknown as SSETextDeltaEvent);
      break;
    case 'data_card':
      handlers.data_card?.(data as unknown as SSEDataCardEvent);
      break;
    case 'artifact_ref':
      handlers.artifact_ref?.(data as unknown as SSEArtifactRefEvent);
      break;
    case 'action_required':
      handlers.action_required?.(data as unknown as SSEActionRequiredEvent);
      break;
    case 'done':
      handlers.done?.(data as unknown as SSEDoneEvent);
      break;
    case 'error':
      handlers.error?.(data as unknown as SSEErrorEvent);
      break;
  }
}

export default createSSEConnection;
