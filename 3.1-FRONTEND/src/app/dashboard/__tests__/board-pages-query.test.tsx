import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ProposalListPage from '@/app/dashboard/board/proposals/page';
import ExecutionReviewPage from '@/app/dashboard/board/review/page';
import BoardOverviewPage from '@/app/dashboard/board/page';
import ApprovalGatePage from '@/app/dashboard/board/approval/page';
import { boardApi } from '@/lib/v3/api';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) =>
    React.createElement('a', { href }, children),
}));

jest.mock('@/lib/v3/api', () => ({
  boardApi: {
    listProposals: jest.fn(),
    listReviews: jest.fn(),
    getApprovalSummary: jest.fn(),
    getMetrics: jest.fn(),
    getPendingApprovals: jest.fn(),
  },
}));

const mocked = boardApi as unknown as {
  listProposals: jest.Mock;
  listReviews: jest.Mock;
  getApprovalSummary: jest.Mock;
  getMetrics: jest.Mock;
  getPendingApprovals: jest.Mock;
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage(node: React.ReactNode, client = makeClient()) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe('board 页 Query 迁移（T-C4 逐页）', () => {
  beforeEach(() => {
    mocked.listProposals.mockReset().mockResolvedValue([]);
    mocked.listReviews.mockReset().mockResolvedValue([]);
    mocked.getApprovalSummary
      .mockReset()
      .mockResolvedValue({ total: 4, pending: 1, approved: 2, rejected: 1 });
    mocked.getMetrics.mockReset().mockResolvedValue({
      total_traces: 7,
      total_decisions: 3,
      total_artifacts: 5,
      pending_approvals: 1,
      recent_performance: { avg_win_rate: 0.55, total_pnl: 12.5, trade_count: 9 },
      department_breakdown: { strategy: 2 },
    });
    mocked.getPendingApprovals.mockReset().mockResolvedValue([]);
  });

  it('proposals：首屏请求一次，切换状态筛选不重复请求', async () => {
    mocked.listProposals.mockResolvedValue([
      {
        id: 'p1',
        title: 'BTC 趋势提案',
        status: 'DRAFT',
        type: 'TREND',
        direction: 'BUY',
        symbol: 'BTC/USDT',
        confidence: 0.6,
        edgeScore: 1.2,
        createdAt: '2026-11-01T00:00:00.000Z',
      },
    ]);

    renderPage(<ProposalListPage />);

    await waitFor(() => expect(screen.getByText('BTC 趋势提案')).toBeInTheDocument());
    expect(mocked.listProposals).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: '草稿' }));
    expect(screen.getByText('BTC 趋势提案')).toBeInTheDocument();
    expect(mocked.listProposals).toHaveBeenCalledTimes(1);
  });

  it('proposals：同一 client 重挂载在 staleTime 内不重复请求', async () => {
    const client = makeClient();
    const { unmount } = renderPage(<ProposalListPage />, client);
    await waitFor(() => expect(mocked.listProposals).toHaveBeenCalledTimes(1));
    unmount();

    renderPage(<ProposalListPage />, client);
    await waitFor(() => expect(screen.getByText('暂无提案')).toBeInTheDocument());
    expect(mocked.listProposals).toHaveBeenCalledTimes(1);
  });

  it('review：评审与审批摘要各请求一次，摘要渲染', async () => {
    renderPage(<ExecutionReviewPage />);

    await waitFor(() => expect(mocked.listReviews).toHaveBeenCalledTimes(1));
    expect(mocked.getApprovalSummary).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText('总审批项')).toBeInTheDocument());
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('暂无评审数据')).toBeInTheDocument();
  });

  it('board 总览：指标与审批摘要各请求一次并渲染', async () => {
    renderPage(<BoardOverviewPage />);

    await waitFor(() => expect(screen.getByText('董事会总览台')).toBeInTheDocument());
    expect(mocked.getMetrics).toHaveBeenCalledTimes(1);
    expect(mocked.getApprovalSummary).toHaveBeenCalledTimes(1);
    expect(screen.getByText('7')).toBeInTheDocument();
    expect(screen.getByText('$12.50')).toBeInTheDocument();
  });

  it('approval：首屏请求一次并渲染待审批项', async () => {
    mocked.getPendingApprovals.mockResolvedValue([
      {
        id: 'a1',
        title: '高风险提案',
        direction: 'LONG',
        symbol: 'BTC/USDT',
        type: 'TREND',
        confidence: 0.8,
        description: null,
        createdAt: '2026-11-01T00:00:00.000Z',
      },
    ]);

    renderPage(<ApprovalGatePage />);

    await waitFor(() => expect(screen.getByText('高风险提案')).toBeInTheDocument());
    expect(mocked.getPendingApprovals).toHaveBeenCalledTimes(1);
  });

  it('approval：批准后 POST 一次并移入已决策', async () => {
    mocked.getPendingApprovals.mockResolvedValue([
      {
        id: 'a1',
        title: '高风险提案',
        direction: 'LONG',
        symbol: 'BTC/USDT',
        type: 'TREND',
        confidence: 0.8,
        description: null,
        createdAt: '2026-11-01T00:00:00.000Z',
      },
    ]);
    const fetchMock = jest.fn().mockResolvedValue({ json: async () => ({ success: true }) });
    global.fetch = fetchMock as unknown as typeof fetch;

    renderPage(<ApprovalGatePage />);
    await waitFor(() => expect(screen.getByText('高风险提案')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /批准/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/board/approval/a1',
      expect.objectContaining({ method: 'POST' }),
    );
    await waitFor(() => expect(screen.getByText('已批准')).toBeInTheDocument());
  });
});
