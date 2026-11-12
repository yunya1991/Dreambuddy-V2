import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import FeedPage from '@/app/dashboard/feed/page';
import ProposalDetailPage from '@/app/dashboard/board/proposals/[id]/page';
import { boardApi, feedApi } from '@/lib/v3/api';

jest.mock('@/lib/v3/api', () => ({
  feedApi: { list: jest.fn() },
  boardApi: { getProposal: jest.fn() },
}));

const mockParams: { id?: string } = { id: 'p-1' };
const mockBack = jest.fn();

jest.mock('next/navigation', () => ({
  useParams: () => mockParams,
  useRouter: () => ({ back: mockBack }),
}));

const mockedFeed = feedApi as unknown as { list: jest.Mock };
const mockedBoard = boardApi as unknown as { getProposal: jest.Mock };

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(client: QueryClient, node: React.ReactElement) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const DETAIL: Record<string, unknown> = {
  id: 'p-1',
  title: '测试提案标题',
  status: 'APPROVED',
  type: 'strategy',
  direction: 'long',
  symbol: 'BTC',
  confidence: 0.62,
  edgeScore: 1.23,
  description: null,
  rawInput: null,
  source: 'test',
  regime: 'trend',
  stopLoss: 100,
  takeProfit: 120,
  leverage: 2,
  positionSize: 1,
  createdAt: '2026-11-01T00:00:00Z',
  tasks: [],
};

describe('feed 页 Query 迁移（T-C4 逐页 批次 14）', () => {
  beforeEach(() => {
    mockedFeed.list.mockReset().mockResolvedValue([]);
  });

  it('首屏请求一次并渲染空态', async () => {
    renderWith(makeClient(), <FeedPage />);

    await waitFor(() => expect(mockedFeed.list).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('暂无产物数据')).toBeInTheDocument());
  });

  it('切换 workflow 筛选触发带参数的新请求', async () => {
    renderWith(makeClient(), <FeedPage />);
    await waitFor(() => expect(mockedFeed.list).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'V2' }));
    await waitFor(() => expect(mockedFeed.list).toHaveBeenCalledTimes(2));
    expect(mockedFeed.list).toHaveBeenLastCalledWith('trading_v2');
  });
});

describe('board 提案详情页 Query 迁移（T-C4 逐页 批次 14）', () => {
  beforeEach(() => {
    mockParams.id = 'p-1';
    mockedBoard.getProposal.mockReset().mockResolvedValue(DETAIL);
  });

  it('按 id 请求一次并渲染标题', async () => {
    renderWith(makeClient(), <ProposalDetailPage />);

    await waitFor(() => expect(mockedBoard.getProposal).toHaveBeenCalledTimes(1));
    expect(mockedBoard.getProposal).toHaveBeenCalledWith('p-1');
    await waitFor(() => expect(screen.getByText('测试提案标题')).toBeInTheDocument());
  });

  it('id 缺失时不发请求', async () => {
    mockParams.id = undefined as unknown as string;
    renderWith(makeClient(), <ProposalDetailPage />);

    await waitFor(() => expect(screen.getByText('← 返回提案列表')).toBeInTheDocument());
    expect(mockedBoard.getProposal).not.toHaveBeenCalled();
  });
});
