/**
 * Monitor Bus — 信息传递监控事件总线
 * v1.0 | 2026-05-14
 *
 * 架构：
 *   EventEmitter 单例 + RingBuffer(500) + uid 隔离
 *   生产者：task-manager / chat route / task route
 *   消费者：SSE stream / REST 查询
 *
 * 并发安全：
 *   - RingBuffer 固定内存，不随用户数增长
 *   - SSE 连接上限 30，超限降级轮询
 *   - 事件发射为非阻塞（synchronous emit，但不 await）
 */

import { EventEmitter } from 'events';

// ============================================================
// 类型定义
// ============================================================

export type MonitorLayer = 'frontend' | 'gateway' | 'artifact_hub' | 'workbuddy' | 'intent' | 'router';
export type MonitorStatus = 'received' | 'processing' | 'completed' | 'failed' | 'timeout' | 'denied';
export type MonitorPhase =
  | 'user_input'
  | 'intent_recognized'
  | 'recognized'
  | 'fallback_rule'
  | 'fallback_default'
  | 'rule_follow_up'
  | 'routed'
  | 'chain_started'
  | 'task_created'
  | 'inline_exec_start'
  | 'inline_exec_done'
  | 'async_spawned'
  | 'trade_pending'
  | 'wb_received'
  | 'wb_processing'
  | 'wb_completed'
  | 'wb_failed'
  | 'artifact_synced'
  | 'index_updated'
  | 'feed_ready'
  | 'result_displayed';

export interface MonitorEvent {
  id: string;
  trace_id: string;           // 全链路追踪ID (= task_id)
  uid: string;                 // 用户ID
  timestamp: string;           // ISO8601

  layer: MonitorLayer;
  phase: MonitorPhase;
  status: MonitorStatus;

  // 上下文
  intent?: string;
  thinking_mode?: string;
  chain?: string[];
  duration_ms?: number;
  error?: string;
  artifact_file?: string;
  message_preview?: string;   // 用户消息前50字
}

export interface MonitorStats {
  total_requests: number;
  total_completed: number;
  total_failed: number;
  total_timeout: number;
  success_rate: number;        // 0-100
  avg_duration_ms: number;
  intent_distribution: Record<string, number>;
  layer_status: {
    frontend: { total: number; completed: number; failed: number };
    gateway: { total: number; completed: number; failed: number };
    workbuddy: { total: number; completed: number; failed: number };
    artifact_hub: { total: number; completed: number; failed: number };
  };
  active_traces: number;      // 进行中的trace数
}

export interface SSEConnection {
  id: string;
  uid: string;
  controller: ReadableStreamDefaultController;
  connectedAt: number;
}

// ============================================================
// RingBuffer 实现
// ============================================================

class RingBuffer<T> {
  private buffer: (T | undefined)[];
  private head = 0;      // 下一个写入位置
  private count = 0;     // 当前元素数
  private readonly capacity: number;

  constructor(capacity: number) {
    this.capacity = capacity;
    this.buffer = new Array(capacity);
  }

  push(item: T): void {
    this.buffer[this.head] = item;
    this.head = (this.head + 1) % this.capacity;
    if (this.count < this.capacity) {
      this.count++;
    }
  }

  /**
   * 返回按时间顺序的数组（最新在后）
   */
  toArray(): T[] {
    const result: T[] = [];
    if (this.count < this.capacity) {
      // 还没绕一圈
      for (let i = 0; i < this.count; i++) {
        const item = this.buffer[i];
        if (item !== undefined) result.push(item);
      }
    } else {
      // 绕了一圈，head之后的是最旧的
      for (let i = this.head; i < this.capacity; i++) {
        const item = this.buffer[i];
        if (item !== undefined) result.push(item);
      }
      for (let i = 0; i < this.head; i++) {
        const item = this.buffer[i];
        if (item !== undefined) result.push(item);
      }
    }
    return result;
  }

