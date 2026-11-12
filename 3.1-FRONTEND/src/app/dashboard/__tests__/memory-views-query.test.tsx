import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DocIndexView } from '@/components/features/memory/DocIndexView';
import { SkillIndexView } from '@/components/features/memory/SkillIndexView';
import { DZEChainView } from '@/components/features/memory/DZEChainView';

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderWith(node: React.ReactNode) {
  return render(<QueryClientProvider client={makeClient()}>{node}</QueryClientProvider>);
}

function stubFetch(map: Record<string, unknown>) {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const key = String(input);
    return {
      ok: key in map,
      json: async () => map[key] ?? null,
    };
  }) as unknown as typeof fetch;
}

describe('memory 页视图 Query 迁移（T-C4 逐页 批次 22）', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('DocIndexView 首屏请求一次文档索引并渲染统计与新鲜度', async () => {
    stubFetch({
      '/api/docs/index': {
        docs: [
          { path: 'a.md', root: '1-ARCH', category: 'spec', last_synced: '', cognitive_linked: true, size_bytes: 10 },
          { path: 'b.md', root: '1-ARCH', category: 'spec', last_synced: '', cognitive_linked: false, size_bytes: 20 },
        ],
        reconcile: { changed: 2, last_indexed_at: '2026-11-12T10:00:00Z' },
      },
    });

    renderWith(<DocIndexView />);

    await waitFor(() => expect(screen.getByText('总文档数')).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith('/api/docs/index');
    expect(global.fetch).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.getByText('2 个文件待重索引')).toBeInTheDocument());
  });

  it('DocIndexView 索引不可用时展示降级提示（FAIL-OPEN）', async () => {
    global.fetch = jest.fn(async () => ({ ok: false, json: async () => null })) as unknown as typeof fetch;

    renderWith(<DocIndexView />);

    await waitFor(() => expect(screen.getByText(/文档索引后端不可达/)).toBeInTheDocument());
  });

  it('SkillIndexView 首屏请求列表与 active 统计各一次并汇总', async () => {
    stubFetch({
      '/api/skills/index': {
        skills: [
          { name: 's1', status: 'active', category: 'debate', triggers: [], confidence: 0.9, version: '1.0', cognitive_links: [] },
          { name: 's2', status: 'active', category: 'debate', triggers: [], confidence: 0.8, version: '1.0', cognitive_links: [] },
          { name: 's3', status: 'shadow', category: 'memory', triggers: [], confidence: 0.5, version: '0.9', cognitive_links: [] },
        ],
        total_count: 3,
      },
      '/api/skills/index?status=active': { skills: [] },
    });

    renderWith(<SkillIndexView />);

    await waitFor(() => expect(screen.getByText('总 Skill 数')).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith('/api/skills/index');
    expect(global.fetch).toHaveBeenCalledWith('/api/skills/index?status=active');
    expect(global.fetch).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByText('3')).toBeInTheDocument());
  });

  it('SkillIndexView 索引不可用时展示降级提示（FAIL-OPEN）', async () => {
    global.fetch = jest.fn(async () => ({ ok: false, json: async () => null })) as unknown as typeof fetch;

    renderWith(<SkillIndexView />);

    await waitFor(() => expect(screen.getByText(/Skill 索引后端不可达/)).toBeInTheDocument());
  });

  it('DZEChainView 首屏请求一次 cognitive/stats 并渲染分类轴分布', async () => {
    stubFetch({
      '/api/cognitive/stats': {
        memory: { type_distribution: { experience: 4, knowledge: 2, observation: 1 } },
      },
    });

    renderWith(<DZEChainView />);

    await waitFor(() =>
      expect(screen.getByText('4-MEMORY 分类轴分布（DZE 概念对齐）')).toBeInTheDocument(),
    );
    expect(global.fetch).toHaveBeenCalledWith('/api/cognitive/stats');
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});
