import { fetchTradingRanking } from '../ranking';

describe('rankingApi（mock 降级契约）', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  it('成功：解析 items + metrics', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, items: [{ id: 'r1' }], metrics: { total: 1 } }),
    }) as unknown as typeof fetch;

    await expect(fetchTradingRanking()).resolves.toEqual({
      items: [{ id: 'r1' }],
      metrics: { total: 1 },
    });
    expect(global.fetch).toHaveBeenCalledWith('/api/trading-ranking/today', { cache: 'no-store' });
  });

  it('成功但空列表：返回空 items（页面据 length 回落 mock）', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, items: [] }),
    }) as unknown as typeof fetch;

    await expect(fetchTradingRanking()).resolves.toEqual({ items: [], metrics: null });
  });

  it('success=false 返回 null（保持 mock）', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: false }),
    }) as unknown as typeof fetch;

    await expect(fetchTradingRanking()).resolves.toBeNull();
  });

  it('HTTP 非 2xx 返回 null', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 503 }) as unknown as typeof fetch;
    await expect(fetchTradingRanking()).resolves.toBeNull();
  });

  it('网络异常返回 null，不向上抛', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
    await expect(fetchTradingRanking()).resolves.toBeNull();
  });
});
