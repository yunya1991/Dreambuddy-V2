/**
 * TokenMonitorProvider 挂载语义回归测试
 *
 * 关键约束：全局只允许一个 TokenMonitor 实例（单一轮询源）。
 * - Provider 内多个组件调用 useTokenMonitor → 复用同一个 Context 实例，构造仅 1 次
 * - Provider 外调用 useTokenMonitor → 保持原有自建实例行为（向后兼容）
 */

import { render, act } from '@testing-library/react';

jest.mock('@/lib/token-monitor', () => {
  const instances: unknown[] = [];

  class TokenMonitor {
    started = false;
    callbacks: unknown;
    constructor(
      public fetchBalance: unknown,
      public config: unknown,
      callbacks: unknown
    ) {
      this.callbacks = callbacks;
      instances.push(this);
    }
    start() {
      this.started = true;
    }
    stop() {
      this.started = false;
    }
    getState() {
      return {
        status: this.started ? 'running' : 'idle',
        balance: 32500,
        totalEarned: 120000,
        totalSpent: 87500,
        level: 'healthy',
        lastChecked: 0,
        autoDowngradeEnabled: true,
        isDowngraded: false,
        checkCount: 1,
        consecutiveLowCount: 0,
      };
    }
    setCallbacks(callbacks: unknown) {
      this.callbacks = callbacks;
    }
    checkNow() {
      return Promise.resolve(this.getState());
    }
    pause() {}
    resume() {}
    updateConfig() {}
    triggerDowngrade() {}
    triggerRecovery() {}
  }

  return { __esModule: true, TokenMonitor, __instances: instances };
});

jest.mock('@/lib/api-client', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));

import { TokenMonitorProvider, useTokenMonitorContext, fetchTokenBalance } from '../token-monitor-provider';
import { useTokenMonitor } from '../use-token-monitor';
import type { FetchBalanceFn } from '../token-monitor';
import api from '@/lib/api-client';

const { __instances } = jest.requireMock('@/lib/token-monitor') as {
  __instances: { started: boolean }[];
};

const fetchBalance: FetchBalanceFn = async () => ({ balance: 32500 });

// 记录每个组件拿到的 checkNow 引用，用于断言共享同一实例
const seen: Array<() => Promise<void>> = [];

function Consumer() {
  const viaCtx = useTokenMonitorContext();
  // Provider 内调用 useTokenMonitor 也必须复用全局实例
  const viaHook = useTokenMonitor({ fetchBalance });
  seen.push(viaHook.checkNow);
  return <span>{`${viaCtx.state.balance}/${viaHook.state.balance}`}</span>;
}

describe('TokenMonitorProvider 单实例', () => {
  beforeEach(() => {
    __instances.length = 0;
    seen.length = 0;
    jest.spyOn(console, 'log').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('Provider 内多个消费者共享同一实例，TokenMonitor 只构造 1 次', () => {
    render(
      <TokenMonitorProvider fetchBalance={fetchBalance}>
        <Consumer />
        <Consumer />
      </TokenMonitorProvider>
    );

    expect(__instances).toHaveLength(1);
    expect(__instances[0].started).toBe(true);
    // 两个 Consumer（各自多次渲染）× 两种取用方式 → 全部指向同一个实例的方法
    expect(seen.length).toBeGreaterThanOrEqual(2);
    expect(new Set(seen).size).toBe(1);
  });

  it('Provider 外调用 useTokenMonitor 仍自建实例（向后兼容）', () => {
    render(<StandaloneConsumer />);

    expect(__instances).toHaveLength(1);
    expect(__instances[0].started).toBe(true);
  });
});

describe('fetchTokenBalance', () => {
  beforeEach(() => {
    (api.get as jest.Mock).mockReset();
  });

  it('走 /api/token/balance 并映射 balance/totalEarned/totalSpent', async () => {
    (api.get as jest.Mock).mockResolvedValue({
      balance: 1200,
      totalEarned: 5000,
      totalSpent: 3800,
    });

    await expect(fetchTokenBalance()).resolves.toEqual({
      balance: 1200,
      totalEarned: 5000,
      totalSpent: 3800,
    });
    expect(api.get).toHaveBeenCalledWith('/api/token/balance');
  });

  it('后端缺字段时回填 0', async () => {
    (api.get as jest.Mock).mockResolvedValue({ balance: 7 });

    await expect(fetchTokenBalance()).resolves.toEqual({
      balance: 7,
      totalEarned: 0,
      totalSpent: 0,
    });
  });
});

function StandaloneConsumer() {
  const { state } = useTokenMonitor({ fetchBalance });
  return <span>{state.balance}</span>;
}
