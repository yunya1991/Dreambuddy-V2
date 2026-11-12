import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReportsScreen } from '@/components/features/reports/ReportsScreen';
import { GovernanceScreen } from '@/components/features/governance/GovernanceScreen';
import api from '@/lib/api-client';
import { useSessionStore } from '@/stores';
import { boardApi } from '@/lib/v3/api/board';

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

jest.mock('@/lib/v3/api/board', () => ({
  ...(jest.requireActual('@/lib/v3/api/board') as object),
  boardApi: {
    listProposals: jest.fn(),
    vote: jest.fn(),
    getProposalVotes: jest.fn(),
  },
}));

const mockedApi = api as unknown as { get: jest.Mock; post: jest.Mock };
const mockedBoard = boardApi as unknown as {
  listProposals: jest.Mock;
  vote: jest.Mock;
  getProposalVotes: jest.Mock;
};

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
}

function renderWith(node: React.ReactNode) {
  return render(<QueryClientProvider client={makeClient()}>{node}</QueryClientProvider>);
}

const fakeReport = {
  taskId: 't-1',
  taskType: 'analysis',
  intent: '市场分析',
  input: 'BTC 现在怎么样',
  summary: '综合摘要内容',
  overallConfidence: 82,
  totalTokens: 1234,
  durationMs: 5400,
  steps: [],
  createdAt: new Date('2026-01-01').toISOString(),
  deepeningOptions: [],
};

const fakeProposal = (overrides: Record<string, unknown> = {}) => ({
  id: 'p1',
  title: '测试提案',
  status: 'DRAFT',
  type: 'TREND',
  direction: 'BUY',
  symbol: 'BTC/USDT',
  confidence: 0.5,
  edgeScore: 1.0,
  createdAt: new Date('2026-01-01').toISOString(),
  ...overrides,
});

describe('reports / governance 组件 Query 迁移（T-C4 逐页 批次 24）', () => {
  beforeEach(() => {
    mockedApi.get.mockReset();
    mockedApi.post.mockReset();
    mockedBoard.listProposals.mockReset();
    mockedBoard.vote.mockReset();
    mockedBoard.getProposalVotes.mockReset();
    useSessionStore.setState({ lastReportId: null });
  });

  it('ReportsScreen 首屏无 taskId 时不发起请求并展示空态', async () => {
    renderWith(<ReportsScreen />);

    await waitFor(() => expect(screen.getByText('暂无报告')).toBeInTheDocument());
    expect(mockedApi.get).toHaveBeenCalledTimes(0);
  });

  it('ReportsScreen lastReportId 就绪后按 taskId 请求并渲染报告', async () => {
    mockedApi.get.mockResolvedValue(fakeReport);
    useSessionStore.setState({ lastReportId: 't-1' });

    renderWith(<ReportsScreen />);

    await waitFor(() => expect(screen.getByText('综合摘要内容')).toBeInTheDocument());
    const reportCalls = mockedApi.get.mock.calls.filter(([url]) => url === '/api/task/result/t-1');
    expect(reportCalls).toHaveLength(1);
    expect(screen.getByText('市场分析')).toBeInTheDocument();
  });

  it('ReportsScreen 输入关键词 300ms 后请求联想接口并展示建议', async () => {
    mockedApi.get.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/search')) {
        return { success: true, results: [{ id: 't-2', title: '报告一' }] };
      }
      return fakeReport;
    });

    renderWith(<ReportsScreen />);

    const input = screen.getByPlaceholderText('输入任务 ID 或标题关键词模糊搜索...');
    fireEvent.change(input, { target: { value: 'BTC' } });

    await waitFor(() =>
      expect(mockedApi.get).toHaveBeenCalledWith('/api/search?query=BTC&module=report&limit=8'),
    );
    await waitFor(() => expect(screen.getByText('报告一')).toBeInTheDocument());
  });

  it('GovernanceScreen 首屏一次拉取提案与逐条投票计数', async () => {
    mockedBoard.listProposals.mockResolvedValue([fakeProposal({ id: 'p1' }), fakeProposal({ id: 'p2' })]);
    mockedBoard.getProposalVotes.mockResolvedValue([{ id: 'v1', vote: 'FOR' }]);

    renderWith(<GovernanceScreen />);

    await waitFor(() => expect(screen.getAllByText('测试提案')).toHaveLength(2));
    expect(mockedBoard.listProposals).toHaveBeenCalledTimes(1);
    expect(mockedBoard.getProposalVotes).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText('+1')).toHaveLength(2);
  });

  it('GovernanceScreen 点击赞成调用 vote 并刷新计数', async () => {
    mockedBoard.listProposals.mockResolvedValue([fakeProposal({ id: 'p1', title: '可投票提案' })]);
    mockedBoard.getProposalVotes.mockResolvedValue([
      { id: 'v1', vote: 'FOR' },
      { id: 'v2', vote: 'AGAINST' },
    ]);
    mockedBoard.vote.mockResolvedValue({ success: true });

    renderWith(<GovernanceScreen />);

    await waitFor(() => expect(screen.getByText('可投票提案')).toBeInTheDocument());
    expect(screen.getByText('+1')).toBeInTheDocument();
    expect(screen.getByText('-1')).toBeInTheDocument();

    fireEvent.click(screen.getByText('赞成'));

    await waitFor(() => expect(mockedBoard.vote).toHaveBeenCalledWith('p1', 'FOR'));
  });
});
