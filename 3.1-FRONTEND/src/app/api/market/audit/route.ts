import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * GET /api/market/audit — 内容分发与系统操作审计日志
 * 代理 Hub /market/audit 接口
 */

const now = Date.now();

const MOCK_DATA = [
  {
    id: 'aud-001',
    action: 'strategy.apply',
    resource: 'BTC 趋势跟踪策略',
    actor: 'trader_007',
    result: 'success' as const,
    details: 'TREND_FOLLOWING · LONG',
    timestamp: new Date(now - 1000 * 60 * 4).toISOString(),
  },
  {
    id: 'aud-002',
    action: 'strategy.approve',
    resource: 'ETH 均值回归策略',
    actor: 'admin',
    result: 'success' as const,
    details: 'MEAN_REVERSION · SHORT',
    timestamp: new Date(now - 1000 * 60 * 12).toISOString(),
  },
  {
    id: 'aud-003',
    action: 'channel.test',
    resource: 'feishu-approval-group',
    actor: 'ops_bot',
    result: 'failure' as const,
    details: 'webhook timeout',
    timestamp: new Date(now - 1000 * 60 * 25).toISOString(),
  },
  {
    id: 'aud-004',
    action: 'strategy.pause',
    resource: 'BNB 网格套利策略',
    actor: 'risk_mgr',
    result: 'success' as const,
    details: 'ARBITRAGE · NEUTRAL',
    timestamp: new Date(now - 1000 * 60 * 60).toISOString(),
  },
  {
    id: 'aud-005',
    action: 'strategy.create',
    resource: 'SOL 动量突破策略',
    actor: 'researcher',
    result: 'pending' as const,
    details: 'MOMENTUM · LONG',
    timestamp: new Date(now - 1000 * 60 * 90).toISOString(),
  },
];

export async function GET() {
  try {
    const hubBaseUrl = process.env.HUB_BASE_URL || 'http://127.0.0.1:3467';
    const res = await fetch(`${hubBaseUrl}/market/audit`, {
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
