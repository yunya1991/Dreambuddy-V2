/**
 * task-stream-manager — 单例替换 / 显式终止 / 错误入 store / SSR 安全
 * SPEC-20261111-A §3.2 行为契约
 */

const closeFns: jest.Mock[] = [];

jest.mock('@/lib/sse-client', () => ({
  createSSEConnection: jest.fn(() => {
    const close = jest.fn();
    closeFns.push(close);
    return { close, readyState: 0 };
  }),
}));

jest.mock('@/lib/sse-dispatcher', () => ({
  createTaskStreamHandlers: jest.fn(() => ({})),
}));

const REQ = {
  message: '分析BTC',
  session_id: 'sess_test',
  thinking_mode: 'deep' as const,
};

function load() {
  const manager = require('@/lib/stream/task-stream-manager') as typeof import('@/lib/stream/task-stream-manager');
  const sseClient = require('@/lib/sse-client') as typeof import('@/lib/sse-client');
  const dispatcher = require('@/lib/sse-dispatcher') as typeof import('@/lib/sse-dispatcher');
  const { useSessionStore } = require('@/stores/session-store') as typeof import('@/stores/session-store');
  return { ...manager, sseClient, dispatcher, useSessionStore };
}

describe('task-stream-manager', () => {
  beforeEach(() => {
    jest.resetModules();
    closeFns.length = 0;
  });

  it('startTaskStream 会先终止上一条流，同一时刻只有 1 条', () => {
    const { startTaskStream, isTaskStreaming, sseClient } = load();
    const create = sseClient.createSSEConnection as unknown as jest.Mock;

    startTaskStream(REQ);
    expect(create).toHaveBeenCalledTimes(1);
    expect(isTaskStreaming()).toBe(true);

    startTaskStream({ ...REQ, message: '第二条' });
    expect(create).toHaveBeenCalledTimes(2);
    expect(closeFns[0]).toHaveBeenCalledTimes(1);
    expect(closeFns[1]).not.toHaveBeenCalled();
  });

  it('abortTaskStream 关闭连接并复位流状态', () => {
    const { startTaskStream, abortTaskStream, isTaskStreaming } = load();

    startTaskStream(REQ);
    abortTaskStream();
    expect(closeFns[0]).toHaveBeenCalledTimes(1);
    expect(isTaskStreaming()).toBe(false);
  });

  it('错误回调写入 session-store.lastTaskError 并停止流', () => {
    const { startTaskStream, isTaskStreaming, dispatcher, useSessionStore } = load();

    startTaskStream(REQ);
    const opts = (dispatcher.createTaskStreamHandlers as unknown as jest.Mock).mock.calls[0][0] as {
      onError?: (err: Error) => void;
    };
    opts.onError?.(new Error('stream_failed'));

    expect(useSessionStore.getState().lastTaskError).toBe('stream_failed');
    expect(isTaskStreaming()).toBe(false);
  });

  it('onDone 后流状态复位且不写错误', () => {
    const { startTaskStream, isTaskStreaming, dispatcher } = load();

    startTaskStream(REQ);
    const opts = (dispatcher.createTaskStreamHandlers as unknown as jest.Mock).mock.calls[0][0] as {
      onDone?: (data?: unknown) => void;
    };
    opts.onDone?.({ task_id: 't1' });

    expect(isTaskStreaming()).toBe(false);
  });

  it('SSR 安全：window 不存在时不创建连接', () => {
    const { startTaskStream, isTaskStreaming, sseClient } = load();
    const create = sseClient.createSSEConnection as unknown as jest.Mock;

    const savedWindow = (globalThis as { window?: unknown }).window;
    delete (globalThis as { window?: unknown }).window;
    try {
      startTaskStream(REQ);
      expect(create).not.toHaveBeenCalled();
      expect(isTaskStreaming()).toBe(false);
    } finally {
      (globalThis as { window?: unknown }).window = savedWindow;
    }
  });
});
