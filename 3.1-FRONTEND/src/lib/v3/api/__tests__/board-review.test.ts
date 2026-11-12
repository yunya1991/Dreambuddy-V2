import { boardApi } from '../board';

describe('boardApi.listReviews（GET /api/board/review）', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  it('调用 GET /api/board/review', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ success: true, data: [] }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;

    await boardApi.listReviews();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/board/review');
    expect(init.method).toBe('GET');
  });

  it('解包 { success, data } 信封并返回评审记录', async () => {
    const record = {
      id: 'r1',
      strategyName: '趋势跟随',
      status: 'APPLIED',
      totalTrades: 12,
      winRate: 0.58,
      pnl: 3.2,
      score: 82,
      review: 'ok',
      appliedAt: '2026-11-01T00:00:00.000Z',
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ success: true, data: [record] }),
    }) as unknown as typeof fetch;

    await expect(boardApi.listReviews()).resolves.toEqual([record]);
  });
});
