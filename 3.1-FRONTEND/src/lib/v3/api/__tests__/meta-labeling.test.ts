import { fetchMetaLabeling } from '@/lib/v3/api/meta-labeling';

const RESULT = {
  signal: { source: 'technical', name: 'EMA排列', direction: 'long', confidence: 0.72 },
  winProbability: 0.7,
  expectedValue: 0.01,
  decision: 'execute',
  sizeMultiplier: 1.5,
};

describe('meta-labeling 域客户端（非标准信封）', () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('成功时解包 results', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, results: [RESULT] }),
    });

    await expect(fetchMetaLabeling()).resolves.toEqual([RESULT]);
    expect(fetchMock).toHaveBeenCalledWith('/api/meta-labeling', { cache: 'no-store' });
  });

  it('success=false 时返回 null', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, results: [RESULT] }),
    });

    await expect(fetchMetaLabeling()).resolves.toBeNull();
  });

  it('网络异常时返回 null', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));

    await expect(fetchMetaLabeling()).resolves.toBeNull();
  });
});
