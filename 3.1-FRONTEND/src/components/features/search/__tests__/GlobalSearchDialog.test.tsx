/**
 * GlobalSearchDialog 竞态回归测试
 *
 * 场景：输入 "a" 触发相似案例请求 A，随后输入 "ab" 触发请求 B；
 * B 先返回、A 后返回时，A 的慢响应不得覆盖 B 的结果。
 */

import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';

const mockGet = jest.fn();

jest.mock('@/lib/api-client', () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mockGet(...args) },
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock('@/lib/search/search-core', () => ({
  getSearchIndex: () => ({ search: () => [] }),
  getRecentSearches: () => [],
  addRecentSearch: jest.fn(),
  clearRecentSearches: jest.fn(),
}));

jest.mock('@/lib/search/search-data', () => ({
  ensureSearchLoaded: () => Promise.resolve(),
}));

jest.mock('@/lib/command-palette', () => ({
  buildCommandItems: () => [],
  COMMAND_GROUP_LABELS: {},
}));

// 稳定引用：hydrate 每次渲染都变会让组件的 focus 副作用反复执行（无限重渲染）
const mockHydrate = jest.fn();
const mockStore = { sessions: [], hydrate: mockHydrate, createSession: () => 's1' };

jest.mock('@/stores/agent-session-store', () => ({
  useAgentSessionStore: (selector: (s: unknown) => unknown) => selector(mockStore),
}));

import GlobalSearchDialog from '../GlobalSearchDialog';

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe('GlobalSearchDialog 相似案例竞态', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockGet.mockReset();
  });

  afterEach(() => {
    cleanup();
    jest.useRealTimers();
  });

  it('旧查询的慢响应不会覆盖新查询的结果', async () => {
    const slow = deferred<{ success: boolean; similarCases: Array<{ id: string; title: string; score: number }> }>();
    const fast = deferred<{ success: boolean; similarCases: Array<{ id: string; title: string; score: number }> }>();
    mockGet.mockImplementation((url: string) =>
      url.includes('query=a&') ? slow.promise : fast.promise,
    );

    render(<GlobalSearchDialog open onClose={() => {}} />);
    const input = screen.getByPlaceholderText(/搜索或跳转/);

    fireEvent.change(input, { target: { value: 'a' } });
    await act(async () => {
      jest.advanceTimersByTime(200);
    });

    fireEvent.change(input, { target: { value: 'ab' } });
    await act(async () => {
      jest.advanceTimersByTime(200);
    });

    await act(async () => {
      fast.resolve({ success: true, similarCases: [{ id: 'new', title: '新案例', score: 0.9 }] });
    });
    expect(screen.getByText('新案例')).toBeInTheDocument();

    await act(async () => {
      slow.resolve({ success: true, similarCases: [{ id: 'old', title: '旧案例', score: 0.4 }] });
    });
    expect(screen.queryByText('旧案例')).toBeNull();
    expect(screen.getByText('新案例')).toBeInTheDocument();
  });
});
