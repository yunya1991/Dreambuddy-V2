import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import NewsPage from '@/app/dashboard/news/page';
import FundamentalPage from '@/app/dashboard/fundamental/page';

const ITEMS = [
  {
    rank: 1,
    event_id: 'e1',
    title: '央行降息落地',
    title_short: '央行降息落地',
    topic: 'rates_policy',
    event_type: 'macro',
    importance: 82,
    sentiment: { score: 0.6, label: '利好' },
    source_url: 'https://www.cls.cn/detail/1',
    published_at: '2026-11-15T02:00:00Z',
    source_count: 3,
  },
  {
    rank: 2,
    event_id: 'e2',
    title: '无来源链接的热点',
    topic: 'other',
    event_type: 'other',
    importance: 61,
    sentiment: { score: 0, label: '中性' },
    source_url: null,
    source_count: 1,
  },
  {
    rank: 3,
    event_id: 'e3',
    title: '非 http 协议的热点',
    topic: 'tech_ai',
    event_type: 'news',
    importance: 55,
    sentiment: null,
    source_url: 'javascript:alert(1)',
    source_count: 2,
  },
];

const SNAPSHOT = {
  ts: '2026-11-15T03:00:00Z',
  resistance_3d: { direction: 'UP', direction_score: 0.3, confidence: 0.7, trend_summary: '上行' },
  metrics: {
    core: {},
    breakdown: {
      hot_news_top10: ITEMS,
      theme_clusters: [{ topic: 'rates_policy', label: '利率与央行', count: 2, avg_importance: 70 }],
      hot_news_summary: { total: 3, scored: 3, window_h: 24 },
    },
  },
  signals: [],
  timeseries: [{ ts: 't1', direction_score: 0.1 }],
};

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(node: React.ReactNode) {
  return render(<QueryClientProvider client={makeClient()}>{node}</QueryClientProvider>);
}

describe('新闻页与头条外链（SPEC-20261115）', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => SNAPSHOT,
    })) as unknown as typeof fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('新闻页渲染热点雷达与头条卡，path 为 /api/fundamental/news/snapshot', async () => {
    renderWith(<NewsPage />);

    await waitFor(() => expect(screen.getAllByText('热点雷达 · 新闻影响力榜').length).toBeGreaterThan(0));
    expect(global.fetch).toHaveBeenCalledWith('/api/fundamental/news/snapshot', { cache: 'no-store' });
  });

  it('http(s) 头条卡与标题可新窗口跳转，非 http 与缺失链接降级为纯文本', async () => {
    renderWith(<NewsPage />);

    await waitFor(() => expect(screen.getAllByRole('link', { name: '央行降息落地' }).length).toBeGreaterThan(0));

    const links = screen.getAllByRole('link', { name: '央行降息落地' });
    links.forEach((a) => {
      expect(a).toHaveAttribute('href', 'https://www.cls.cn/detail/1');
      expect(a).toHaveAttribute('target', '_blank');
      expect(a).toHaveAttribute('rel', 'noopener noreferrer');
    });

    expect(screen.queryByRole('link', { name: '无来源链接的热点' })).toBeNull();
    expect(screen.queryByRole('link', { name: '非 http 协议的热点' })).toBeNull();
  });

  it('基本面页不再包含「新闻监控」tab', async () => {
    renderWith(<FundamentalPage />);

    await waitFor(() => expect(screen.getByText('基本面分析')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: '新闻监控' })).toBeNull();
  });
});
