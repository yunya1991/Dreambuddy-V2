/**
 * GET /api/news/items 本地令牌门禁 + 只读契约测试。
 * 不触网、不执行 Python：mock util.promisify 返回受控执行器。
 */
const mockRun = jest.fn();

jest.mock('util', () => ({ promisify: () => mockRun }));
jest.mock('child_process', () => ({ execFile: jest.fn() }));
jest.mock('next/server', () => ({
  NextResponse: {
    json: (body: unknown, init?: { status?: number; headers?: Record<string, string> }) => ({
      status: init?.status ?? 200,
      body,
      headers: init?.headers ?? {},
    }),
  },
}));

import { GET, POST } from '../route';

type MockResponse = { status: number; body: Record<string, unknown>; headers: Record<string, string> };

function makeRequest(token?: string, params: Record<string, string> = {}) {
  return {
    headers: { get: (key: string) => (key === 'x-dreambuddy-local-token' ? token ?? null : null) },
    nextUrl: {
      searchParams: {
        get: (key: string) => params[key] ?? null,
      },
    },
  } as never;
}

describe('/api/news/items', () => {
  beforeEach(() => {
    process.env.DREAMBUDDY_NEWS_LOCAL_TOKEN = 'secret-token';
    mockRun.mockReset();
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    delete process.env.DREAMBUDDY_NEWS_LOCAL_TOKEN;
    jest.restoreAllMocks();
  });

  it('缺少令牌返回 403，且不执行脚本', async () => {
    const res = (await GET(makeRequest())) as unknown as MockResponse;
    expect(res.status).toBe(403);
    expect(res.body).toEqual({ ok: false, error: 'E_LOCAL_ONLY' });
    expect(mockRun).not.toHaveBeenCalled();
  });

  it('令牌错误返回 403', async () => {
    const res = (await GET(makeRequest('wrong'))) as unknown as MockResponse;
    expect(res.status).toBe(403);
    expect(mockRun).not.toHaveBeenCalled();
  });

  it('令牌正确时透传过滤参数并返回明细', async () => {
    mockRun.mockResolvedValue({
      stdout: JSON.stringify({ schema: 'news_items/v1', items: [{ event_id: 'a' }] }),
    });
    const res = (await GET(
      makeRequest('secret-token', { window: '24h', limit: '2', q: 'BTC' })
    )) as unknown as MockResponse;

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ schema: 'news_items/v1', items: [{ event_id: 'a' }] });
    expect(res.headers['Cache-Control']).toBe('private, max-age=15');
    const args = mockRun.mock.calls[0][1] as string[];
    expect(args).toEqual(
      expect.arrayContaining(['--window', '24h', '--limit', '2', '--q', 'BTC'])
    );
  });

  it('容忍警告行与多行 JSON', async () => {
    mockRun.mockResolvedValue({
      stdout: 'warning: deprecated\n' + JSON.stringify({ schema: 'news_items/v1', items: [] }, null, 2),
    });
    const res = (await GET(makeRequest('secret-token'))) as unknown as MockResponse;
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ schema: 'news_items/v1', items: [] });
  });

  it('脚本失败返回 503', async () => {
    mockRun.mockRejectedValue(new Error('boom'));
    const res = (await GET(makeRequest('secret-token'))) as unknown as MockResponse;
    expect(res.status).toBe(503);
    expect(res.body).toEqual({ ok: false, error: 'E_NEWS_ITEMS' });
  });

  it('POST 明确只读 405', async () => {
    const res = (await POST()) as unknown as MockResponse;
    expect(res.status).toBe(405);
    expect(res.body).toEqual({ ok: false, error: 'E_READ_ONLY' });
  });
});