  /**
   * 按条件过滤返回（最新在前）
   */
  filter(predicate: (item: T) => boolean, limit?: number): T[] {
    const all = this.toArray();
    const filtered = all.filter(predicate);
    // 翻转为最新在前
    filtered.reverse();
    return limit ? filtered.slice(0, limit) : filtered;
  }

  get size(): number {
    return this.count;
  }
}

// ============================================================
// Monitor Bus 单例
// ============================================================

const BUS_EVENT = 'monitor:event';
const MAX_SSE_CONNECTIONS = 30;
const SSE_TIMEOUT_MS = 30 * 60 * 1000; // 30分钟

class MonitorBus extends EventEmitter {
  private ringBuffer: RingBuffer<MonitorEvent>;
  private sseConnections: Map<string, SSEConnection> = new Map();
  private statsAccumulator: {
    totalRequests: number;
    totalCompleted: number;
    totalFailed: number;
    totalTimeout: number;
    totalDurationMs: number;
    durationCount: number;
    intentDist: Record<string, number>;
    layerCounts: Record<MonitorLayer, { total: number; completed: number; failed: number }>;
    activeTraces: Set<string>;
  };

  constructor() {
    super();
    this.ringBuffer = new RingBuffer<MonitorEvent>(500);
    this.statsAccumulator = {
      totalRequests: 0,
      totalCompleted: 0,
      totalFailed: 0,
      totalTimeout: 0,
      totalDurationMs: 0,
      durationCount: 0,
      intentDist: {},
      layerCounts: {
        frontend: { total: 0, completed: 0, failed: 0 },
        gateway: { total: 0, completed: 0, failed: 0 },
        workbuddy: { total: 0, completed: 0, failed: 0 },
        artifact_hub: { total: 0, completed: 0, failed: 0 },
        intent: { total: 0, completed: 0, failed: 0 },
        router: { total: 0, completed: 0, failed: 0 },
      },
      activeTraces: new Set(),
    };

    // 监听自身事件，更新统计
    this.on(BUS_EVENT, (event: MonitorEvent) => {
      this.updateStats(event);
    });
  }

  // ---- 生产者 API ----

