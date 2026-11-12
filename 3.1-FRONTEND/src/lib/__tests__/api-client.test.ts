/**
 * api-client.test.ts — T-C2 REST 信封解析
 * mock global fetch, 覆盖 3 形态 + 错误码 + trace_id/version.
 * jsdom 无 Response/Headers 构造, 用普通对象 mock Response.
 */

import api, { ERROR_CODE, ApiException } from '@/lib/api-client';

type FetchResp = {
  ok: boolean;
  status: number;
  statusText: string;
  headers: { get: (k: string) => string | null };
  json: () => Promise<unknown>;
};

function fakeResponse(status: number, body: unknown, headerMap: Record<string, string> = {}): FetchResp {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    headers: { get: (k) => headerMap[k] ?? null },
    json: async () => body,
  };
}

let fetchMock: jest.Mock;

beforeAll(() => {
  fetchMock = jest.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

beforeEach(() => {
  fetchMock.mockReset();
  // 默认 fetch 抛错, 每个用例显式 mock
});

describe('api-client: envelope 3 shapes', () => {
  it('shape ① success:true + data -> returns data', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(200, { success: true, data: { ok: 1 } }),
    );
    const res = await api.get<{ ok: number }>('/api/foo');
    expect(res).toEqual({ ok: 1 });
  });

  it('shape ① success:false + error -> throws ApiException', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(200, { success: false, error: { code: 422, message: 'invalid' } }),
    );
    await expect(api.get('/api/foo')).rejects.toMatchObject({ code: 422, message: 'invalid' });
  });

  it('shape ② old ok:true + data -> auto-compat', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(200, { ok: true, data: { id: 42 } }),
    );
    const res = await api.get<{ id: number }>('/api/agent/plan');
    expect(res).toEqual({ id: 42 });
  });

  it('shape ② old ok:false -> throws ApiException', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(200, { ok: false, error: 'model_not_configured' }),
    );
    await expect(api.get('/api/agent/plan')).rejects.toBeInstanceOf(ApiException);
  });

  it('shape ③ bare JSON -> auto-wrap returns body', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(200, { items: [1, 2, 3] }),
    );
    const res = await api.get<{ items: number[] }>('/api/reports');
    expect(res).toEqual({ items: [1, 2, 3] });
  });
});

describe('api-client: HTTP error code mapping', () => {
  it('401 -> AUTH_REQUIRED', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(401, { success: false, error: { code: 401, message: 'Unauthorized' } }),
    );
    await expect(api.get('/api/protected')).rejects.toMatchObject({ code: ERROR_CODE.AUTH_REQUIRED });
  });

  it('404 -> NOT_FOUND', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(fakeResponse(404, {}));
    await expect(api.get('/api/missing')).rejects.toMatchObject({ code: ERROR_CODE.NOT_FOUND });
  });

  it('429 -> RATE_LIMITED', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(fakeResponse(429, {}));
    await expect(api.get('/api/fast')).rejects.toMatchObject({ code: ERROR_CODE.RATE_LIMITED });
  });

  it('504 -> UPSTREAM_TIMEOUT', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(fakeResponse(504, {}));
    await expect(api.get('/api/slow')).rejects.toMatchObject({ code: ERROR_CODE.UPSTREAM_TIMEOUT });
  });

  it('timeout -> UPSTREAM_TIMEOUT', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockRejectedValueOnce(new DOMException('aborted', 'AbortError'));
    await expect(api.get('/api/slow', undefined, { timeout: 1 } as any)).rejects.toMatchObject({
      code: ERROR_CODE.UPSTREAM_TIMEOUT,
    });
  });
});

describe('api-client: trace_id / version headers', () => {
  it('X-Request-Id -> envelope.trace_id, X-API-Version -> envelope.version', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(
        200,
        { success: true, data: { ok: true } },
        { 'X-Request-Id': 'req-abc-123', 'X-API-Version': '1' },
      ),
    );
    const env = await api.envelope<{ ok: boolean }>('/api/foo');
    expect(env.trace_id).toBe('req-abc-123');
    expect(env.version).toBe('1');
    expect(env.data).toEqual({ ok: true });
  });

  it('missing X-API-Version -> envelope.version = legacy', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(200, { success: true, data: {} }),
    );
    const env = await api.envelope('/api/foo');
    expect(env.version).toBe('legacy');
  });

  it('request auto-injects X-API-Version: 1', async () => {
    const fetchMock = globalThis.fetch as unknown as jest.Mock;
    fetchMock.mockResolvedValueOnce(fakeResponse(200, { success: true, data: {} }));
    await api.get('/api/foo');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)['X-API-Version']).toBe('1');
  });

  it('request auto-injects X-Request-Id，服务端不回显时 envelope.trace_id 取本地值', async () => {
    const fetchMock = globalThis.fetch as unknown as jest.Mock;
    fetchMock.mockResolvedValueOnce(fakeResponse(200, { success: true, data: {} }));
    const env = await api.envelope('/api/trace');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const sent = (init.headers as Record<string, string>)['X-Request-Id'];
    expect(sent).toBeTruthy();
    expect(env.trace_id).toBe(sent);
  });

  it('调用方 traceId 优先，并作为 X-Request-Id 发出', async () => {
    const fetchMock = globalThis.fetch as unknown as jest.Mock;
    fetchMock.mockResolvedValueOnce(fakeResponse(200, { success: true, data: {} }));
    const env = await api.envelope('/api/trace', { traceId: 'trace-fixed-1' });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)['X-Request-Id']).toBe('trace-fixed-1');
    expect(env.trace_id).toBe('trace-fixed-1');
  });
});

describe('api-client: 调用方 AbortSignal（组件卸载）', () => {
  it('外部 signal abort -> ApiException「请求已取消」而非超时', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockRejectedValueOnce(
      new DOMException('aborted', 'AbortError'),
    );
    const controller = new AbortController();
    controller.abort();
    await expect(
      api.get('/api/cancel', undefined, { signal: controller.signal }),
    ).rejects.toMatchObject({ code: ERROR_CODE.TIMEOUT, message: '请求已取消' });
  });

  it('外部 signal 未 abort -> 正常返回；fetch 收到内部 signal', async () => {
    const fetchMock = globalThis.fetch as unknown as jest.Mock;
    fetchMock.mockResolvedValueOnce(fakeResponse(200, { success: true, data: { ok: 1 } }));
    const controller = new AbortController();
    const res = await api.get<{ ok: number }>('/api/ok', undefined, { signal: controller.signal });
    expect(res).toEqual({ ok: 1 });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(controller.signal.aborted).toBe(false);
  });
});

describe('api-client: 204 No Content', () => {
  it('returns undefined', async () => {
    (globalThis.fetch as unknown as jest.Mock).mockResolvedValueOnce(
      fakeResponse(204, null as unknown as object),
    );
    const res = await api.delete<void>('/api/foo');
    expect(res).toBeUndefined();
  });
});
