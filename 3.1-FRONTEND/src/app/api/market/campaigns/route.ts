import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * GET /api/market/campaigns — 策略投放活动管理
 * 代理 Hub /market/campaigns 接口
 */

const now = Date.now();

const MOCK_DATA = [
  {
    id: 'cmp-001',
    name: 'BTC 趋势跟踪 - 主账户',
    type: 'TREND_FOLLOWING',
    status: 'APPLIED' as const,
    direction: 'LONG',
    symbol: 'BTC/USDT',
    confidence: 0.82,
    createdAt: new Date(now - 1000 * 60 * 60 * 2).toISOString(),
  },
  {
    id: 'cmp-002',
    name: 'ETH 均值回归 - 对冲',
    type: 'MEAN_REVERSION',
    status: 'APPROVED' as const,
    direction: 'SHORT',
    symbol: 'ETH/USDT',
    confidence: 0.71,
    createdAt: new Date(now - 1000 * 60 * 60 * 5).toISOString(),
  },
  {
    id: 'cmp-003',
    name: 'SOL 动量突破 - 试验',
    type: 'MOMENTUM',
    status: 'DRAFT' as const,
    direction: 'LONG',
    symbol: 'SOL/USDT',
    confidence: 0.55,
    createdAt: new Date(now - 1000 * 60 * 60 * 8).toISOString(),
  },
  {
    id: 'cmp-004',
    name: 'BNB 网格套利 - 稳定',
    type: 'ARBITRAGE',
    status: 'PAUSED' as const,
    direction: 'NEUTRAL',
    symbol: 'BNB/USDT',
    confidence: 0.68,
    createdAt: new Date(now - 1000 * 60 * 60 * 24).toISOString(),
  },
  {
    id: 'cmp-005',
    name: 'XRP 事件驱动 - 已结束',
    type: 'EVENT_DRIVEN',
    status: 'EXPIRED' as const,
    direction: 'LONG',
    symbol: 'XRP/USDT',
    confidence: 0.6,
    createdAt: new Date(now - 1000 * 60 * 60 * 72).toISOString(),
  },
];

export async function GET() {
  try {
    const hubBaseUrl = process.env.HUB_BASE_URL || 'http://127.0.0.1:3467';
    const res = await fetch(`${hubBaseUrl}/market/campaigns`, {
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
