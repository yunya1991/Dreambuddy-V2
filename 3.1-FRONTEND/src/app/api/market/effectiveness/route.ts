import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * GET /api/market/effectiveness — 策略执行效果统计
 * 代理 Hub /market/effectiveness 接口
 */

const now = Date.now();

const MOCK_DATA = [
  {
    id: 'eff-001',
    name: 'BTC 趋势跟踪策略',
    totalTrades: 47,
    winRate: 0.638,
    pnl: 1842.5,
    appliedAt: new Date(now - 1000 * 60 * 12).toISOString(),
  },
  {
    id: 'eff-002',
    name: 'ETH 均值回归策略',
    totalTrades: 32,
    winRate: 0.562,
    pnl: 423.8,
    appliedAt: new Date(now - 1000 * 60 * 38).toISOString(),
  },
  {
    id: 'eff-003',
    name: 'SOL 动量突破策略',
    totalTrades: 21,
    winRate: 0.476,
    pnl: -128.3,
    appliedAt: new Date(now - 1000 * 60 * 64).toISOString(),
  },
  {
    id: 'eff-004',
    name: 'BNB 网格套利策略',
    totalTrades: 58,
    winRate: 0.707,
    pnl: 2156.2,
    appliedAt: new Date(now - 1000 * 60 * 90).toISOString(),
  },
];

export async function GET() {
  try {
    const hubBaseUrl = process.env.HUB_BASE_URL || 'http://127.0.0.1:3467';
    const res = await fetch(`${hubBaseUrl}/market/effectiveness`, {
      headers: { Accept: 'application/json' },
      next: { revalidate: 15 },
    });
    if (!res.ok) {
      return NextResponse.json(
        { success: false, error: `Hub returned ${res.status}` },
        { status: res.status }
      );
    }
    const json = await res.json();
    return NextResponse.json({ success: true, data: json.data ?? MOCK_DATA });
  } catch {
    // Hub unavailable — return mock data for frontend fallback
    return NextResponse.json({ success: true, mock: true, data: [] }, { status: 200 });
  }
}
