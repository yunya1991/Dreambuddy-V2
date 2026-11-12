import { fetchBriefingDetail, fetchBriefingList } from '../briefing';

describe('briefingApi（非标准信封解析）', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
    jest.clearAllMocks();
  });

  it('列表：解析 { success, briefings } 并带 limit 参数', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, briefings: [{ id: 'b1' }] }),
    }) as unknown as typeof fetch;

    await expect(fetchBriefingList(50)).resolves.toEqual([{ id: 'b1' }]);
    expect(global.fetch).toHaveBeenCalledWith('/api/briefings?limit=50');
  });

  it('列表：success=false 抛错（交由 Query 层呈现）', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: false }),
    }) as unknown as typeof fetch;

    await expect(fetchBriefingList()).rejects.toThrow('加载简报列表失败');
  });

  it('列表：HTTP 非 2xx 抛错', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 502 }) as unknown as typeof fetch;
    await expect(fetchBriefingList()).rejects.toThrow('HTTP 502');
  });

  it('详情：解析 { success, briefing }', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, briefing: { id: 'b1', title: 't' } }),
    }) as unknown as typeof fetch;

    await expect(fetchBriefingDetail('b1')).resolves.toEqual({ id: 'b1', title: 't' });
    expect(global.fetch).toHaveBeenCalledWith('/api/briefings/b1');
  });

  it('详情：缺少 briefing 抛错', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    }) as unknown as typeof fetch;

    await expect(fetchBriefingDetail('b1')).rejects.toThrow('加载简报详情失败');
  });
});
