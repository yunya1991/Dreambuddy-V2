import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { OverviewPanel } from '@/components/features/fundamental/OverviewPanel';
import { MacroPanel } from '@/components/features/fundamental/MacroPanel';
import { BreadthPanel } from '@/components/features/fundamental/BreadthPanel';
import { ModuleDetail } from '@/components/features/fundamental/ModuleDetail';
import { fundamentalApi } from '@/lib/v3/api';

jest.mock('@/lib/v3/api', () => ({
  __esModule: true,
  fundamentalApi: { getSnapshot: jest.fn() },
}));

const mocked = fundamentalApi as unknown as { getSnapshot: jest.Mock };

const SNAPSHOT = {
  modules: {
    valuation: {
      metrics: {
        core: { mvrv_ratio: 2.5, nvt_z_score: 0.5, valuation_zone: '中性', market_cap_usd: 1200000 },
      },
    },
    macro: {
      metrics: { core: { policy_score: 0.6, cpi_yoy: 2.8, fed_funds_rate: 5.25, rate_cycle: '降息周期' } },
    },
    breadth: {
      metrics: {
        core: { btc_dominance: 52, breadth_confirmation: '改善' },
        breakdown: { advance_count: 10, decline_count: 5 },
      },
    },
    flow: { metrics: { core: { etf_total_flow: 120 } } },
    onchain: { metrics: { core: { active_addresses: 900000 } } },
    sentiment: { metrics: { core: { sentiment_index: 62 } } },
  },
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(node: React.ReactNode, client = makeClient()) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function stubFetch(map: Record<string, unknown>) {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => ({
    ok: true,
    json: async () => map[String(input)] ?? { ok: false },
  })) as unknown as typeof fetch;
}

describe('fundamental 页面板 Query 迁移（T-C4 逐页 批次 20）', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    mocked.getSnapshot.mockReset();
  });

  it('OverviewPanel 首屏请求一次快照并渲染指标与实时价格', async () => {
    mocked.getSnapshot.mockResolvedValue(SNAPSHOT as never);
    stubFetch({
      '/api/price/btc': { ok: true, price: 65000, change24h: 1.5 },
      '/api/market/global': { ok: true, btc_dominance: 54.2 },
    });

    renderWith(<OverviewPanel />);

    await waitFor(() => expect(screen.getByText('MVRV Ratio')).toBeInTheDocument());
    expect(mocked.getSnapshot).toHaveBeenCalledTimes(1);
    expect(screen.getByText('2.500')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/\$65\.0K/)).toBeInTheDocument());
    expect(screen.getByText('54.2%')).toBeInTheDocument();
  });

  it('多个快照面板共享同一份缓存，只请求一次 getSnapshot', async () => {
    mocked.getSnapshot.mockResolvedValue(SNAPSHOT as never);
    stubFetch({});

    renderWith(
      <>
        <OverviewPanel />
        <MacroPanel />
      </>,
    );

    await waitFor(() => expect(screen.getByText('宏观经济指标')).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText('MVRV Ratio')).toBeInTheDocument());
    expect(mocked.getSnapshot).toHaveBeenCalledTimes(1);
  });

  it('快照失败时展示错误态（原语义保留）', async () => {
    mocked.getSnapshot.mockRejectedValue(new Error('boom'));
    stubFetch({});

    renderWith(<OverviewPanel />);

    await waitFor(() => expect(screen.getByText(/总览数据加载失败/)).toBeInTheDocument());
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });

  it('BreadthPanel 实时行情失败 FAIL-OPEN，仍用快照渲染广度指标', async () => {
    mocked.getSnapshot.mockResolvedValue(SNAPSHOT as never);
    stubFetch({}); // /api/market/global 返回 {ok:false}

    renderWith(<BreadthPanel />);

    await waitFor(() => expect(screen.getByText('市场广度核心指标')).toBeInTheDocument());
    expect(screen.getByText('52.0%')).toBeInTheDocument();
    expect(screen.getByText('上涨资产数')).toBeInTheDocument();
  });

  it('ModuleDetail 按 module 取数并支持刷新重取', async () => {
    const body = {
      ts: '2026-11-12T10:00:00Z',
      resistance_3d: { direction: 'UP', direction_score: 0.4, confidence: 0.8, trend_summary: '上行' },
      metrics: { core: { mvrv_ratio: 2.1 } },
      signals: [],
      timeseries: [
        { ts: 't1', direction_score: 0.1 },
        { ts: 't2', direction_score: 0.3 },
      ],
    };
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => body,
    })) as unknown as typeof fetch;

    renderWith(<ModuleDetail module="valuation" title="估值" />);

    await waitFor(() => expect(screen.getByText(/方向 UP/)).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith('/api/fundamental/valuation/snapshot', { cache: 'no-store' });

    fireEvent.click(screen.getByText('刷新数据'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
  });
});
