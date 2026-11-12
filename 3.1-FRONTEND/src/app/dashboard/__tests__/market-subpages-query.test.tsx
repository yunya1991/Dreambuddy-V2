import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AuditPage from '@/app/dashboard/market/audit/page';
import SegmentsPage from '@/app/dashboard/market/segments/page';
import EffectivenessPage from '@/app/dashboard/market/effectiveness/page';
import CampaignsPage from '@/app/dashboard/market/campaigns/page';
import DistributionPage from '@/app/dashboard/market/distribution/page';
import { marketApi } from '@/lib/v3/api';

jest.mock('@/lib/v3/api', () => ({
  marketApi: {
    getAudit: jest.fn(),
    getSegments: jest.fn(),
    getEffectiveness: jest.fn(),
    getCampaigns: jest.fn(),
    getDistribution: jest.fn(),
  },
}));

const mocked = marketApi as unknown as {
  getAudit: jest.Mock;
  getSegments: jest.Mock;
  getEffectiveness: jest.Mock;
  getCampaigns: jest.Mock;
  getDistribution: jest.Mock;
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(client: QueryClient, node: React.ReactElement) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe('market 子页 Query 迁移（T-C4 逐页 批次 12）', () => {
  beforeEach(() => {
    mocked.getAudit.mockReset().mockResolvedValue([]);
    mocked.getSegments.mockReset().mockResolvedValue(null);
    mocked.getEffectiveness.mockReset().mockResolvedValue([]);
    mocked.getCampaigns.mockReset().mockResolvedValue([]);
    mocked.getDistribution.mockReset().mockResolvedValue([]);
  });

  it('audit 页首屏请求一次并渲染空态', async () => {
    renderWith(makeClient(), <AuditPage />);

    await waitFor(() => expect(mocked.getAudit).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('暂无审计记录')).toBeInTheDocument());
  });

  it('audit 页在 staleTime 内重挂载不重复请求', async () => {
    const client = makeClient();
    const { unmount } = renderWith(client, <AuditPage />);
    await waitFor(() => expect(mocked.getAudit).toHaveBeenCalledTimes(1));
    unmount();

    renderWith(client, <AuditPage />);
    await waitFor(() => expect(screen.getByText('暂无审计记录')).toBeInTheDocument());
    expect(mocked.getAudit).toHaveBeenCalledTimes(1);
  });

  it('segments 页首屏请求一次并渲染总计', async () => {
    mocked.getSegments.mockResolvedValue({
      total: 100,
      byRole: { FREE: 50, PRO: 30, ADMIN: 20 },
    });
    renderWith(makeClient(), <SegmentsPage />);

    await waitFor(() => expect(mocked.getSegments).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('100')).toBeInTheDocument());
  });

  it('effectiveness 页首屏请求一次并渲染空态', async () => {
    renderWith(makeClient(), <EffectivenessPage />);

    await waitFor(() => expect(mocked.getEffectiveness).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('暂无效果数据')).toBeInTheDocument());
  });

  it('campaigns 页首屏请求一次，状态筛选为纯前端派生', async () => {
    mocked.getCampaigns.mockResolvedValue([
      { id: 'c1', name: '活动A', type: 'strategy', status: 'APPLIED', direction: 'long', symbol: 'BTC', confidence: 0.6, createdAt: '2026-11-01T00:00:00Z' },
      { id: 'c2', name: '活动B', type: 'strategy', status: 'DRAFT', direction: 'short', symbol: 'ETH', confidence: null, createdAt: '2026-11-02T00:00:00Z' },
    ]);
    renderWith(makeClient(), <CampaignsPage />);

    await waitFor(() => expect(mocked.getCampaigns).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('活动A')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: '草稿' }));
    await waitFor(() => expect(screen.queryByText('活动A')).not.toBeInTheDocument());
    expect(screen.getByText('活动B')).toBeInTheDocument();
    expect(mocked.getCampaigns).toHaveBeenCalledTimes(1);
  });

  it('distribution 页首屏请求一次并渲染空态', async () => {
    renderWith(makeClient(), <DistributionPage />);

    await waitFor(() => expect(mocked.getDistribution).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('暂无分发记录')).toBeInTheDocument());
  });
});
