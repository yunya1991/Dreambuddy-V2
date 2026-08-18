// ============================================
// SSE 事件分发器 — 将 /api/task/stream 事件映射到各 Store
// ============================================

import { useSessionStore } from '@/stores/session-store';
import { useChainStore, type ChainTrace } from '@/stores/chain-store';
import { useMonitorStore } from '@/stores/monitor-store';
import type { SSEHandlerMap } from './sse-client';

/**
 * 创建 SSE 事件处理器映射
 * 将 /api/task/stream 的 SSE 事件分发到对应的 Zustand Store
 */
export function createTaskStreamHandlers(options?: {
  onDone?: (data: TaskDoneData) => void;
  onError?: (error: Error) => void;
}): SSEHandlerMap {
  const session = useSessionStore.getState;
  const chain = useChainStore.getState;
  const monitor = useMonitorStore.getState;

  return {
    started: (data) => {
      // 任务开始
      monitor().setSSEStatus('connected');
      monitor().addEvent('S', {
        id: `evt_${Date.now()}`,
        layer: 'S',
        type: 'task_started',
        description: data.message || '任务已开始执行',
        timestamp: Date.now(),
      });
      session().setStreaming(true, '');
      session().setLastTaskStatus('running');
    },

    thinking: (data) => {
      // AI 思考过程 — 追加到流式内容
      if (data.content) {
        session().appendStreamingContent(data.content);
      }
    },

    progress: (data) => {
      // 链路步骤进度
      const stepId = data.stepId || `step_${data.stepIndex ?? 0}`;
      const status = data.status === 'done' ? 'done' : data.status === 'skipped' ? 'skipped' : data.status === 'failed' ? 'failed' : 'running';

      chain().updateStep(stepId, {
        status,
        outputSummary: data.stepName,
      });

      // Reflector 决策
      if (data.reflectorAction) {
        chain().reflectorDecision(stepId, data.reflectorAction as any, data.reflectorReason || '');
      }

      monitor().addEvent('C', {
        id: `evt_${Date.now()}`,
        layer: 'C',
        type: 'step_progress',
        description: `${data.stepName || stepId}: ${status}`,
        timestamp: Date.now(),
      });
    },

    text_delta: (data) => {
      // 流式文本增量
      if (data.delta) {
        session().appendStreamingContent(data.delta);
      }
    },

    data_card: (data) => {
      // 数据卡片 — 暂时追加为文本
      monitor().addEvent('C', {
        id: `evt_${Date.now()}`,
        layer: 'C',
        type: 'data_card',
        description: data.title || '数据卡片',
        timestamp: Date.now(),
      });
    },

    artifact_ref: (data) => {
      // 产物引用
      chain().addArtifact({
        id: data.artifactId || `art_${Date.now()}`,
        type: data.artifactType || 'report',
        title: data.title || '未命名产物',
      });
    },

    action_required: (data) => {
      // 需要用户操作
      monitor().addEvent('S', {
        id: `evt_${Date.now()}`,
        layer: 'S',
        type: 'action_required',
        description: data.message || data.action || '需要用户操作',
        timestamp: Date.now(),
      });
    },

    done: (data) => {
      const doneData = data as unknown as TaskDoneData;

      // 更新任务状态
      session().setLastTaskStatus(doneData.status || 'completed');
      session().setCurrentTaskId(doneData.task_id || null);

      // 更新意图信息 (S 层)
      if (doneData.intent) {
        session().setLastIntent({
          type: doneData.intent.type,
          confidence: doneData.intent.confidence,
          method: doneData.intent.method || 'llm',
          entities: doneData.intent.entities,
        });
        session().setSLayerIntent(doneData.intent.type);
      }

      // 更新链路追踪 (chain_trace)
      if (doneData.chain_trace) {
        chain().setChainTrace(doneData.chain_trace as unknown as ChainTrace);
      }

      // 将最终内容写入流式输出
      if (doneData.content) {
        // 如果之前没有流式内容(text_delta),直接设置完整内容
        const currentContent = session().streamingContent;
        if (!currentContent) {
          session().setStreaming(true, doneData.content);
        }
      }

      // 最终化流式输出
      const sessionId = session().activeSessionId;
      if (sessionId) {
        // 如果没有流式内容但有 content,用它作为消息内容
        const finalContent = session().streamingContent || doneData.content || '';
        if (finalContent && !session().streamingContent) {
          session().setStreaming(true, finalContent);
        }
        session().finalizeStreaming(sessionId);
      }

      // 设置报告引用
      if (doneData.task_id) {
        session().setLastReportId(doneData.task_id);
      }

      // 监控事件
      monitor().addEvent('G', {
        id: `evt_${Date.now()}`,
        layer: 'G',
        type: 'task_completed',
        description: `任务完成: ${doneData.task_id || ''} | 耗时: ${doneData.execution_time_ms || 0}ms`,
        timestamp: Date.now(),
        duration: doneData.execution_time_ms,
      });

      // 回调
      options?.onDone?.(doneData);
    },

    error: (data) => {
      const errorMsg = (data as any).error || (data as any).message || '未知错误';
      session().setStreaming(false, '');
      session().setLastTaskStatus('error');
      monitor().setSSEStatus('error');
      monitor().addEvent('C', {
        id: `evt_${Date.now()}`,
        layer: 'C',
        type: 'error',
        description: errorMsg,
        timestamp: Date.now(),
      });
      options?.onError?.(new Error(errorMsg));
    },
  };
}

// === 任务完成事件数据结构 ===
export interface TaskDoneData {
  task_id: string;
  status: string;
  intent: {
    type: string;
    confidence: number;
    method?: string;
    entities?: Record<string, unknown>;
  };
  thinking_mode?: string;
  content?: string;
  content_type?: string;
  execution_time_ms?: number;
  artifacts_produced?: string[];
  execution_summary?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  chain_trace?: Record<string, unknown>;
  trade_requires_confirmation?: boolean;
}
