'use client';

import { useEffect, useRef } from 'react';
import { useMonitorStore, useMemoryStore } from '@/stores';
import type { SACELayer, SACGLayerEvent } from '@/stores';
import api from '@/lib/api-client';

/**
 * useMonitorData — 监控页独立数据接入 hook
 *
 * 职责：
 * 1. 建立 /api/monitor/stream SSE 连接，接收 monitor-bus 真实事件
 * 2. 按 phase 语义将事件映射到 SACG 四层，写入 monitor-store
 * 3. 每 10s 轮询 /api/monitor/stats，更新 pipelineThroughput
 * 4. 断线自动重连（指数退避，最多 5 次）
 *
 * 与 AI 对话系统联动：
 * - 聊天任务通过 /api/task/stream SSE 更新 monitor-store（sse-dispatcher）
 * - 本 hook 通过 /api/monitor/stream SSE 补充 monitor-bus 全量事件
 * - 两者共享同一组 zustand stores，数据一致
 */

// phase → SACG 层映射（按语义）
const PHASE_TO_LAYER: Record<string, SACELayer> = {
  // S 感知层：意图识别、用户输入、澄清
  user_input: 'S',
  intent_recognized: 'S',
  recognized: 'S',
  fallback_rule: 'S',
  fallback_default: 'S',
  rule_follow_up: 'S',
  clarification_requested: 'S',
  clarification_sent: 'S',
  low_confidence_clarification: 'S',
  non_financial_skip: 'S',
  jev_evaluated: 'S',
  // A 编排层：链路选择、任务创建、路由
  routed: 'A',
  chain_started: 'A',
  task_created: 'A',
  async_spawned: 'A',
  // C 执行层：内联执行、交易、workbuddy 处理
  inline_exec_start: 'C',
  inline_exec_done: 'C',
  trade_pending: 'C',
  wb_received: 'C',
  wb_processing: 'C',
  wb_completed: 'C',
  wb_failed: 'C',
  // G 存储层：产物同步、索引、情报
  artifact_synced: 'G',
  index_updated: 'G',
  feed_ready: 'G',
  result_displayed: 'G',
};

function mapPhaseToLayer(phase: string): SACELayer {
  return PHASE_TO_LAYER[phase] || 'C';
}

interface MonitorStreamEvent {
  id: string;
  trace_id: string;
  uid: string;
  timestamp: string;
  layer: string;
  phase: string;
  status: string;
  intent?: string;
  thinking_mode?: string;
  chain?: string[];
  duration_ms?: number;
  error?: string;
  artifact_file?: string;
  message_preview?: string;
  type?: string;
}

export function useMonitorData() {
  const esRef = useRef<EventSource | null>(null);
  const reconnectCountRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    const connect = () => {
      if (!mountedRef.current) return;

      useMonitorStore.getState().setSSEStatus('connecting');

      let es: EventSource;
      try {
        es = new EventSource('/api/monitor/stream');
      } catch {
        scheduleReconnect();
        return;
      }
      esRef.current = es;

      es.onopen = () => {
        reconnectCountRef.current = 0;
        useMonitorStore.getState().setSSEStatus('connected');
      };

      es.onmessage = (e: MessageEvent) => {
        try {
          const event = JSON.parse(e.data) as MonitorStreamEvent;
          // 跳过系统消息
          if (event.type === 'connected' || event.type === 'system') return;

          const layer = mapPhaseToLayer(event.phase);
          const storeEvent: SACGLayerEvent = {
            id: event.id || `evt_${Date.now()}`,
            layer,
            type: event.phase,
            description: event.message_preview || `${event.phase}: ${event.status}`,
            timestamp: event.timestamp ? new Date(event.timestamp).getTime() : Date.now(),
            duration: event.duration_ms,
          };
          useMonitorStore.getState().addEvent(layer, storeEvent);
        } catch {
          // 忽略解析错误
        }
      };

      es.onerror = () => {
        useMonitorStore.getState().setSSEStatus('error');
        es.close();
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (!mountedRef.current) return;
      if (reconnectCountRef.current >= 5) {
        useMonitorStore.getState().setSSEStatus('disconnected');
        return;
      }
      const delay = Math.pow(2, reconnectCountRef.current) * 1000;
      reconnectCountRef.current += 1;
      reconnectTimerRef.current = setTimeout(connect, delay);
    };

    // 轮询监控统计
    const fetchStats = async () => {
      try {
        const data = await api.get<{
          stats: {
            total_requests: number;
            total_completed: number;
            total_failed: number;
            success_rate: number;
            avg_duration_ms: number;
            active_traces: number;
          };
        }>('/api/monitor/stats');
        if (data?.stats && mountedRef.current) {
          const s = data.stats;
          useMonitorStore.getState().setThroughput({
            totalProcessed: s.total_requests,
            successRate: s.success_rate / 100,
            avgLatencyMs: s.avg_duration_ms,
            activeCount: s.active_traces,
          });
        }
      } catch {
        // 静默失败
      }
    };

    connect();
    fetchStats();
    pollTimerRef.current = setInterval(fetchStats, 10000);

    // 拉取认知系统 BAC 压缩统计（/api/cognitive/stats）
    useMemoryStore.getState().fetchStats();

    return () => {
      mountedRef.current = false;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, []);
}
