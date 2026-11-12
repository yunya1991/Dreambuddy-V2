import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiKeyManager } from '@/components/features/settings/ApiKeyManager';
import { ChannelManager } from '@/components/features/settings/ChannelManager';
import { StrategyManager } from '@/components/features/settings/StrategyManager';
import { CompletenessWizard } from '@/components/features/settings/CompletenessWizard';
import { TradingParamsPanel } from '@/components/features/settings/TradingParamsPanel';
import { api } from '@/lib/api-client';

jest.mock('@/lib/api-client', () => ({
  __esModule: true,
  api: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    patch: jest.fn(),
    delete: jest.fn(),
  },
  default: {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    patch: jest.fn(),
    delete: jest.fn(),
  },
}));

const mockedApi = api as unknown as {
  get: jest.Mock;
  post: jest.Mock;
  put: jest.Mock;
  patch: jest.Mock;
  delete: jest.Mock;
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(node: React.ReactNode) {
  return render(<QueryClientProvider client={makeClient()}>{node}</QueryClientProvider>);
}

describe('settings 页面板 Query 迁移（T-C4 逐页 批次 21）', () => {
  afterEach(() => {
    Object.values(mockedApi).forEach(fn => fn.mockReset());
  });

  it('ApiKeyManager 首屏请求一次列表，刷新按钮触发 refetch', async () => {
    mockedApi.get.mockResolvedValue([]);

    renderWith(<ApiKeyManager />);

    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/api/config/api-keys'));
    await waitFor(() => expect(screen.getByText('添加第一个密钥')).toBeInTheDocument());
    expect(mockedApi.get).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('刷新'));
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledTimes(2));
  });

  it('ChannelManager 首屏请求一次渠道列表', async () => {
    mockedApi.get.mockResolvedValue([]);

    renderWith(<ChannelManager />);

    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/api/config/channels'));
    expect(mockedApi.get).toHaveBeenCalledTimes(1);
  });

  it('StrategyManager 首屏请求一次策略列表', async () => {
    mockedApi.get.mockResolvedValue({ strategies: [] });

    renderWith(<StrategyManager />);

    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledWith('/api/config/strategies'));
    expect(mockedApi.get).toHaveBeenCalledTimes(1);
  });

  it('CompletenessWizard 并行拉取 4 个端点各一次并汇总完成度', async () => {
    mockedApi.get.mockImplementation(async (url: string) => {
      if (url === '/api/config/api-keys') {
        return [
          { id: 'k1', category: 'EXCHANGE', isVerified: true },
          { id: 'k2', category: 'LLM' },
        ];
      }
      if (url === '/api/config/trading-params') {
        return {
          params: { leverageMax: 5, capitalPercentage: 20, isTradingEnabled: true },
          liveStatus: { status: 'ACTIVE' },
        };
      }
      if (url === '/api/config/strategies') {
        return { strategies: [{ id: 's1', status: 'APPLIED' }] };
      }
      if (url === '/api/config/channels') {
        return [{ id: 'c1', isOnline: true }];
      }
      return null;
    });

    renderWith(<CompletenessWizard />);

    await waitFor(() => expect(screen.getByText(/6\/6 已完成 · 必填 3\/3/)).toBeInTheDocument());
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(mockedApi.get).toHaveBeenCalledTimes(4);
  });

  it('TradingParamsPanel 首屏取参数，保存后写缓存并失效重取', async () => {
    mockedApi.get.mockResolvedValue({
      params: {
        tradeType: 'SWAP',
        tradeMode: 'SWAP_MODE',
        leverageMax: 5,
        capitalPercentage: 20,
        dailyLossLimit: 100,
        accountLossLimit: 500,
        riskTolerance: 'MODERATE',
        isTradingEnabled: false,
        allowedSymbols: ['BTC-USDT-SWAP'],
      },
    });
    mockedApi.patch.mockResolvedValue({ ok: true });

    renderWith(<TradingParamsPanel />);

    await waitFor(() => expect(screen.getByText('5x')).toBeInTheDocument());
    expect(mockedApi.get).toHaveBeenCalledWith('/api/config/trading-params');
    expect(mockedApi.get).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('编辑'));
    fireEvent.click(screen.getByText('保存'));

    await waitFor(() => expect(mockedApi.patch).toHaveBeenCalledWith('/api/config/trading-params', expect.any(Object)));
    await waitFor(() => expect(mockedApi.get).toHaveBeenCalledTimes(2));
  });
});
