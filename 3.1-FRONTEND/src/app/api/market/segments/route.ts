import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

/**
 * GET /api/market/segments — 用户分层统计
 * 代理 Hub /market/segments 接口
 */

const MOCK_DATA = {
  total: 1284,
  byRole: { FREE: 986, PRO: 247, ADMIN: 51 },
};

export async function GET() {
  try {
    const hubBaseUrl = process.env.HUB_BASE_URL || 'http://127.0.0.1:3467';
    const res = await fetch(`${hubBaseUrl}/market/segments`, {
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
