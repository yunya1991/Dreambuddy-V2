// ============================================
// Task Stream Manager — 任务流模块单例（POST SSE）
// ============================================
//
// 为什么需要它：
//   原先 /api/task/stream 连接由 ChatPanel 组件持有，组件卸载即 close()，
//   切页会中断正在执行的任务流。改为模块单例后，连接与组件生命周期解耦，
//   页面切换只影响「谁在渲染」，不影响「流是否继续」。
//
// 契约（SPEC-20261111-A §3.2）：
//   1. startTaskStream 先 abort 旧连接 —— 同一时刻只有 1 条任务流
//   2. 复用 sse-client / sse-dispatcher，不重写协议映射
//   3. 完成/失败统一维护 session-store（setStreaming / lastTaskError）
//   4. 任务流禁止自动重连（重连会重复执行交易任务）
//   5. SSR 安全：window 不存在时直接返回
//   6. 页面卸载不关闭连接

import { createSSEConnection, type SSEConnection } from '@/lib/sse-client';
import { createTaskStreamHandlers } from '@/lib/sse-dispatcher';
import { useSessionStore } from '@/stores/session-store';

export interface TaskStreamRequest {
  message: string;
  session_id: string;
  thinking_mode?: 'deep' | 'fast';
  lang?: string;
  trading_mode?: string;
  l1_intent_hint?: string;
  /** 跨链 trace（入口生成，L1→L2 原样透传；禁止 L2 侧重新生成） */
  trace_id?: string;
}

export interface TaskStreamOptions {
  onDone?: (data?: unknown) => void;
  onError?: (err: Error) => void;
}

let connection: SSEConnection | null = null;
let streaming = false;
/** 连接代际：旧连接的回调不得影响新连接的状态 */
let generation = 0;

function fail(message: string) {
  useSessionStore.getState().setStreaming(false, '');
  useSessionStore.getState().setLastTaskError(message);
}

/**
 * 启动任务流（会自动终止上一条未完成的流）。
 */
export function startTaskStream(req: TaskStreamRequest, opts: TaskStreamOptions = {}): void {
  if (typeof window === 'undefined') return;

  abortTaskStream();
  useSessionStore.getState().setLastTaskError(null);

  const token = ++generation;
  const isCurrent = () => token === generation;
  streaming = true;

  const handlers = createTaskStreamHandlers({
    onDone: (data) => {
      if (!isCurrent()) return;
      connection = null;
      streaming = false;
      opts.onDone?.(data);
    },
    onError: (err) => {
      if (!isCurrent()) return;
      connection = null;
      streaming = false;
      useSessionStore.getState().setLastTaskError(err.message);
      opts.onError?.(err);
    },
  });

  connection = createSSEConnection('/api/task/stream', req, handlers, {
    onError: (err) => {
      if (!isCurrent()) return;
      connection = null;
      streaming = false;
      fail(err.message);
      opts.onError?.(err);
    },
  });
}

/**
 * 显式终止任务流（用户点「取消」时调用）；任务流不自动重连。
 */
export function abortTaskStream(): void {
  generation += 1;
  if (connection) {
    connection.close();
    connection = null;
  }
  streaming = false;
}

export function isTaskStreaming(): boolean {
  return streaming;
}
