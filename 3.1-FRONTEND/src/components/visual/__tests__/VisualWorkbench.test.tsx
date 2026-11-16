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

const SIGNAL_MATRIX = {
  id: 'matrix:signals',
  kind: 'matrix',
  spec_version: '1.0',
  title: '加权信号点阵（资产 × 四轴）',
  source_capability: 'D-E19',
  n_scope: 'per_cell',
  dataset: {
    row_labels: ['BTC'],
    col_labels: ['趋势', '惯性', '周期', '前瞻'],
    values: [[0.9, 0.2, null, 0.6]],
  },
  encodings: {},
  annotations: {
    axes: [
      { key: 'trend', label: '趋势', weight: 0.4 },
      { key: 'inertia', label: '惯性', weight: 0.25 },
      { key: 'cycle', label: '周期', weight: 0.15 },
      { key: 'foresight', label: '前瞻', weight: 0.2 },
    ],
    cells: {
      'BTC|trend': { state: 'lit', strength: 0.9, bucket: 'high', sign: 1 },
      'BTC|inertia': { state: 'dim', strength: 0.2, bucket: 'low', sign: -1 },
      'BTC|cycle': { state: 'unavailable', strength: null, bucket: 'none', sign: 0 },
      'BTC|foresight': { state: 'conflict', strength: 0.6, bucket: 'mid', sign: 1 },
    },
    rows: { BTC: { label: '比特币', class: '加密', as_of: '2026-11-15' } },
    light_weights_hash: 'abcdef12',
    thresholds: { lit_pct: 0.76, warm_pct: 0.57 },
  },
  quality_ref: 'quality',
  truncated: false,
  caveat: '历史统计，不代表未来',
};

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

  it('主览图渲染后端 matrix 点阵（状态/符号零重算）', async () => {
    stubFetch({ ...OVERVIEW, visuals: [SIGNAL_MATRIX, ...OVERVIEW.visuals] });

    render(<VisualWorkbench compact />);

    await waitFor(() => expect(screen.getByText('主览图')).toBeInTheDocument());
    expect(screen.getAllByText('趋势').length).toBeGreaterThan(0);
    expect(screen.getByText('比特币')).toBeInTheDocument();
    expect(screen.getByText('加密 · 2026-11-15')).toBeInTheDocument();
  });

  it('图表服务失败时降级提示，不抛异常', async () => {
    stubFetch({ ok: false, error: 'backend down' });

    render(<VisualWorkbench compact />);

    await waitFor(() => expect(screen.getByText('图表服务暂不可用')).toBeInTheDocument());
    expect(screen.getByText(/backend down/)).toBeInTheDocument();
  });
});
