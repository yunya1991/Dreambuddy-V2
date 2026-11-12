import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ThreeScreensPage from '@/app/dashboard/three-screens/page';
import { ThreeScreensAPI } from '@/lib/three-screens-api';

jest.mock('@/lib/three-screens-api', () => ({
  ThreeScreensAPI: {
    fetchTrendScreen: jest.fn(),
    fetchV4WaveStrategy: jest.fn(),
    fetchDataDrivenScreens: jest.fn(),
  },
}));

jest.mock('@/lib/three-screens-mapper', () => ({
  mapScreen1: jest.fn(() => ({})),
  mapScreen2: jest.fn(() => ({})),
  mapScreen3: jest.fn(() => ({})),
}));

jest.mock('@/components/features/three-screens/PipelineView', () => ({
  PipelineView: () => <div data-testid="pipeline" />,
}));

const mocked = ThreeScreensAPI as unknown as {
  fetchTrendScreen: jest.Mock;
  fetchV4WaveStrategy: jest.Mock;
  fetchDataDrivenScreens: jest.Mock;
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(client: QueryClient, node: React.ReactElement) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const TREND = { symbol: 'BTC', direction: 'bullish' };
const WAVE = { symbol: 'BTC' };
const DATA_DRIVEN = { screen1: {} };

describe('three-screens 三路轮询 Query 迁移（T-C4 逐页 批次 18）', () => {
  beforeEach(() => {
    mocked.fetchTrendScreen.mockReset().mockResolvedValue(TREND);
    mocked.fetchV4WaveStrategy.mockReset().mockResolvedValue(WAVE);
    mocked.fetchDataDrivenScreens.mockReset().mockResolvedValue(DATA_DRIVEN);
  });

  it('首屏只请求 trend，trend 成功前 wave / data-driven 不启动（单线程后端错峰）', () => {
    renderWith(makeClient(), <ThreeScreensPage />);

    expect(mocked.fetchTrendScreen).toHaveBeenCalledTimes(1);
    expect(mocked.fetchTrendScreen).toHaveBeenCalledWith('BTC');
    expect(mocked.fetchV4WaveStrategy).not.toHaveBeenCalled();
    expect(mocked.fetchDataDrivenScreens).not.toHaveBeenCalled();
  });

  it('trend 首次成功后 wave 与 data-driven 各请求一次', async () => {
    renderWith(makeClient(), <ThreeScreensPage />);

    await waitFor(() => expect(mocked.fetchV4WaveStrategy).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mocked.fetchDataDrivenScreens).toHaveBeenCalledTimes(1));
    expect(mocked.fetchV4WaveStrategy).toHaveBeenCalledWith('BTC');
    expect(mocked.fetchDataDrivenScreens).toHaveBeenCalledWith('BTC');
    expect(screen.getByText('三屏交易系统')).toBeInTheDocument();
  });

  it('trend 失败时 wave / data-driven 保持不启动', async () => {
    mocked.fetchTrendScreen.mockRejectedValue(new Error('trend_offline'));
    renderWith(makeClient(), <ThreeScreensPage />);

    await waitFor(() => expect(mocked.fetchTrendScreen).toHaveBeenCalledTimes(1));
    expect(mocked.fetchV4WaveStrategy).not.toHaveBeenCalled();
    expect(mocked.fetchDataDrivenScreens).not.toHaveBeenCalled();
  });
});
