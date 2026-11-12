// ============================================
// Monitor Stream Manager — 监控流模块单例（EventSource）
// ============================================
//
// 为什么需要它：
//   原先有 3 处各自 new EventSource('/api/monitor/stream')
//   （use-monitor-data / useProactiveSSE / useArchMapLive），
//   同时打开多个页面会出现多条重复连接。收口为模块单例后，
//   浏览器端任意时刻最多 1 条 monitor SSE，订阅者共享同一条流。
//
// 契约（SPEC-20261111-A §3.3）：
//   1. 模块单例 EventSource，引用计数：首个订阅创建，最后一个退订关闭
//   2. 重连：指数退避 1s → 30s（带抖动），open 后重置；无订阅不重连
//   3. 去重：按 event.id 维护最近 200 条 LRU，重复事件不再分发
//   4. 分发：先分发给订阅者，由订阅者决定是否写 store
//   5. SSR 安全

export interface MonitorStreamEvent {
  type?: string;
  id?: string;
  trace_id?: string;
  uid?: string;
  timestamp?: string;
  layer?: string;
  phase?: string;
  status?: string;
  intent?: string;
  thinking_mode?: string;
  chain?: string[];
  duration_ms?: number;
  error?: string;
  artifact_file?: string;
  message_preview?: string;
  extra?: Record<string, unknown>;
  [k: string]: unknown;
}

export type MonitorHandler = (event: MonitorStreamEvent) => void;
export type MonitorStreamStatus = 'idle' | 'connecting' | 'open' | 'reconnecting';
export type MonitorStatusHandler = (status: MonitorStreamStatus) => void;

const STREAM_URL = '/api/monitor/stream';
const DEDUPE_LIMIT = 200;
const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;

const subscribers = new Set<MonitorHandler>();
const statusListeners = new Set<MonitorStatusHandler>();
const seen = new Set<string>();
const seenOrder: string[] = [];

let source: EventSource | null = null;
let status: MonitorStreamStatus = 'idle';
let retry = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function setStatus(next: MonitorStreamStatus) {
  if (status === next) return;
  status = next;
  for (const listener of Array.from(statusListeners)) {
    try {
      listener(next);
    } catch {
      // 单个订阅者异常不影响其他订阅者
    }
  }
}

function remember(id: string): boolean {
  if (seen.has(id)) return false;
  seen.add(id);
  seenOrder.push(id);
  if (seenOrder.length > DEDUPE_LIMIT) {
    const oldest = seenOrder.shift();
    if (oldest) seen.delete(oldest);
  }
  return true;
}

function dispatch(event: MonitorStreamEvent) {
  for (const handler of Array.from(subscribers)) {
    try {
      handler(event);
    } catch {
      // 单个订阅者异常不影响其他订阅者
    }
  }
}

function connect() {
  if (typeof window === 'undefined') return;
  if (source) return;
  if (subscribers.size === 0) return;

  setStatus(retry === 0 ? 'connecting' : 'reconnecting');

  let es: EventSource;
  try {
    es = new EventSource(STREAM_URL);
  } catch {
    scheduleReconnect();
    return;
  }
  source = es;

  es.onopen = () => {
    retry = 0;
    setStatus('open');
  };

  es.onmessage = (msg: MessageEvent) => {
    let event: MonitorStreamEvent;
    try {
      event = JSON.parse(msg.data) as MonitorStreamEvent;
    } catch {
      return;
    }
    // 跳过系统消息
    if (event.type === 'connected' || event.type === 'system') return;
    if (event.id && !remember(event.id)) return;
    dispatch(event);
  };

  es.onerror = () => {
    es.close();
    if (source === es) source = null;
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  if (subscribers.size === 0) return;
  if (reconnectTimer) return;

  const delay = Math.min(BASE_DELAY_MS * 2 ** retry, MAX_DELAY_MS) + Math.random() * 500;
  retry += 1;
  setStatus('reconnecting');
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function teardown() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (source) {
    source.close();
    source = null;
  }
  retry = 0;
  setStatus('idle');
}

/**
 * 订阅 monitor 流事件。返回退订函数（引用计数归零时关闭连接）。
 */
export function subscribeMonitor(handler: MonitorHandler): () => void {
  subscribers.add(handler);
  connect();

  return () => {
    subscribers.delete(handler);
    if (subscribers.size === 0) teardown();
  };
}

/**
 * 订阅连接状态变化（供 UI 展示 connecting/open/reconnecting）。
 */
export function subscribeMonitorStatus(handler: MonitorStatusHandler): () => void {
  statusListeners.add(handler);
  return () => {
    statusListeners.delete(handler);
  };
}

export function getMonitorStatus(): MonitorStreamStatus {
  return status;
}
