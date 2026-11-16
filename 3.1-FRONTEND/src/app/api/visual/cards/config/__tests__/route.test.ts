/**
 * /api/visual/cards/config 契约测试（SPEC-54 R3b / AC8）
 * - userId 只取 session；伪造 userId 返回 403
 * - 未登录 401；非法 payload 400；超限 413
 */

jest.mock('next/server', () => ({
  NextResponse: {
    json: (body: unknown, init?: { status?: number }) => ({
      status: init?.status ?? 200,
      body,
    }),
  },
}));

jest.mock('@/lib/auth', () => ({ auth: jest.fn() }));
jest.mock('@/lib/visual/cards-config', () => ({
  readCardsConfig: jest.fn(),
  writeCardsConfig: jest.fn(),
}));

import { GET, PUT } from '../route';
import { auth } from '@/lib/auth';
import { readCardsConfig, writeCardsConfig } from '@/lib/visual/cards-config';

const mockAuth = auth as unknown as jest.Mock;
const mockRead = readCardsConfig as unknown as jest.Mock;
const mockWrite = writeCardsConfig as unknown as jest.Mock;

type MockResponse = { status: number; body: Record<string, unknown> };

function getRequest(params: Record<string, string> = {}) {
  return {
    nextUrl: { searchParams: { get: (key: string) => params[key] ?? null } },
  } as never;
}

function putRequest(body: unknown) {
  return { json: async () => body } as never;
}

beforeEach(() => {
  mockAuth.mockReset();
  mockRead.mockReset();
  mockWrite.mockReset();
});

describe('GET /api/visual/cards/config', () => {
  it('未登录返回 401 且不读存储', async () => {
    mockAuth.mockResolvedValue(null);

    const res = (await GET(getRequest())) as unknown as MockResponse;

    expect(res.status).toBe(401);
    expect(res.body.code).toBe('unauthorized');
    expect(mockRead).not.toHaveBeenCalled();
  });

  it('伪造 userId 返回 403 且不读存储', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u1' } });

    const res = (await GET(getRequest({ userId: 'u2' }))) as unknown as MockResponse;

    expect(res.status).toBe(403);
    expect(res.body.code).toBe('forbidden');
    expect(mockRead).not.toHaveBeenCalled();
  });

  it('正常读取用 session.userId 而非请求参数', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u1' } });
    mockRead.mockResolvedValue({ ok: true, code: 'ok', items: [], count: 0 });

    const res = (await GET(getRequest({ tabId: 'all' }))) as unknown as MockResponse;

    expect(res.status).toBe(200);
    expect(mockRead).toHaveBeenCalledWith('u1', 'all');
  });
});

describe('PUT /api/visual/cards/config', () => {
  const panels = [
    { panel_key: 'D-A11|BTC', capability_id: 'D-A11', args: { symbol: 'BTC' } },
  ];

  it('伪造 userId 返回 403 且不写存储', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u1' } });

    const res = (await PUT(
      putRequest({ userId: 'u2', tabId: 'all', panels }),
    )) as unknown as MockResponse;

    expect(res.status).toBe(403);
    expect(res.body.code).toBe('forbidden');
    expect(mockWrite).not.toHaveBeenCalled();
  });

  it('正常写入使用 session.userId', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u1' } });
    mockWrite.mockResolvedValue({ ok: true, code: 'ok', tab_id: 'all', count: 1 });

    const res = (await PUT(
      putRequest({ tabId: 'all', panels }),
    )) as unknown as MockResponse;

    expect(res.status).toBe(200);
    expect(mockWrite).toHaveBeenCalledWith('u1', 'all', [
      {
        panel_key: 'D-A11|BTC',
        capability_id: 'D-A11',
        args: { symbol: 'BTC' },
        data_provenance: 'pool',
      },
    ]);
  });

  it('缺 tabId 或 panels 非法返回 400', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u1' } });

    const noTab = (await PUT(putRequest({ panels }))) as unknown as MockResponse;
    const badPanels = (await PUT(
      putRequest({ tabId: 'all', panels: [{ args: {} }] }),
    )) as unknown as MockResponse;

    expect(noTab.status).toBe(400);
    expect(noTab.body.code).toBe('invalid_params');
    expect(badPanels.status).toBe(400);
    expect(mockWrite).not.toHaveBeenCalled();
  });

  it('存储超限返回 413', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u1' } });
    mockWrite.mockResolvedValue({ ok: false, code: 'payload_too_large' });

    const res = (await PUT(
      putRequest({ tabId: 'all', panels }),
    )) as unknown as MockResponse;

    expect(res.status).toBe(413);
    expect(res.body.code).toBe('payload_too_large');
  });
});
