/**
 * GET /api/token/balance 三态契约测试
 * next/server 在 jsdom 无 Web Response，直接 mock NextResponse.json 为普通对象。
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
jest.mock('@/lib/prisma', () => ({
  prisma: { creditsAccount: { findUnique: jest.fn() } },
}));

import { GET } from '../route';
import { auth } from '@/lib/auth';
import { prisma } from '@/lib/prisma';

const mockAuth = auth as unknown as jest.Mock;
const mockFindUnique = prisma.creditsAccount.findUnique as unknown as jest.Mock;

type MockResponse = { status: number; body: Record<string, unknown> };

async function call(): Promise<MockResponse> {
  return (await GET()) as unknown as MockResponse;
}

describe('GET /api/token/balance', () => {
  beforeEach(() => {
    jest.spyOn(console, 'error').mockImplementation(() => {});
    mockAuth.mockReset();
    mockFindUnique.mockReset();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('未登录返回 401，且不查库', async () => {
    mockAuth.mockResolvedValue(null);

    const res = await call();

    expect(res.status).toBe(401);
    expect(res.body).toEqual({ message: '未登录' });
    expect(mockFindUnique).not.toHaveBeenCalled();
  });

  it('账户存在时按 uid 返回余额三项', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u1' } });
    mockFindUnique.mockResolvedValue({
      balance: 2000,
      totalEarned: 5000,
      totalSpent: 3000,
    });

    const res = await call();

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ balance: 2000, totalEarned: 5000, totalSpent: 3000 });
    expect(mockFindUnique).toHaveBeenCalledWith({
      where: { uid: 'u1' },
      select: { balance: true, totalEarned: true, totalSpent: true },
    });
  });

  it('账户不存在时返回全 0（不报错）', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u2' } });
    mockFindUnique.mockResolvedValue(null);

    const res = await call();

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ balance: 0, totalEarned: 0, totalSpent: 0 });
  });

  it('数据库异常返回 500', async () => {
    mockAuth.mockResolvedValue({ user: { id: 'u3' } });
    mockFindUnique.mockRejectedValue(new Error('db down'));

    const res = await call();

    expect(res.status).toBe(500);
    expect(res.body).toEqual({ message: '服务器错误' });
  });
});
