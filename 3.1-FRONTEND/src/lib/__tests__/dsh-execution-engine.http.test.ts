import { EventEmitter } from 'node:events';
import { waitFor } from '@testing-library/react';

jest.mock('child_process', () => ({ spawn: jest.fn() }));

// GAP-2：让 inboundTraceId() 能在测试里读到「入站请求头」
let mockInboundHeaders: Record<string, string> = {};
jest.mock('next/headers', () => ({
  headers: async () => ({
    get: (key: string) => mockInboundHeaders[key.toLowerCase()] ?? null,
  }),
}));

import { spawn } from 'child_process';
import { callDshHandler } from '../dsh-execution-engine';

function makeChild() {
  const child = new EventEmitter() as EventEmitter & {
    stdout: EventEmitter;
    stderr: EventEmitter;
    kill: jest.Mock;
  };
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = jest.fn();
  return child;
}

function fakeResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe('dsh-execution-engine 传输选择 (T-C5)', () => {
  const originalFetch = globalThis.fetch;
  const originalBase = process.env.DSH_API_BASE;
  const spawnMock = spawn as unknown as jest.Mock;

  beforeEach(() => {
    spawnMock.mockReset();
    mockInboundHeaders = {};
    delete process.env.DSH_API_BASE;
  });

  afterEach(() => {
    jest.useRealTimers();
    globalThis.fetch = originalFetch;
    if (originalBase === undefined) delete process.env.DSH_API_BASE;
    else process.env.DSH_API_BASE = originalBase;
  });

  it('配置 DSH_API_BASE 时走 HTTP，不 spawn', async () => {
    process.env.DSH_API_BASE = 'http://dsh.local/';
    const fetchMock = jest.fn().mockResolvedValue(
      fakeResponse(200, { ok: true, output: { trend: 'up' } }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await callDshHandler('technical', { symbol: 'BTC-USDT' });

    expect(result).toEqual({ ok: true, output: { trend: 'up' } });
    expect(spawnMock).not.toHaveBeenCalled();
    expect(fetchMock.mock.calls[0][0]).toBe('http://dsh.local/execute');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      capability: 'technical',
      payload: { symbol: 'BTC-USDT' },
    });
  });

  it('入站 X-Request-Id 透传到上游请求头与 body.trace_id（GAP-2）', async () => {
    process.env.DSH_API_BASE = 'http://dsh.local';
    mockInboundHeaders = { 'x-request-id': 'trace-in-9' };
    const fetchMock = jest.fn().mockResolvedValue(
      fakeResponse(200, { ok: true, output: {}, trace_id: 'trace-in-9' }),
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await callDshHandler('technical', { symbol: 'BTC' });

    const init = fetchMock.mock.calls[0][1];
    expect(init.headers['X-Request-Id']).toBe('trace-in-9');
    expect(JSON.parse(init.body).trace_id).toBe('trace-in-9');
  });

  it('无入站链路 ID 时不注入 trace（保持旧请求形状）', async () => {
    process.env.DSH_API_BASE = 'http://dsh.local';
    const fetchMock = jest.fn().mockResolvedValue(fakeResponse(200, { ok: true, output: {} }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await callDshHandler('technical', { symbol: 'BTC' });

    const init = fetchMock.mock.calls[0][1];
    expect(init.headers['X-Request-Id']).toBeUndefined();
    expect(JSON.parse(init.body)).toEqual({
      capability: 'technical',
      payload: { symbol: 'BTC' },
    });
  });

  it('HTTP 上游失败回退 IPC', async () => {
    process.env.DSH_API_BASE = 'http://down';
    globalThis.fetch = jest.fn().mockRejectedValue(new Error('ECONNREFUSED')) as unknown as typeof fetch;

    const child = makeChild();
    spawnMock.mockReturnValue(child);

    const promise = callDshHandler('sentiment', {});
    await waitFor(() => expect(spawnMock).toHaveBeenCalledTimes(1));
    child.stdout.emit('data', Buffer.from('{"ok":true,"output":{"score":0.5}}\n'));
    child.emit('close');

    const result = await promise;
    expect(result.ok).toBe(true);
    expect(spawnMock).toHaveBeenCalledTimes(1);
  });

  it('未配置 base 时只有 IPC 路径', async () => {
    const child = makeChild();
    spawnMock.mockReturnValue(child);

    const promise = callDshHandler('macro', {});
    await waitFor(() => expect(spawnMock).toHaveBeenCalledTimes(1));
    child.stdout.emit('data', Buffer.from('{"ok":true,"output":{}}\n'));
    child.emit('close');

    const result = await promise;
    expect(result.ok).toBe(true);
    expect(spawnMock).toHaveBeenCalledTimes(1);
  });

  it('IPC 路径同样带 trace_id（默认本地模式不断链）', async () => {
    mockInboundHeaders = { 'x-request-id': 'trace-ipc-1' };
    const child = makeChild();
    spawnMock.mockReturnValue(child);

    const promise = callDshHandler('macro', { symbol: 'ETH' });
    await waitFor(() => expect(spawnMock).toHaveBeenCalledTimes(1));
    child.stdout.emit('data', Buffer.from('{"ok":true,"output":{}}\n'));
    child.emit('close');
    await promise;

    const args = spawnMock.mock.calls[0][1] as string[];
    expect(JSON.parse(args[2])).toEqual({ symbol: 'ETH', trace_id: 'trace-ipc-1' });
  });

  it('子进程超时 → degraded timeout，并 SIGKILL 回收', async () => {
    jest.useFakeTimers();
    const child = makeChild();
    spawnMock.mockReturnValue(child);

    const promise = callDshHandler('technical', {});
    await jest.advanceTimersByTimeAsync(15_000);

    await expect(promise).resolves.toEqual({
      ok: false,
      degraded: true,
      error: 'timeout_15000ms',
    });
    expect(child.kill).toHaveBeenCalledWith('SIGKILL');
  });

  it('子进程非零退出且无输出 → degraded exit_code_1', async () => {
    const child = makeChild();
    spawnMock.mockReturnValue(child);

    const promise = callDshHandler('technical', {});
    await waitFor(() => expect(spawnMock).toHaveBeenCalledTimes(1));
    child.emit('close', 1);

    await expect(promise).resolves.toEqual({
      ok: false,
      degraded: true,
      error: 'exit_code_1',
    });
  });

  it('解释器不存在（ENOENT）→ degraded spawn_failed', async () => {
    const child = makeChild();
    spawnMock.mockReturnValue(child);

    const promise = callDshHandler('technical', {});
    await waitFor(() => expect(spawnMock).toHaveBeenCalledTimes(1));
    child.emit('error', Object.assign(new Error('spawn python3 ENOENT'), { code: 'ENOENT' }));

    const result = await promise;
    expect(result.ok).toBe(false);
    expect(result.degraded).toBe(true);
    expect(result.error).toContain('spawn_failed');
    expect(result.error).toContain('ENOENT');
  });
});

describe('orchestrator 云端异步通路 + /execute 鉴权头', () => {
  const originalFetch = globalThis.fetch;
  const originalBase = process.env.DSH_API_BASE;
  const originalToken = process.env.DSH_API_TOKEN;
  const spawnMock = spawn as unknown as jest.Mock;

  beforeEach(() => {
    spawnMock.mockReset();
    delete process.env.DSH_API_BASE;
    delete process.env.DSH_API_TOKEN;
  });

  afterEach(() => {
    jest.useRealTimers();
    globalThis.fetch = originalFetch;
    if (originalBase === undefined) delete process.env.DSH_API_BASE;
    else process.env.DSH_API_BASE = originalBase;
    if (originalToken === undefined) delete process.env.DSH_API_TOKEN;
    else process.env.DSH_API_TOKEN = originalToken;
  });

  it('orchestrator 先提交再轮询，返回与同步一致的信封', async () => {
    jest.useFakeTimers();
    process.env.DSH_API_BASE = 'http://cloud';
    // 形状对齐真实 execute_http_server：pending 只有 {job_id,status}；
    // done 时 call_handler 剥掉 status，直接把 run_cycle 结果作为 output 返回
    const fetchMock = jest.fn()
      .mockResolvedValueOnce(fakeResponse(200, { ok: true, output: { status: 'accepted', job_id: 'j1' } }))
      .mockResolvedValueOnce(fakeResponse(200, { ok: true, output: { status: 'pending', job_id: 'j1' } }))
      .mockResolvedValueOnce(fakeResponse(200, {
        ok: true,
        output: { ok: true, output: { direction: 'LONG', confidence: 0.7 } },
      }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const promise = callDshHandler('orchestrator', { symbol: 'BTC' });
    await jest.advanceTimersByTimeAsync(3000);

    await expect(promise).resolves.toEqual({
      ok: true,
      output: { direction: 'LONG', confidence: 0.7 },
    });
    expect(spawnMock).not.toHaveBeenCalled();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      capability: 'orchestrator',
      payload: { symbol: 'BTC', async: true },
    });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      capability: 'orchestrator_status',
      payload: { job_id: 'j1' },
    });
  });

  it('/execute 返回 401 时不回退 spawn（配置错误要显式失败）', async () => {
    process.env.DSH_API_BASE = 'http://cloud';
    globalThis.fetch = jest.fn().mockResolvedValue(fakeResponse(401, {})) as unknown as typeof fetch;

    const result = await callDshHandler('technical', {});

    expect(result).toEqual({ ok: false, degraded: true, error: 'unauthorized' });
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it('配置 DSH_API_TOKEN 时带 Bearer 头', async () => {
    process.env.DSH_API_BASE = 'http://cloud';
    process.env.DSH_API_TOKEN = 'secret-token';
    const fetchMock = jest.fn().mockResolvedValue(fakeResponse(200, { ok: true, output: {} }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await callDshHandler('technical', {});

    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({
      Authorization: 'Bearer secret-token',
    });
  });
});
