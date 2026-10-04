// ============================================
// GovernanceScreen 组件测试
// 验证: 接入 boardApi.listProposals、loading/empty/error 三态、stage 由 status 派生
// P1: 恢复投票列 (+N/-N 计数)、投票按钮交互、dataSource 角标
// ============================================

import React from 'react';
import { jest } from '@jest/globals';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { boardApi, type Proposal } from '@/lib/v3/api/board';
import { GovernanceScreen } from './GovernanceScreen';

// Mock boardApi — 保留类型导出,只替换 boardApi 对象 (P1: 加 vote + getProposalVotes)
jest.mock('@/lib/v3/api/board', () => ({
  ...(jest.requireActual('@/lib/v3/api/board') as object),
  boardApi: {
    listProposals: jest.fn(),
    vote: jest.fn(),
    getProposalVotes: jest.fn(),
  },
}));

const mockedListProposals = boardApi.listProposals as unknown as jest.MockedFunction<typeof boardApi.listProposals>;
const mockedVote = boardApi.vote as unknown as jest.MockedFunction<typeof boardApi.vote>;
const mockedGetProposalVotes = boardApi.getProposalVotes as unknown as jest.MockedFunction<typeof boardApi.getProposalVotes>;

const fakeProposal = (overrides: Partial<Proposal> = {}): Proposal => ({
  id: '1',
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

beforeEach(() => {
  mockedListProposals.mockReset();
  mockedVote.mockReset();
  mockedGetProposalVotes.mockReset();
  // 默认: getProposalVotes 返回空数组 (避免 useEffect 调用时 undefined 报错)
  mockedGetProposalVotes.mockResolvedValue([]);
});

describe('GovernanceScreen', () => {
  it('shows loading skeleton before fetch resolves', async () => {
    // 永不 resolve — 保持 loading 状态
    mockedListProposals.mockReturnValue(new Promise(() => {}));
    render(<GovernanceScreen />);
    // 骨架屏用 animate-pulse 类，至少存在 1 个占位元素
    const skeletons = document.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('renders proposals and derives stage labels from StrategyStatus', async () => {
    mockedListProposals.mockResolvedValue([
      fakeProposal({ id: '1', title: '草稿态提案', status: 'DRAFT' }),
      fakeProposal({ id: '2', title: '已批准提案', status: 'APPROVED' }),
      fakeProposal({ id: '3', title: '执行中提案', status: 'APPLIED' }),
    ]);
    render(<GovernanceScreen />);

    await waitFor(() => {
      expect(screen.getByText('草稿态提案')).toBeInTheDocument();
    });
    // stage 派生标签 (流程图 + 卡片阶段标签都可能出现, 用 getAllByText 兼容多处匹配)
    expect(screen.getAllByText(/草稿/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/审批/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/应用/).length).toBeGreaterThan(0);
    expect(screen.getByText('已批准提案')).toBeInTheDocument();
    expect(screen.getByText('执行中提案')).toBeInTheDocument();
  });

  it('renders empty state when API returns []', async () => {
    mockedListProposals.mockResolvedValue([]);
    render(<GovernanceScreen />);

    await waitFor(() => {
      expect(screen.getByText('暂无提案')).toBeInTheDocument();
    });
  });

  it('renders error banner when API rejects', async () => {
    mockedListProposals.mockRejectedValue(new Error('boom'));
    render(<GovernanceScreen />);

    await waitFor(() => {
      // 错误横幅显示错误消息
      expect(screen.getByText(/boom/)).toBeInTheDocument();
    });
  });

  it('renders votes column with +N / -N counts (P1)', async () => {
    mockedListProposals.mockResolvedValue([
      fakeProposal({ id: '1', title: '提案一', status: 'DRAFT' }),
      fakeProposal({ id: '2', title: '提案二', status: 'APPROVED' }),
    ]);
    // mock getProposalVotes 返回 3 FOR + 1 AGAINST
    mockedGetProposalVotes.mockResolvedValue([
      { id: 'v1', vote: 'FOR' },
      { id: 'v2', vote: 'FOR' },
      { id: 'v3', vote: 'FOR' },
      { id: 'v4', vote: 'AGAINST' },
    ]);

    render(<GovernanceScreen />);

    await waitFor(() => {
      expect(screen.getByText('提案一')).toBeInTheDocument();
    });

    // P1: 应出现 "+3" (FOR 计数) 和 "-1" (AGAINST 计数) — 2 个提案共享同一 mock, 各显示一次
    expect(screen.getAllByText('+3')).toHaveLength(2);
    expect(screen.getAllByText('-1')).toHaveLength(2);
  });

  it('does NOT render hardcoded mock proposals (BTC 多头策略调整 etc.)', async () => {
    // 真实 API 返回空数组,绝不能回退到硬编码 mock
    mockedListProposals.mockResolvedValue([]);
    render(<GovernanceScreen />);

    await waitFor(() => {
      expect(screen.getByText('暂无提案')).toBeInTheDocument();
    });
    // 防止回归: 硬编码的 3 条 mock 不应再出现
    expect(screen.queryByText('BTC 多头策略调整')).toBeNull();
    expect(screen.queryByText('SOL 仓位减半')).toBeNull();
    expect(screen.queryByText('ETH 链上分析请求')).toBeNull();
  });

  // ========== P1 新增用例 ==========

  it('clicking FOR button calls boardApi.vote and refreshes counts (P1)', async () => {
    mockedListProposals.mockResolvedValue([
      fakeProposal({ id: 'p1', title: '可投票提案', status: 'DRAFT' }),
    ]);
    // 初始: 3 FOR + 1 AGAINST
    mockedGetProposalVotes.mockResolvedValueOnce([
      { id: 'v1', vote: 'FOR' }, { id: 'v2', vote: 'FOR' }, { id: 'v3', vote: 'FOR' },
      { id: 'v4', vote: 'AGAINST' },
    ]);
    // 点击后: 4 FOR + 1 AGAINST
    mockedGetProposalVotes.mockResolvedValueOnce([
      { id: 'v1', vote: 'FOR' }, { id: 'v2', vote: 'FOR' }, { id: 'v3', vote: 'FOR' },
      { id: 'v4', vote: 'FOR' }, { id: 'v5', vote: 'AGAINST' },
    ]);
    mockedVote.mockResolvedValue({ success: true });

    render(<GovernanceScreen />);

    await waitFor(() => {
      expect(screen.getByText('可投票提案')).toBeInTheDocument();
    });
    // 初始计数 +3
    expect(screen.getByText('+3')).toBeInTheDocument();

    // 点击赞成按钮
    const forButton = screen.getByText('赞成');
    await userEvent.click(forButton);

    await waitFor(() => {
      expect(mockedVote).toHaveBeenCalledWith('p1', 'FOR');
      // 计数刷新为 +4
      expect(screen.getByText('+4')).toBeInTheDocument();
    });
  });

  it('renders （演示数据） badge when dataSource=mock, hides when db (P1)', async () => {
    // 场景 1: dataSource='mock' → 显示角标
    mockedListProposals.mockResolvedValueOnce([
      fakeProposal({ id: '1', title: '演示提案', status: 'DRAFT', dataSource: 'mock' }),
    ]);
    const { unmount } = render(<GovernanceScreen />);
    await waitFor(() => {
      expect(screen.getByText('演示提案')).toBeInTheDocument();
    });
    expect(screen.getByText('（演示数据）')).toBeInTheDocument();
    unmount();

    // 场景 2: dataSource='db' → 不显示角标
    mockedListProposals.mockResolvedValueOnce([
      fakeProposal({ id: '2', title: '真实提案', status: 'DRAFT', dataSource: 'db' }),
    ]);
    render(<GovernanceScreen />);
    await waitFor(() => {
      expect(screen.getByText('真实提案')).toBeInTheDocument();
    });
    expect(screen.queryByText('（演示数据）')).toBeNull();
  });
});
