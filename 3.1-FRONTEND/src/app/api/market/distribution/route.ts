import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * GET /api/market/distribution — 消息推送分发记录
 * 代理 Hub /market/distribution 接口
 */

const now = Date.now();

const MOCK_DATA = [
  {
    id: 'dist-001',
    channelType: 'telegram',
    messageType: '策略信号',
    status: 'sent' as const,
    sentAt: new Date(now - 1000 * 60 * 3).toISOString(),
    recipient: 'trading-signals',
  },
  {
    id: 'dist-002',
    channelType: 'webhook',
    messageType: '风控告警',
    status: 'sent' as const,
    sentAt: new Date(now - 1000 * 60 * 8).toISOString(),
    recipient: 'risk-alert-endpoint',
  },
  {
    id: 'dist-003',
    channelType: 'email',
    messageType: '日报',
    status: 'pending' as const,
    sentAt: new Date(now - 1000 * 60 * 15).toISOString(),
    recipient: 'ops@example.com',
  },
  {
    id: 'dist-004',
    channelType: 'feishu',
    messageType: '策略审批',
    status: 'failed' as const,
    sentAt: new Date(now - 1000 * 60 * 22).toISOString(),
    recipient: 'approval-group',
  },
  {
    id: 'dist-005',
    channelType: 'telegram',
    messageType: '策略信号',
    status: 'sent' as const,
    sentAt: new Date(now - 1000 * 60 * 40).toISOString(),
    recipient: 'trading-signals',
  },
];

export async function GET() {
  try {
    const hubBaseUrl = process.env.HUB_BASE_URL || 'http://127.0.0.1:3467';
    const res = await fetch(`${hubBaseUrl}/market/distribution`, {
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
    // Dev fallback: return mock data so the page renders without Hub.
    return NextResponse.json({ success: true, data: MOCK_DATA });
  }
}
