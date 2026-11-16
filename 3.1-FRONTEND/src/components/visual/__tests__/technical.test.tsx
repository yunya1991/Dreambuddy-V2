import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { LightsTimeline } from '../LightsTimeline';
import { OverlayChart } from '../OverlayChart';
import { SignalFeedback } from '../SignalFeedback';
import { SignalMatrix } from '../SignalMatrix';
import type { VisualSpec } from '../types';

const MATRIX: VisualSpec = {
  id: 'matrix:signals',
  kind: 'matrix',
  spec_version: '1.0',
  title: '加权信号点阵',
  source_capability: 'D-E19',
  n_scope: 'per_cell',
  dataset: {
    row_labels: ['BTC', 'XAU'],
    col_labels: ['趋势', '惯性', '周期', '前瞻'],
    values: [
      [0.9, 0.2, null, 0.6],
      [0.4, 0.3, 0.2, 0.1],
    ],
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
    rows: {
      BTC: { label: '比特币', class: '加密', as_of: '2026-11-15', strength: 0.82 },
      XAU: { label: '黄金', class: '避险', as_of: '2026-11-15', strength: 0.31 },
    },
    thresholds: { lit_pct: 0.76, warm_pct: 0.57 },
    light_weights_hash: 'abcdef123456',
  },
  quality_ref: 'quality',
  truncated: false,
  caveat: '历史统计，不代表未来',
};

describe('SignalMatrix（T9-1）', () => {
  it('渲染四轴 + 合成列 + 五态图例', () => {
    render(<SignalMatrix visual={MATRIX} />);
    expect(screen.getByText('合成')).toBeInTheDocument();
    expect(screen.getAllByText('趋势').length).toBeGreaterThan(0);
    expect(screen.getAllByText('比特币').length).toBeGreaterThan(0);
    expect(screen.getByText('82%')).toBeInTheDocument();
    ['点亮', '预热', '暗淡', '冲突', '不可用'].forEach((label) => {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    });
  });

  it('没有行列标签时给空态，不伪造点阵', () => {
    render(<SignalMatrix visual={{ ...MATRIX, dataset: {} }} />);
    expect(screen.getByText('点阵无数据')).toBeInTheDocument();
  });
});

const LIGHT_ROWS = [
  {
    symbol: 'BTC',
    class: '加密',
    as_of: '2026-11-16',
    axes: {},
    strength: 0.81,
    summary: { lit_n: 2, warm_n: 1, conflict_n: 0, unavailable_n: 1 },
  },
  {
    symbol: 'XAU',
    class: '避险',
    as_of: '2026-11-16',
    axes: {},
    strength: 0.42,
    summary: { lit_n: 0, warm_n: 1, conflict_n: 1, unavailable_n: 2 },
  },
];

describe('LightsTimeline（T9-2）', () => {
  it('无期次时空态，不补造影带', () => {
    render(<LightsTimeline periods={[]} />);
    expect(screen.getByText('点亮影带无数据')).toBeInTheDocument();
  });

  it('有期次时渲染影带并显示期数与回放按钮', () => {
    render(
      <LightsTimeline
        periods={[
          { as_of: '2026-11-02', rows: LIGHT_ROWS },
          { as_of: '2026-11-16', rows: LIGHT_ROWS },
        ]}
        onRequestHistory={() => undefined}
      />,
    );
    expect(screen.getAllByText(/2 期/).length).toBeGreaterThan(0);
    expect(screen.getByText('回放最近 12 期')).toBeInTheDocument();
    expect(screen.getAllByText('BTC').length).toBeGreaterThan(0);
  });
});

describe('OverlayChart（T9-3）', () => {
  const points = [
    { x: '2026-11-14', y: 100, smoothed: 99 },
    { x: '2026-11-15', y: 102, smoothed: 101 },
  ];

  it('叠加层来源逐项标注，ATR 缺失时标「未接线」', () => {
    render(
      <OverlayChart
        points={points}
        percentile={{ value: 0.66, lookback: 250, sample_n: 250 }}
        litDays={['2026-11-15']}
        sources={[
          { id: 'price', label: '价格', capability: 'D-E15', status: 'ok' },
          { id: 'atr', label: 'ATR 带', capability: null, status: 'missing' },
          { id: 'percentile', label: '历史分位', capability: 'D-A04', status: 'ok' },
        ]}
      />,
    );
    expect(screen.getByText(/价格 · D-E15/)).toBeInTheDocument();
    expect(screen.getByText(/ATR 带 · 未接线/)).toBeInTheDocument();
    expect(screen.getByText(/66%/)).toBeInTheDocument();
  });

  it('无价格序列时给提示，不画空图', () => {
    render(<OverlayChart points={[]} />);
    expect(screen.getByText(/未提供价格序列/)).toBeInTheDocument();
  });
});

describe('SignalFeedback（T9-4）', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  function stub(payload: unknown) {
    global.fetch = jest.fn(async () => ({ json: async () => payload })) as unknown as typeof fetch;
  }

  it('账本为空时显示空态，不伪造命中率', async () => {
    stub({ ok: true, horizons: [], answer: '信号账本暂无 allowed 记录' });
    render(<SignalFeedback />);
    await waitFor(() => expect(screen.getByText('暂无已结算信号')).toBeInTheDocument());
    expect(screen.getByText(/signal_journal|信号账本暂无/)).toBeInTheDocument();
  });

  it('有数据时分母展示 n_eff 且与样本一致', async () => {
    stub({
      ok: true,
      as_of: '2026-11-16',
      horizons: [
        {
          horizon: 5,
          totals: { n_raw: 9, n_eff: 3, hits: 2, hit_rate: 0.6667 },
          targets: [
            {
              target: 'BTC',
              n_raw: 9,
              n_eff: 3,
              hits: 2,
              hit_rate: 0.6667,
              base_rate: 0.5,
              excess_hit: 0.1667,
              avg_forward: 0.012,
            },
          ],
          buckets: [{ strength: 'strong', n_eff: 3, hits: 2, hit_rate: 0.6667 }],
        },
      ],
      quality: { status: 'good', sample_n: 3 },
    });
    render(<SignalFeedback />);
    await waitFor(() => expect(screen.getByText('信号 → 后 5 日')).toBeInTheDocument());
    expect(screen.getByText(/非重叠 n_eff 3/)).toBeInTheDocument();
    expect(screen.getByText('+16.7%')).toBeInTheDocument();
    expect(screen.getByText(/分母 = n_eff/)).toBeInTheDocument();
  });
});
