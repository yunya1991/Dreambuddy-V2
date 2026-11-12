/**
 * POST /api/dsh/execute — trace_id 全链透传契约
 * next/server 在 jsdom 无 Web Response，mock NextResponse.json 为普通对象。
 */

jest.mock('next/server', () => ({
  NextResponse: {
    json: (body: unknown, init?: { status?: number; headers?: Record<string, string> }) => ({
      status: init?.status ?? 200,
      body,
      headers: init?.headers ?? {},
    }),
  },
}));

import { POST } from '../route';

type MockResponse = {
  status: number;
  body: Record<string, unknown>;
  headers: Record<string, string>;
};

function makeRequest(body: unknown, headers: Record<string, string> = {}) {
  return {
    headers: { get: (k: string) => headers[k.toLowerCase()] ?? null },
    json: async () => body,
  } as unknown as Parameters<typeof POST>[0];
}

let fetchMock: jest.Mock;

beforeAll(() => {
  fetchMock = jest.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

beforeEach(() => {
  fetchMock.mockReset();
  process.env.DSH_API_BASE = 'http://dsh.local';
  jest.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  delete process.env.DSH_API_BASE;
  jest.restoreAllMocks();
});

describe('POST /api/dsh/execute trace_id 透传', () => {
  it('请求头 X-Request-Id -> 上游 body.trace_id + 上游请求头 + 响应头回显', async () => {
    fetchMock.mockResolvedValueOnce({
      status: 200,
      json: async () => ({ ok: true, trace_id: 'trace-from-upstream' }),
    });

    const res = (await POST(
      makeRequest({ capability: 'cognitive.recall', payload: { q: 'x' } }, { 'x-request-id': 'trace-in-1' }),
    )) as unknown as MockResponse;

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)['X-Request-Id']).toBe('trace-in-1');
    expect(JSON.parse(init.body as string)).toMatchObject({
      capability: 'cognitive.recall',
      trace_id: 'trace-in-1',
    });
    // 上游回显优先
    expect(res.status).toBe(200);
    expect(res.headers['X-Request-Id']).toBe('trace-from-upstream');
  });

  it('无请求头时用 body.trace_id；上游未回显则沿用该值', async () => {
    fetchMock.mockResolvedValueOnce({ status: 200, json: async () => ({ ok: true }) });

    const res = (await POST(
      makeRequest({ capability: 'c', trace_id: 'trace-body-1' }),
    )) as unknown as MockResponse;

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)['X-Request-Id']).toBe('trace-body-1');
    expect(res.headers['X-Request-Id']).toBe('trace-body-1');
  });

  it('DSH_API_BASE 未配置 -> 503 且回显入站链路 ID', async () => {
    delete process.env.DSH_API_BASE;

    const res = (await POST(
      makeRequest({ capability: 'c' }, { 'x-request-id': 'trace-in-2' }),
    )) as unknown as MockResponse;

    expect(res.status).toBe(503);
    expect(res.body).toMatchObject({ degraded: true });
    expect(res.headers['X-Request-Id']).toBe('trace-in-2');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('缺少 capability -> 400 且回显入站链路 ID', async () => {
    const res = (await POST(
      makeRequest({}, { 'x-request-id': 'trace-in-3' }),
    )) as unknown as MockResponse;

    expect(res.status).toBe(400);
    expect(res.headers['X-Request-Id']).toBe('trace-in-3');
  });

  it('上游异常 -> 504 且保留链路 ID', async () => {
    fetchMock.mockRejectedValueOnce(new Error('boom'));

    const res = (await POST(
      makeRequest({ capability: 'c' }, { 'x-request-id': 'trace-in-4' }),
    )) as unknown as MockResponse;

    expect(res.status).toBe(504);
    expect(res.body).toMatchObject({ degraded: true });
    expect(res.headers['X-Request-Id']).toBe('trace-in-4');
  });

  it('配置 DSH_API_TOKEN 时带 Bearer 头（云端鉴权对齐 callDshHttp）', async () => {
    process.env.DSH_API_TOKEN = 'secret-token';
    fetchMock.mockResolvedValueOnce({ status: 200, json: async () => ({ ok: true }) });

    await POST(makeRequest({ capability: 'c' }));

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer secret-token');
    delete process.env.DSH_API_TOKEN;
  });
});
