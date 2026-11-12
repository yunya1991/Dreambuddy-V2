/**
 * sse-client.test.ts — T-C3 接入层：id 去重 / 心跳 / lastEventId
 * 既有 10 类交易事件分发语义保持不变。
 */

import { createSSEConnection, type SSEEventMeta } from '@/lib/sse-client';

// jsdom 环境缺少 TextEncoder/TextDecoder/ReadableStream，用 Node 内置实现补齐
/* eslint-disable @typescript-eslint/no-var-requires */
const globals = globalThis as unknown as Record<string, unknown>;
if (typeof globals.TextEncoder === 'undefined') {
  globals.TextEncoder = (require('node:util') as typeof import('node:util')).TextEncoder;
}
if (typeof globals.TextDecoder === 'undefined') {
  globals.TextDecoder = (require('node:util') as typeof import('node:util')).TextDecoder;
}
if (typeof globals.ReadableStream === 'undefined') {
  globals.ReadableStream = (require('node:stream/web') as typeof import('node:stream/web')).ReadableStream;
}
/* eslint-enable @typescript-eslint/no-var-requires */

let fetchMock: jest.Mock;

function streamResponse(frames: string[]) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  });
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: { get: () => null },
    body: stream,
  };
}

/** 等待流消费完毕 */
function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

beforeAll(() => {
  fetchMock = jest.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

beforeEach(() => {
  fetchMock.mockReset();
});

describe('sse-client: v1 id 去重', () => {
  it('相同 id 的帧只分发一次', async () => {
    fetchMock.mockResolvedValueOnce(
      streamResponse([
        'id: e1\nevent: thinking\ndata: {"content":"a"}\n\n',
        'id: e1\nevent: thinking\ndata: {"content":"a"}\n\n',
      ]),
    );

    const thinking = jest.fn();
    createSSEConnection('/api/stream', {}, { thinking });
    await flush();

    expect(thinking).toHaveBeenCalledTimes(1);
  });

  it('无 id 的旧帧不去重（同内容两次都分发）', async () => {
    fetchMock.mockResolvedValueOnce(
      streamResponse([
        'event: thinking\ndata: {"content":"a"}\n\n',
        'event: thinking\ndata: {"content":"a"}\n\n',
      ]),
    );

    const thinking = jest.fn();
    createSSEConnection('/api/stream', {}, { thinking });
    await flush();

    expect(thinking).toHaveBeenCalledTimes(2);
  });

  it('dedupeById=false 时相同 id 也分发两次', async () => {
    fetchMock.mockResolvedValueOnce(
      streamResponse([
        'id: e1\nevent: thinking\ndata: {"content":"a"}\n\n',
        'id: e1\nevent: thinking\ndata: {"content":"a"}\n\n',
      ]),
    );

    const thinking = jest.fn();
    createSSEConnection('/api/stream', {}, { thinking }, { dedupeById: false });
    await flush();

    expect(thinking).toHaveBeenCalledTimes(2);
  });
});

describe('sse-client: 心跳与元数据', () => {
  it(': ping 不触发任何 handler，但上报 heartbeat 元数据', async () => {
    fetchMock.mockResolvedValueOnce(streamResponse([': ping\n\n']));

    const thinking = jest.fn();
    const done = jest.fn();
    const meta: SSEEventMeta[] = [];
    createSSEConnection('/api/stream', {}, { thinking, done }, { onEventMeta: (m) => meta.push(m) });
    await flush();

    expect(thinking).not.toHaveBeenCalled();
    expect(done).not.toHaveBeenCalled();
    expect(meta).toContainEqual({ heartbeat: true, lastEventId: undefined });
  });

  it('lastEventId 随成功分发的 id 更新，并解析 retry', async () => {
    fetchMock.mockResolvedValueOnce(
      streamResponse(['id: e7\nretry: 3000\nevent: thinking\ndata: {"content":"x"}\n\n']),
    );

    const meta: SSEEventMeta[] = [];
    createSSEConnection('/api/stream', {}, { thinking: jest.fn() }, { onEventMeta: (m) => meta.push(m) });
    await flush();

    expect(meta).toContainEqual({ id: 'e7', retry: 3000, lastEventId: 'e7' });
  });
});

describe('sse-client: 既有行为不变', () => {
  it('无 id 的旧事件仍正常分发到对应 handler', async () => {
    fetchMock.mockResolvedValueOnce(
      streamResponse([
        'event: started\ndata: {"chainId":"c1","chainName":"n","chainType":"t","totalSteps":1}\n\n',
        'event: text_delta\ndata: {"delta":"hi"}\n\n',
        'event: done\ndata: {"chainId":"c1","totalTokens":1,"duration":10}\n\n',
      ]),
    );

    const started = jest.fn();
    const textDelta = jest.fn();
    const done = jest.fn();
    createSSEConnection('/api/stream', {}, { started, text_delta: textDelta, done });
    await flush();

    expect(started).toHaveBeenCalledTimes(1);
    expect(textDelta).toHaveBeenCalledWith({ delta: 'hi' });
    expect(done).toHaveBeenCalledTimes(1);
  });

  it('HTTP 非 2xx 触发 error handler', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      headers: { get: () => null },
      body: null,
    });

    const error = jest.fn();
    createSSEConnection('/api/stream', {}, { error });
    await flush();

    expect(error).toHaveBeenCalledWith(expect.objectContaining({ code: 500, recoverable: false }));
  });
});
