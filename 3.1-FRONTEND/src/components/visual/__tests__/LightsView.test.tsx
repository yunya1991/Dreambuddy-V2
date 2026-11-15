import React from 'react';
import { render, screen } from '@testing-library/react';
import { LightsView } from '../LightsView';
import type { LightsPayload } from '../types';

const PAYLOAD: LightsPayload = {
  ok: true,
  answer: '12 个标的点亮投影',
  meta: {
    light_weights_mode: 'on',
    light_weights_hash: '359734d9ccc8eb60',
    thresholds: { lit_pct: 0.7, warm_pct: 0.4 },
    thresholds_uncalibrated: true,
    min_rows: 250,
  },
  rows: [
    {
      symbol: 'BTC',
      class: '加密',
      as_of: '2026-11-12',
      strength: 0.4878,
      n: 1094,
      axes: {
        trend: { state: 'warm', strength: 0.41, bucket: 'mid' },
        inertia: { state: 'lit', strength: 1.0, bucket: 'high' },
        cycle: { state: 'unavailable', strength: null, bucket: 'none' },
        foresight: { state: 'dim', strength: 0.0, bucket: 'low' },
      },
      summary: { lit_n: 1, warm_n: 1, conflict_n: 0, unavailable_n: 1 },
    },
  ],
};

describe('LightsView（D-E19 五态点亮投影）', () => {
  it('渲染五态图例与四轴状态，不出现方向词', () => {
    render(<LightsView payload={PAYLOAD} />);

    expect(screen.getByText('BTC')).toBeInTheDocument();
    expect(screen.getAllByText('点亮').length).toBeGreaterThan(0);
    expect(screen.getAllByText('预热').length).toBeGreaterThan(0);
    expect(screen.getAllByText('暗淡').length).toBeGreaterThan(0);
    expect(screen.getAllByText('不可用').length).toBeGreaterThan(0);
    expect(screen.getByText('阈值未标定')).toBeInTheDocument();
    expect(screen.queryByText(/看涨|看跌|建议/)).not.toBeInTheDocument();
  });

  it('行级强度条使用后端标定阈值，不回退到硬编码默认值', () => {
    const payload: LightsPayload = {
      ...PAYLOAD,
      meta: {
        ...PAYLOAD.meta,
        thresholds: { lit_pct: 0.764706, warm_pct: 0.5724 },
        thresholds_uncalibrated: false,
      },
      rows: [{ ...PAYLOAD.rows[0], strength: 0.75 }],
    };
    const { container } = render(<LightsView payload={payload} />);

    const bar = container.querySelector('[style*="width: 75%"]');
    expect(bar).toHaveClass('bg-amber-400');
    expect(bar).not.toHaveClass('bg-emerald-400');
  });

  it('后端阈值缺失时强度条置灰，不引入前端兜底阈值', () => {
    const payload: LightsPayload = {
      ...PAYLOAD,
      meta: { ...PAYLOAD.meta, thresholds: undefined },
      rows: [{ ...PAYLOAD.rows[0], strength: 0.75 }],
    };
    const { container } = render(<LightsView payload={payload} />);

    const bar = container.querySelector('[style*="width: 75%"]');
    expect(bar).toHaveClass('bg-slate-500');
    expect(bar).not.toHaveClass('bg-emerald-400');
    expect(bar).not.toHaveClass('bg-amber-400');
  });

  it('后端无点亮结果时走空态，不抛异常', () => {
    render(<LightsView payload={{ ok: false, rows: [] }} />);
    expect(screen.getByText('点亮投影不可用')).toBeInTheDocument();
  });
});
