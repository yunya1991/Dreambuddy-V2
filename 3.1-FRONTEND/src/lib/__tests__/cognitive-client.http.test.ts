import { EventEmitter } from 'node:events';
import { waitFor } from '@testing-library/react';

jest.mock('child_process', () => ({ spawn: jest.fn() }));

import { spawn } from 'child_process';
import { callCognitive } from '../cognitive-client';

type FakeChild = EventEmitter & {
  stdout: EventEmitter;
  stderr: EventEmitter;
  kill: jest.Mock;
};

function makeChild(): FakeChild {
  const child = new EventEmitter() as FakeChild;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = jest.fn();
  return child;
}

function fakeResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

describe('cognitive-client 传输选择 (T-C5)', () => {
  const originalFetch = globalThis.fetch;
  const originalBase = process.env.COGNITIVE_API_BASE;
  const spawnMock = spawn as unknown as jest.Mock;

  beforeEach(() => {
    spawnMock.mockReset();
    delete process.env.COGNITIVE_API_BASE;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    if (originalBase === undefined) delete process.env.COGNITIVE_API_BASE;
    else process.env.COGNITIVE_API_BASE = originalBase;
  });

  it('配置 COGNITIVE_API_BASE 时走 HTTP，不 spawn', async () => {
    process.env.COGNITIVE_API_BASE = 'http://127.0.0.1:9999/';
    globalThis.fetch = jest.fn().mockResolvedValue(
      fakeResponse(200, { ok: true, data: { hits: 2 } }),
    ) as unknown as typeof fetch;

    const result = await callCognitive<{ hits: number }>('recall', { context: 'x' });

    expect(result).toEqual({ ok: true, data: { hits: 2 } });
    expect(spawnMock).not.toHaveBeenCalled();
    expect((globalThis.fetch as jest.Mock).mock.calls[0][0]).toBe(
      'http://127.0.0.1:9999/cognitive/recall',
    );
  });

  it('上游返回非 JSON 时按裸数据包装', async () => {
    process.env.COGNITIVE_API_BASE = 'http://upstream';
    globalThis.fetch = jest.fn().mockResolvedValue(
      fakeResponse(200, { memories: [] }),
    ) as unknown as typeof fetch;

    const result = await callCognitive('recall', {});
    expect(result.ok).toBe(true);
    expect(result.data).toEqual({ memories: [] });
  });

  it('HTTP 失败回退 IPC（spawn 被调用）', async () => {
    process.env.COGNITIVE_API_BASE = 'http://down';
    globalThis.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED')) as unknown as typeof fetch;

    const child = makeChild();
    spawnMock.mockReturnValue(child);

    const promise = callCognitive('health', {});
    await waitFor(() => expect(spawnMock).toHaveBeenCalledTimes(1));
    child.stdout.emit('data', Buffer.from('{"ok":true,"data":{"status":"up"}}\n'));
    child.emit('close');

    const result = await promise;
    expect(result.ok).toBe(true);
    expect(spawnMock).toHaveBeenCalledTimes(1);
  });

  it('未配置 base 时保持既有 IPC 行为', async () => {
    const child = makeChild();
    spawnMock.mockReturnValue(child);

    const promise = callCognitive('stats', {});
    await waitFor(() => expect(spawnMock).toHaveBeenCalledTimes(1));
    child.stdout.emit('data', Buffer.from('{"ok":true,"data":{"total":1}}\n'));
    child.emit('close');

    const result = await promise;
    expect(result.ok).toBe(true);
    expect(spawnMock).toHaveBeenCalledTimes(1);
  });
});