  /**
   * 发射监控事件（非阻塞）
   */
  emitMonitorEvent(event: Omit<MonitorEvent, 'id' | 'timestamp'>): MonitorEvent {
    const fullEvent: MonitorEvent = {
      ...event,
      id: `evt_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      timestamp: new Date().toISOString(),
    };

    // 写入 RingBuffer
    this.ringBuffer.push(fullEvent);

    // 更新统计
    this.updateStats(fullEvent);

    // 通知 SSE 消费者
    this.emit(BUS_EVENT, fullEvent);

    // 推送给匹配的 SSE 连接
    this.pushToSSEClients(fullEvent);

    return fullEvent;
  }

  // ---- 消费者 API ----

  /**
   * 获取最近事件
   */
  getRecentEvents(options?: {
    uid?: string;
    layer?: MonitorLayer;
    trace_id?: string;
    limit?: number;
  }): MonitorEvent[] {
    const { uid, layer, trace_id, limit = 50 } = options || {};

    return this.ringBuffer.filter((e) => {
      if (uid && e.uid !== uid) return false;
      if (layer && e.layer !== layer) return false;
      if (trace_id && e.trace_id !== trace_id) return false;
      return true;
    }, limit);
  }

  /**
   * 获取统计
   */
  getStats(uid?: string): MonitorStats {
    const acc = this.statsAccumulator;

    // 如果指定uid，从ring buffer重新计算
    if (uid) {
      const userEvents = this.ringBuffer.filter(e => e.uid === uid);
      return this.calculateStats(userEvents);
    }

    return {
      total_requests: acc.totalRequests,
      total_completed: acc.totalCompleted,
      total_failed: acc.totalFailed,
      total_timeout: acc.totalTimeout,
      success_rate: acc.totalRequests > 0
        ? Math.min(100, Math.round((acc.totalCompleted / acc.totalRequests) * 100))
        : 0,
      avg_duration_ms: acc.durationCount > 0
        ? Math.round(acc.totalDurationMs / acc.durationCount)
        : 0,
      intent_distribution: { ...acc.intentDist },
      layer_status: {
        frontend: { ...acc.layerCounts.frontend },
        gateway: { ...acc.layerCounts.gateway },
        workbuddy: { ...acc.layerCounts.workbuddy },
        artifact_hub: { ...acc.layerCounts.artifact_hub },
      },
      active_traces: acc.activeTraces.size,
    };
  }

  /**
   * 获取全链路状态概览
   */
  getPipelineStatus(uid?: string): {
    frontend: { total: number; completed: number; rate: string };
    gateway: { total: number; completed: number; rate: string };
    workbuddy: { total: number; completed: number; rate: string };
    artifact_hub: { total: number; completed: number; rate: string };
  } {
    const stats = this.getStats(uid);
    const calcRate = (c: { total: number; completed: number }) =>
      c.total > 0 ? `${Math.round((c.completed / c.total) * 100)}%` : '--';

    return {
      frontend: { ...stats.layer_status.frontend, rate: calcRate(stats.layer_status.frontend) },
      gateway: { ...stats.layer_status.gateway, rate: calcRate(stats.layer_status.gateway) },
      workbuddy: { ...stats.layer_status.workbuddy, rate: calcRate(stats.layer_status.workbuddy) },
      artifact_hub: { ...stats.layer_status.artifact_hub, rate: calcRate(stats.layer_status.artifact_hub) },
    };
  }

  // ---- SSE 管理 ----

  /**
   * 注册 SSE 连接
   */
  registerSSE(uid: string, controller: ReadableStreamDefaultController): string | null {
    if (this.sseConnections.size >= MAX_SSE_CONNECTIONS) {
      console.warn(`[MonitorBus] SSE connections limit reached (${MAX_SSE_CONNECTIONS})`);
      return null; // 降级为轮询
    }

    const connId = `sse_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    this.sseConnections.set(connId, {
      id: connId,
      uid,
      controller,
      connectedAt: Date.now(),
    });

    console.log(`[MonitorBus] SSE connected: ${connId} (uid: ${uid}, total: ${this.sseConnections.size})`);
    return connId;
  }

  /**
   * 断开 SSE 连接
   */
  unregisterSSE(connId: string): void {
    this.sseConnections.delete(connId);
    console.log(`[MonitorBus] SSE disconnected: ${connId} (total: ${this.sseConnections.size})`);
  }

  /**
   * 获取 SSE 连接数
   */
  get sseConnectionCount(): number {
    return this.sseConnections.size;
  }

  /**
   * 清理超时 SSE 连接
   */
  cleanupStaleSSE(): number {
    const now = Date.now();
    let cleaned = 0;
    for (const [connId, conn] of this.sseConnections) {
      if (now - conn.connectedAt > SSE_TIMEOUT_MS) {
        try { conn.controller.close(); } catch {}
        this.sseConnections.delete(connId);
        cleaned++;
      }
    }
    return cleaned;
  }

  // ---- 内部方法 ----

  private updateStats(event: MonitorEvent): void {
    const acc = this.statsAccumulator;

    // 请求计数（user_input 为新请求）
    if (event.phase === 'user_input') {
      acc.totalRequests++;
      acc.activeTraces.add(event.trace_id);
    }

    // 完成计数
    if (event.status === 'completed') {
      acc.totalCompleted++;
      if (event.phase === 'result_displayed' || event.phase === 'inline_exec_done' || event.phase === 'wb_completed') {
        acc.activeTraces.delete(event.trace_id);
      }
    }

    if (event.status === 'failed') {
      acc.totalFailed++;
      acc.activeTraces.delete(event.trace_id);
    }

    if (event.status === 'timeout') {
      acc.totalTimeout++;
      acc.activeTraces.delete(event.trace_id);
    }

    // 耗时
    if (event.duration_ms) {
      acc.totalDurationMs += event.duration_ms;
      acc.durationCount++;
    }

    // 意图分布
    if (event.intent) {
      acc.intentDist[event.intent] = (acc.intentDist[event.intent] || 0) + 1;
    }

    // 层级计数
    const layerStats = acc.layerCounts[event.layer];
    if (layerStats) {
      layerStats.total++;
      if (event.status === 'completed') layerStats.completed++;
      if (event.status === 'failed') layerStats.failed++;
    }
  }

  private pushToSSEClients(event: MonitorEvent): void {
    const data = JSON.stringify(event);
    for (const [connId, conn] of this.sseConnections) {
      // uid 过滤：只推送给相关用户
      if (conn.uid && conn.uid !== event.uid) continue;

      try {
        conn.controller.enqueue(`data: ${data}\n\n`);
      } catch {
        // 连接已断开
        this.sseConnections.delete(connId);
      }
    }
  }

  private calculateStats(events: MonitorEvent[]): MonitorStats {
    let totalRequests = 0;
    let totalCompleted = 0;
    let totalFailed = 0;
    let totalTimeout = 0;
    let totalDurationMs = 0;
    let durationCount = 0;
    const intentDist: Record<string, number> = {};
    const layerCounts: Record<MonitorLayer, { total: number; completed: number; failed: number }> = {
      frontend: { total: 0, completed: 0, failed: 0 },
      gateway: { total: 0, completed: 0, failed: 0 },
      workbuddy: { total: 0, completed: 0, failed: 0 },
      artifact_hub: { total: 0, completed: 0, failed: 0 },
      intent: { total: 0, completed: 0, failed: 0 },
      router: { total: 0, completed: 0, failed: 0 },
    };
    const activeTraces = new Set<string>();

    for (const e of events) {
      if (e.phase === 'user_input') totalRequests++;
      if (e.status === 'completed') totalCompleted++;
      if (e.status === 'failed') totalFailed++;
      if (e.status === 'timeout') totalTimeout++;
      if (e.duration_ms) { totalDurationMs += e.duration_ms; durationCount++; }
      if (e.intent) intentDist[e.intent] = (intentDist[e.intent] || 0) + 1;
      const ls = layerCounts[e.layer];
      if (ls) {
        ls.total++;
        if (e.status === 'completed') ls.completed++;
        if (e.status === 'failed') ls.failed++;
      }
      if (e.status === 'processing') activeTraces.add(e.trace_id);
      else if (e.status === 'completed' || e.status === 'failed') activeTraces.delete(e.trace_id);
    }

    return {
      total_requests: totalRequests,
      total_completed: totalCompleted,
      total_failed: totalFailed,
      total_timeout: totalTimeout,
      success_rate: totalRequests > 0 ? Math.round((totalCompleted / totalRequests) * 100) : 0,
      avg_duration_ms: durationCount > 0 ? Math.round(totalDurationMs / durationCount) : 0,
      intent_distribution: intentDist,
      layer_status: layerCounts,
      active_traces: activeTraces.size,
    };
  }
}

// ============================================================
// 导出单例
// ============================================================

const monitorBus = new MonitorBus();
export default monitorBus;

// 便捷函数（不 import 单例也能用）
export function emitMonitorEvent(event: Omit<MonitorEvent, 'id' | 'timestamp'>): MonitorEvent {
  return monitorBus.emitMonitorEvent(event);
}

export function getRecentEvents(options?: {
  uid?: string;
  layer?: MonitorLayer;
  trace_id?: string;
  limit?: number;
}): MonitorEvent[] {
  return monitorBus.getRecentEvents(options);
}

export function getMonitorStats(uid?: string): MonitorStats {
  return monitorBus.getStats(uid);
}

export function getPipelineStatus(uid?: string) {
  return monitorBus.getPipelineStatus(uid);
}
