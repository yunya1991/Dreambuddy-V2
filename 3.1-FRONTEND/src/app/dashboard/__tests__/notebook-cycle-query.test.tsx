import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ArtifactGallery } from '@/components/features/notebook/ArtifactGallery';
import NotebookPanel from '@/components/features/notebook/NotebookPanel';
import { CycleThinkingPanel } from '@/components/features/cycle/CycleThinkingPanel';
import { notebookApi } from '@/lib/v3/api';

jest.mock('@/lib/v3/api', () => ({
  __esModule: true,
  notebookApi: { getState: jest.fn() },
}));

const mockedNotebook = notebookApi as unknown as { getState: jest.Mock };

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(node: React.ReactNode) {
  return render(<QueryClientProvider client={makeClient()}>{node}</QueryClientProvider>);
}

describe('notebook / cycle 组件 Query 迁移（T-C4 逐页 批次 23）', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    mockedNotebook.getState.mockReset();
  });

  it('ArtifactGallery 首屏请求一次产物列表并渲染数量', async () => {
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        success: true,
        items: [
          { artifact_id: 'a1', artifact_type: 'report', title: '报告A', created_at: 1, created_at_iso: '', tags: [] },
        ],
      }),
    })) as unknown as typeof fetch;

    renderWith(<ArtifactGallery />);

    await waitFor(() => expect(screen.getByText('1 个产物')).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith('/api/artifacts?limit=50');
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(screen.getByText('报告A')).toBeInTheDocument();
  });

  it('ArtifactGallery 切换类型筛选使用新 URL 请求', async () => {
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({ success: true, items: [] }),
    })) as unknown as typeof fetch;

    renderWith(<ArtifactGallery />);

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/artifacts?limit=50'));
    fireEvent.click(screen.getByText('report'));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/artifacts?type=report&limit=50'));
  });

  it('CycleThinkingPanel 首屏请求一次 /api/cycle 并渲染象限', async () => {
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        success: true,
        effective_confidence: 'medium',
        disclaimer: '研究建议，非交易信号',
        cycle_state: { real_cycle: {}, technical_anchor: {}, sector_transmission: {} },
        strategy_mapping: { inputs: { quadrant: 'Q2-复苏' } },
        execution_state: {},
        x1_metrics_status: { gate: { samples: 1, min_samples: 4 } },
      }),
    })) as unknown as typeof fetch;

    renderWith(<CycleThinkingPanel />);

    await waitFor(() => expect(screen.getByText(/周期象限：Q2-复苏/)).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith('/api/cycle', { cache: 'no-store' });
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('CycleThinkingPanel success=false 时展示错误提示', async () => {
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({ success: false, error: 'boom' }),
    })) as unknown as typeof fetch;

    renderWith(<CycleThinkingPanel />);

    await waitFor(() => expect(screen.getByText(/周期研究数据加载失败：boom/)).toBeInTheDocument());
  });

  it('NotebookPanel 首屏请求一次服务端状态并同步 store', async () => {
    mockedNotebook.getState.mockResolvedValue({
      tasks: [],
      active_task_id: null,
      chain: { nodes: [] },
    });

    renderWith(<NotebookPanel />);

    await waitFor(() => expect(mockedNotebook.getState).toHaveBeenCalledTimes(1));
  });
});
