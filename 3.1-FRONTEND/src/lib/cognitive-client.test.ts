/**
 * cognitive-client 超时分级回归测试（SPEC FRONTEND_INDUSTRIALIZATION_GOAL_SPEC HC-11）
 *
 * 背景：云端 30 万+ 记忆的 recall 实测约 14s，原固定 10s 超时会把正常慢调用
 * 误判为降级（/api/cognitive/recall 503 timeout_10000ms）；health 轮询仍需快速失败。
 */
import { EventEmitter } from 'events';

jest.mock('child_process', () => ({ spawn: jest.fn() }));

import { spawn } from 'child_process';
import { callCognitive } from './cognitive-client';

const mockSpawn = spawn as unknown as jest.Mock;

class FakeChild extends EventEmitter {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  kill = jest.fn();
}

function useFakeChild(): FakeChild {
  const child = new FakeChild();
  mockSpawn.mockReturnValue(child);
  return child;
}

describe('cognitive-client 超时分级', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockSpawn.mockReset();
    delete process.env.COGNITIVE_API_BASE;
    delete process.env.COGNITIVE_TIMEOUT_MS;
    delete process.env.COGNITIVE_HEALTH_TIMEOUT_MS;
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('health 使用短超时（10s），避免页面轮询长时间空白', async () => {
    useFakeChild();
    const pending = callCognitive('health', {});

    jest.advanceTimersByTime(10_000);

    await expect(pending).resolves.toMatchObject({
      ok: false,
      degraded: true,
      error: 'timeout_10000ms',
    });
  });

  it('recall 默认超时覆盖云端实测 14s，且不早于 35s 触发', async () => {
    useFakeChild();
    const pending = callCognitive('recall', { context: 'x' });

    let settled = false;
    pending.then(() => {
      settled = true;
    });

    jest.advanceTimersByTime(34_999);
    await Promise.resolve();
    expect(settled).toBe(false);

    jest.advanceTimersByTime(1);
    await expect(pending).resolves.toMatchObject({
      ok: false,
      degraded: true,
      error: 'timeout_35000ms',
    });
  });

  it('health 不受业务超时环境变量影响', async () => {
    process.env.COGNITIVE_TIMEOUT_MS = '1200';
    useFakeChild();
    const pending = callCognitive('health', {});

    jest.advanceTimersByTime(10_000);

    await expect(pending).resolves.toMatchObject({ error: 'timeout_10000ms' });
  });

  it('业务超时可由 COGNITIVE_TIMEOUT_MS 覆盖', async () => {
    process.env.COGNITIVE_TIMEOUT_MS = '1200';
    useFakeChild();
    const pending = callCognitive('verify', { memory_id: 'VM-1' });

    jest.advanceTimersByTime(1_200);

    await expect(pending).resolves.toMatchObject({ error: 'timeout_1200ms' });
  });

  it('成功路径保持原有单行 JSON 解析语义', async () => {
    const child = useFakeChild();
    const pending = callCognitive('stats', {});

    child.stdout.emit('data', Buffer.from('{"ok":true,"data":{"total":3}}\n'));
    child.emit('close');

    await expect(pending).resolves.toEqual({ ok: true, data: { total: 3 } });
  });
});
