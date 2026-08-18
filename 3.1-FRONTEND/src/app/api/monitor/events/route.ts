/**
 * Monitor Events API — 历史事件查询
 * GET /api/monitor/events?uid=xxx&layer=gateway&trace_id=xxx&limit=50
 */
import { NextRequest, NextResponse } from 'next/server';
import { getRecentEvents } from '@/lib/monitor-bus';
import type { MonitorLayer } from '@/lib/monitor-bus';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);

  const uid = searchParams.get('uid') || undefined;
  const layer = searchParams.get('layer') as MonitorLayer | null;
  const traceId = searchParams.get('trace_id') || undefined;
  const limit = Math.min(parseInt(searchParams.get('limit') || '50', 10), 200);

  const events = getRecentEvents({
    uid: uid || undefined,
    layer: layer || undefined,
    trace_id: traceId || undefined,
    limit,
  });

  return NextResponse.json({
    success: true,
    data: events,
    total: events.length,
  });
}
