import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import MarketPage from '@/app/dashboard/market/page';
import { marketApi } from '@/lib/v3/api';

// next/link 在 jsdom 下会触发 IntersectionObserver 预取，测试里退化为普通 <a>
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) =>
    React.createElement('a', { href }, children),
}));

jest.mock('@/lib/v3/api', () => ({
  marketApi: { getRoute: jest.fn(), getContent: jest.fn() },
}));

const mocked = marketApi as unknown as { getRoute: jest.Mock; getContent: jest.Mock };

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <MarketPage />
    </QueryClientProvider>,
  );
}

describe('market 页 Query 迁移（T-C4 逐页）', () => {
  beforeEach(() => {
    mocked.getRoute.mockReset().mockResolvedValue([]);
    mocked.getContent.mockReset().mockResolvedValue([]);
  });

  it('首次渲染只请求当前 tab，不预取另一个 tab', async () => {
    renderPage(makeClient());

    await waitFor(() => expect(mocked.getRoute).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('暂无路由决策记录')).toBeInTheDocument());
    expect(mocked.getContent).not.toHaveBeenCalled();
  });

  it('切换 tab 触发对应请求，切回命中缓存不重复请求', async () => {
    renderPage(makeClient());
    await waitFor(() => expect(mocked.getRoute).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText('内容池'));
    await waitFor(() => expect(mocked.getContent).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByText('路由决策'));
    await waitFor(() => expect(screen.getByText('暂无路由决策记录')).toBeInTheDocument());
    expect(mocked.getRoute).toHaveBeenCalledTimes(1);
  });

  it('同一 client 在 staleTime 内重挂载不重复请求', async () => {
    const client = makeClient();
    const { unmount } = renderPage(client);
    await waitFor(() => expect(mocked.getRoute).toHaveBeenCalledTimes(1));
    unmount();

    renderPage(client);
    await waitFor(() => expect(screen.getByText('暂无路由决策记录')).toBeInTheDocument());
    expect(mocked.getRoute).toHaveBeenCalledTimes(1);
  });
});
