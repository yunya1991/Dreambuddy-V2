import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { VisualWorkbench } from '../VisualWorkbench';

const OVERVIEW = {
  ok: true,
  as_of: '2026-11-15',
  assets: ['BTC', 'XAU'],
  visuals: [
    {
      id: 'v-table',
      kind: 'table',
      spec_version: 'visual.v1',
      title: '能力清单',
      source_capability: 'D-E12',
      n_scope: 'global',
      dataset: {
        columns: [
          { key: 'symbol', label: '资产', type: 'string' },
          { key: 'score', label: '评分', type: 'number' },
        ],
        rows: [{ symbol: 'BTC', score: 0.5 }],
      },
      encodings: {},
      quality_ref: 'D-E12',
      truncated: false,
      caveat: '',
    },
  ],
  recommended: [{ id: 'v-table', title: '能力清单', kind: 'table', reason: '样本充足' }],
  degraded: false,
};

function stubFetch(overview: unknown, ok = true) {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => ({
    ok,
    json: async () => (String(input).startsWith('/api/visual/overview') ? overview : { ok: false }),
  })) as unknown as typeof fetch;
}
describe('VisualWorkbench（基本面「数据与图表」tab 共用）', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('首屏渲染后端图表，compact 模式不重复页面标题', async () => {
    stubFetch(OVERVIEW);

    render(<VisualWorkbench compact />);

    await waitFor(() => expect(screen.getAllByText('能力清单').length).toBeGreaterThan(0));
    expect(screen.getByText('BTC')).toBeInTheDocument();
    expect(screen.queryByText('数据与图表')).not.toBeInTheDocument();
  });

  it('图表服务失败时降级提示，不抛异常', async () => {
    stubFetch({ ok: false, error: 'backend down' });

    render(<VisualWorkbench compact />);

    await waitFor(() => expect(screen.getByText('图表服务暂不可用')).toBeInTheDocument());
    expect(screen.getByText(/backend down/)).toBeInTheDocument();
  });
});
