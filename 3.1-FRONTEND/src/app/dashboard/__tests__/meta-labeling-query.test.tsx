import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MetaLabelingPage from '@/app/dashboard/meta-labeling/page';
import { fetchMetaLabeling } from '@/lib/v3/api';

jest.mock('@/lib/v3/api', () => ({
  fetchMetaLabeling: jest.fn(),
}));

const mocked = fetchMetaLabeling as unknown as jest.Mock;

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(client: QueryClient, node: React.ReactElement) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe('meta-labeling 页 Query 迁移（T-C4 逐页 批次 15）', () => {
  beforeEach(() => {
    mocked.mockReset();
  });

  it('接口不可用时请求一次并降级到演示数据', async () => {
    mocked.mockResolvedValue(null);
    renderWith(makeClient(), <MetaLabelingPage />);

    await waitFor(() => expect(mocked).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('（演示数据）')).toBeInTheDocument());
    expect(screen.getByText('EMA排列')).toBeInTheDocument();
  });

  it('接口返回结果时展示 API 数据且不显示演示标记', async () => {
    mocked.mockResolvedValue([
      {
        signal: { source: 'technical', name: 'API信号', direction: 'long', confidence: 0.8 },
        winProbability: 0.7,
        expectedValue: 0.01,
        decision: 'execute',
        sizeMultiplier: 1.5,
      },
    ]);
    renderWith(makeClient(), <MetaLabelingPage />);

    await waitFor(() => expect(screen.getByText('API信号')).toBeInTheDocument());
    expect(screen.queryByText('（演示数据）')).not.toBeInTheDocument();
    expect(screen.queryByText('EMA排列')).not.toBeInTheDocument();
  });
});
