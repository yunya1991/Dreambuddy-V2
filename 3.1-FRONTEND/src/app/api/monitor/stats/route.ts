/**
 * Monitor Stats API — 聚合统计
 * GET /api/monitor/stats?uid=xxx
 */
import { NextRequest, NextResponse } from 'next/server';
import { getMonitorStats, getPipelineStatus } from '@/lib/monitor-bus';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const uid = searchParams.get('uid') || undefined;

  const stats = getMonitorStats(uid || undefined);
  const pipeline = getPipelineStatus(uid || undefined);

  return NextResponse.json({
    success: true,
    data: {
      stats,
      pipeline,
      timestamp: new Date().toISOString(),
    },
  });
}
