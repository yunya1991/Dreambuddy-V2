import React from 'react';
import { render, screen, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LiveStatusPanel } from '@/components/features/dashboard/LiveStatusPanel';
import { useMonitorData } from '@/lib/use-monitor-data';
import api from '@/lib/api-client';

jest.mock('@/lib/api-client', () => ({
  __esModule: true,
  default: { get: jest.fn() },
}));

jest.mock('@/lib/stream/monitor-stream-manager', () => ({
  subscribeMonitor: jest.fn(() => jest.fn()),
  subscribeMonitorStatus: jest.fn(() => jest.fn()),
}));

const mockSetThroughput = jest.fn();
const mockAddEvent = jest.fn();
const mockSetSSEStatus = jest.fn();
const mockMemoryFetchStats = jest.fn();

jest.mock('@/stores', () => ({
  useMonitorStore: {
    getState: () => ({
      addEvent: mockAddEvent,
      setSSEStatus: mockSetSSEStatus,
      setThroughput: mockSetThroughput,
    }),
  },
  useMemoryStore: {
    getState: () => ({ fetchStats: mockMemoryFetchStats }),
  },
}));

const mockedApi = api as unknown as { get: jest.Mock };

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={makeClient()}>{children}</QueryClientProvider>;
}

describe('dashboard 首页 / monitor 页数据接入 Query 迁移（T-C4 逐页 批次 19）', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    mockSetThroughput.mockReset();
    mockedApi.get.mockReset();
  });

  it('LiveStatusPanel 首屏请求一次产物统计并渲染', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        stats: { total: 12, by_type: { report: 3 }, total_size_bytes: 2048 },
      }),
    }) as unknown as typeof fetch;

    render(
      <QueryClientProvider client={makeClient()}>
        <LiveStatusPanel />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText('12')).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith('/api/artifacts?stats=1');
    expect(screen.getByText('2.0')).toBeInTheDocument(); // 2048 bytes → 2.0 KB
  });

  it('LiveStatusPanel 请求失败保持 FAIL-OPEN（不崩溃、显示 0）', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;

    render(
      <QueryClientProvider client={makeClient()}>
        <LiveStatusPanel />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText('产物总数')).toBeInTheDocument());
    expect(screen.getAllByText('0').length).toBeGreaterThan(0);
  });

  it('useMonitorData 首屏请求一次 monitor/stats 并写入 store', async () => {
    mockedApi.get.mockResolvedValue({
      stats: {
        total_requests: 100,
        total_completed: 95,
        total_failed: 5,
        success_rate: 95,
        avg_duration_ms: 120,
        active_traces: 3,
      },
    });

    renderHook(() => useMonitorData(), { wrapper });

    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/api/monitor/stats'));
    await waitFor(() =>
      expect(mockSetThroughput).toHaveBeenCalledWith({
        totalProcessed: 100,
        successRate: 0.95,
        avgLatencyMs: 120,
        activeCount: 3,
      }),
    );
    expect(mockedApi.get).toHaveBeenCalledTimes(1);
    expect(mockMemoryFetchStats).toHaveBeenCalled();
  });
});
