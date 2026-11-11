/**
 * @jest-environment node
 *
 * Phase 4.6 /api/agent/brainstorm：mock child_process，覆盖成功 / 非零退出 /
 * 非 JSON / 超时 / intent 为空 / GET 405（不触真实编排器）。
 */
import { EventEmitter } from 'events';
import { PassThrough } from 'stream';

jest.mock('child_process', () => ({ spawn: jest.fn() }));

import { spawn } from 'child_process';
import { NextRequest } from 'next/server';
import { GET, POST } from './route';

function makeChild() {
  const child = new EventEmitter() as EventEmitter & {
    stdout: PassThrough;
    stderr: PassThrough;
    kill: jest.Mock;
  };
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = jest.fn();
  return child;
}

function makeRequest(body: unknown): NextRequest {
  return new NextRequest('http://localhost/api/agent/brainstorm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** 等待 POST 内部完成 request.json() 并挂上 spawn 事件监听。 */
async function flush() {
  await new Promise((resolve) => setImmediate(resolve));
}

const SUMMARY = {
  ok: true,
  route: 'debate',
  skipped: false,
  winner: 'pc-abc',
  trace_id: 'bs-1',
  outbox_written: 2,
  diversity_violations: [],
  adjudication: { mode: 'both' },
  mode: 'debate',
};

describe('POST /api/agent/brainstorm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('成功：解析最后一行 JSON 并返回 { ok:true, ...summary }', async () => {
    const child = makeChild();
    (spawn as jest.Mock).mockReturnValue(child);

    const promise = POST(makeRequest({ intent: '对比方案A与B的成本', nPerSide: 2 }));
    await flush();
    child.stdout.emit('data', Buffer.from('某行日志\n'));
    child.stdout.emit('data', Buffer.from(`${JSON.stringify(SUMMARY)}\n`));
    child.emit('close', 0);
    const response = await promise;

    expect(response.status).toBe(200);
    const json = await response.json();
    expect(json.ok).toBe(true);
    expect(json.route).toBe('debate');
    expect(json.trace_id).toBe('bs-1');
    const [python, args] = (spawn as jest.Mock).mock.calls[0];
    expect(python).toBe(process.env.ORCHESTRATOR_PY || 'python3');
    expect(args).toContain('--json-out');
    expect(args).toContain('--n-per-side');
  });

  it('非零退出 → 200 degraded', async () => {
    const child = makeChild();
    (spawn as jest.Mock).mockReturnValue(child);

    const promise = POST(makeRequest({ intent: '测试意图' }));
    await flush();
    child.stderr.emit('data', Buffer.from('boom'));
    child.emit('close', 2);
    const json = await (await promise).json();

    expect(json.ok).toBe(false);
    expect(json.degraded).toBe(true);
    expect(json.error).toContain('orchestrator_exit_nonzero');
  });

  it('stdout 非 JSON → 200 degraded', async () => {
    const child = makeChild();
    (spawn as jest.Mock).mockReturnValue(child);

    const promise = POST(makeRequest({ intent: '测试意图' }));
    await flush();
    child.stdout.emit('data', Buffer.from('not-json\n'));
    child.emit('close', 0);
    const json = await (await promise).json();

    expect(json.ok).toBe(false);
    expect(json.degraded).toBe(true);
    expect(json.error).toContain('orchestrator_output_invalid');
  });

  it('超时 → kill 并返回 degraded', async () => {
    jest.useFakeTimers();
    const child = makeChild();
    (spawn as jest.Mock).mockReturnValue(child);

    const promise = POST(makeRequest({ intent: '慢任务' }));
    await jest.advanceTimersByTimeAsync(1);
    await jest.advanceTimersByTimeAsync(180_000);
    const json = await (await promise).json();

    expect(child.kill).toHaveBeenCalledWith('SIGKILL');
    expect(json.ok).toBe(false);
    expect(json.error).toBe('orchestrator_timeout');
  });

  it('intent 为空 → degraded（不 spawn）', async () => {
    const json = await (await POST(makeRequest({ intent: '   ' }))).json();

    expect(json.ok).toBe(false);
    expect(json.error).toBe('intent_required');
    expect(spawn).not.toHaveBeenCalled();
  });

  it('GET → 405', async () => {
    const response = await GET();
    expect(response.status).toBe(405);
  });
});
