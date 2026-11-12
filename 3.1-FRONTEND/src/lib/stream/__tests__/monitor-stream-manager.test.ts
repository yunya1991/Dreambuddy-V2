/**
 * monitor-stream-manager — 单例 / 引用计数 / 去重 / 退避重连
 * SPEC-20261111-A §3.3 行为契约
 */

type Handler = (event: Record<string, unknown>) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  emit(payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

type MonitorModule = typeof import('@/lib/stream/monitor-stream-manager');

function loadModule(): MonitorModule {
  let mod!: MonitorModule;
  jest.isolateModules(() => {
    mod = require('@/lib/stream/monitor-stream-manager');
  });
  return mod;
}

describe('monitor-stream-manager', () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    (globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource = MockEventSource;
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('引用计数：多订阅共享 1 条连接，最后一个退订才关闭', () => {
    const { subscribeMonitor } = loadModule();
    const a = jest.fn();
    const b = jest.fn();

    const unsubA = subscribeMonitor(a as Handler);
    const unsubB = subscribeMonitor(b as Handler);
    expect(MockEventSource.instances).toHaveLength(1);

    unsubA();
    expect(MockEventSource.instances[0].closed).toBe(false);

    unsubB();
    expect(MockEventSource.instances[0].closed).toBe(true);
  });

  it('去重：相同 event.id 只分发一次，不同 id 正常分发', () => {
    const { subscribeMonitor } = loadModule();
    const handler = jest.fn();
    subscribeMonitor(handler as Handler);

    const es = MockEventSource.instances[0];
    es.emit({ id: 'evt-1', phase: 'task_created' });
    es.emit({ id: 'evt-1', phase: 'task_created' });
    es.emit({ id: 'evt-2', phase: 'routed' });

    expect(handler).toHaveBeenCalledTimes(2);
  });

  it('跳过系统消息（connected/system）', () => {
    const { subscribeMonitor } = loadModule();
    const handler = jest.fn();
    subscribeMonitor(handler as Handler);

    const es = MockEventSource.instances[0];
    es.emit({ type: 'connected', conn_id: 'x' });
    es.emit({ type: 'system' });
    expect(handler).not.toHaveBeenCalled();
  });

  it('断流后指数退避重连，open 后状态回到 open', () => {
    const { subscribeMonitor, getMonitorStatus, subscribeMonitorStatus } = loadModule();
    const statuses: string[] = [];
    subscribeMonitorStatus((s) => statuses.push(s));
    subscribeMonitor(jest.fn() as Handler);

    expect(MockEventSource.instances).toHaveLength(1);
    MockEventSource.instances[0].onerror?.();
    expect(getMonitorStatus()).toBe('reconnecting');

    jest.advanceTimersByTime(1600); // 1000ms + 抖动上限 500ms
    expect(MockEventSource.instances).toHaveLength(2);

    MockEventSource.instances[1].onopen?.();
    expect(getMonitorStatus()).toBe('open');
    expect(statuses).toContain('reconnecting');
    expect(statuses[statuses.length - 1]).toBe('open');
  });

  it('无订阅时断流不重连（teardown 后不再新建连接）', () => {
    const { subscribeMonitor } = loadModule();
    const unsub = subscribeMonitor(jest.fn() as Handler);
    const es = MockEventSource.instances[0];
    unsub();

    es.onerror?.();
    jest.advanceTimersByTime(60_000);
    expect(MockEventSource.instances).toHaveLength(1);
  });
});
