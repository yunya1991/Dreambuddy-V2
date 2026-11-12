'use client';

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useMonitorStore, useMemoryStore } from '@/stores';
import type { SACELayer, SACGLayerEvent } from '@/stores';
import api from '@/lib/api-client';
import { queryKey, queryStaleTime } from '@/lib/query-keys';
import {
  subscribeMonitor,
  subscribeMonitorStatus,
  type MonitorStreamEvent,
  type MonitorStreamStatus,
} from '@/lib/stream/monitor-stream-manager';

/**
 * useMonitorData — 监控页独立数据接入 hook
 *
 * 职责：
 * 1. 订阅 monitor-stream-manager 单例流（/api/monitor/stream），不自己持有连接
 * 2. 按 phase 语义将事件映射到 SACG 四层，写入 monitor-store
 * 3. 每 10s 轮询 /api/monitor/stats，更新 pipelineThroughput
 *
 * 与 AI 对话系统联动：
 * - 聊天任务通过 /api/task/stream SSE 更新 monitor-store（sse-dispatcher）
 * - 本 hook 通过 monitor-stream-manager 补充 monitor-bus 全量事件
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

function mapStreamStatus(s: MonitorStreamStatus): 'disconnected' | 'connecting' | 'connected' | 'error' {
  if (s === 'open') return 'connected';
  if (s === 'connecting') return 'connecting';
  if (s === 'reconnecting') return 'error';
  return 'disconnected';
}

interface MonitorStatsResponse {
  stats: {
    total_requests: number;
    total_completed: number;
    total_failed: number;
    success_rate: number;
    avg_duration_ms: number;
    active_traces: number;
  };
}

export function useMonitorData() {
  // 统计轮询（10s）交由 react-query 托管：去重、共享缓存、卸载即停
  const statsQuery = useQuery({
    queryKey: queryKey('monitor', 'stats'),
    queryFn: () => api.get<MonitorStatsResponse>('/api/monitor/stats'),
    staleTime: queryStaleTime('monitor'),
    refetchInterval: 10_000,
    retry: false, // 静默失败，保留上次成功数据
  });

  // 统计数据写入 monitor-store
  useEffect(() => {
    const s = statsQuery.data?.stats;
    if (!s) return;
    useMonitorStore.getState().setThroughput({
      totalProcessed: s.total_requests,
      successRate: s.success_rate / 100,
      avgLatencyMs: s.avg_duration_ms,
      activeCount: s.active_traces,
    });
  }, [statsQuery.data]);

  useEffect(() => {
    // 订阅单例流：多页面共享同一条 EventSource
    const unsubscribe = subscribeMonitor((event: MonitorStreamEvent) => {
      const phase = event.phase || '';
      const layer = mapPhaseToLayer(phase);
      const storeEvent: SACGLayerEvent = {
        id: event.id || `evt_${Date.now()}`,
        layer,
        type: phase,
        description: event.message_preview || `${phase}: ${event.status}`,
        timestamp: event.timestamp ? new Date(event.timestamp).getTime() : Date.now(),
        duration: event.duration_ms,
      };
      useMonitorStore.getState().addEvent(layer, storeEvent);
    });

    const unsubscribeStatus = subscribeMonitorStatus((s) => {
      useMonitorStore.getState().setSSEStatus(mapStreamStatus(s));
    });

    // 拉取认知系统 BAC 压缩统计（/api/cognitive/stats）
    useMemoryStore.getState().fetchStats();

    return () => {
      unsubscribe();
      unsubscribeStatus();
    };
  }, []);
}
