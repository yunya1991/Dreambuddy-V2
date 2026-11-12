import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import BdsmPage from '@/app/dashboard/bdsm/page';
import OpsPage from '@/app/dashboard/ops/page';
import BdsmAPI from '@/lib/bdsm-api';
import { opsApi } from '@/lib/v3/api';

jest.mock('@/lib/bdsm-api', () => ({
  __esModule: true,
  default: { fetchSnapshot: jest.fn() },
}));

jest.mock('@/lib/v3/api', () => ({
  opsApi: {
    getQueues: jest.fn(),
    getDecisionLevels: jest.fn(),
  },
}));

const mockedBdsm = BdsmAPI as unknown as { fetchSnapshot: jest.Mock };
const mockedOps = opsApi as unknown as { getQueues: jest.Mock; getDecisionLevels: jest.Mock };

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(client: QueryClient, node: React.ReactElement) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const SNAPSHOT = {
  snapshot_date: '2026-11-12',
  status: 'error',
  note: '快照暂不可用',
  error_message: 'snapshot_unavailable',
  coins: {},
  sector_valuation_summary: {},
};

describe('bdsm / ops 轮询页 Query 迁移（T-C4 逐页 批次 17）', () => {
  beforeEach(() => {
    mockedBdsm.fetchSnapshot.mockReset().mockResolvedValue(SNAPSHOT);
    mockedOps.getQueues.mockReset().mockResolvedValue({
      total_tasks: 128,
      pending_tasks: 12,
      processing_tasks: 5,
      completed_tasks: 108,
      failed_tasks: 3,
      avg_latency_ms: 246,
      queue_depth_by_department: { trading: 7 },
      items: [],
    });
    mockedOps.getDecisionLevels.mockReset().mockResolvedValue([]);
  });

  it('bdsm 首屏请求一次并渲染快照日期', async () => {
    renderWith(makeClient(), <BdsmPage />);

    await waitFor(() => expect(mockedBdsm.fetchSnapshot).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText('2026-11-12')).toBeInTheDocument());
  });

  it('bdsm 失败时渲染错误信息', async () => {
    mockedBdsm.fetchSnapshot.mockRejectedValue(new Error('boom'));
    renderWith(makeClient(), <BdsmPage />);

    await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument());
  });

  it('ops 首屏两接口各请求一次并渲染统计', async () => {
    renderWith(makeClient(), <OpsPage />);

    await waitFor(() => expect(screen.getByText('运维监控台')).toBeInTheDocument());
    expect(mockedOps.getQueues).toHaveBeenCalledTimes(1);
    expect(mockedOps.getDecisionLevels).toHaveBeenCalledTimes(1);
    expect(screen.getByText('128')).toBeInTheDocument();
  });

  it('ops 失败时回落 mock 并提示已加载模拟数据', async () => {
    mockedOps.getQueues.mockRejectedValue(new Error('hub_offline'));
    mockedOps.getDecisionLevels.mockRejectedValue(new Error('hub_offline'));
    renderWith(makeClient(), <OpsPage />);

    await waitFor(() => expect(screen.getByText('（已加载模拟数据）')).toBeInTheDocument());
    expect(screen.getByText('128')).toBeInTheDocument();
  });
});
