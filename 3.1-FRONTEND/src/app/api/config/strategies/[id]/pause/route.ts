/**
 * POST /api/config/strategies/[id]/pause
 * 暂停策略
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveStrategyPauseRouteUid } from '@/lib/development-route-uids';
import { pauseStrategyWithTaskOrder } from '@/lib/strategy-lifecycle-service';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const uid = await resolveStrategyPauseRouteUid(request);

  try {
    const strategy = await prisma.strategy.findFirst({ where: { id, uid } });
    if (!strategy) {
      return NextResponse.json({ success: false, error: '策略不存在' }, { status: 404 });
    }

    const result = await pauseStrategyWithTaskOrder({
      prisma,
      strategyId: id,
      nowIso: new Date().toISOString(),
    });

    return NextResponse.json({
      success: true,
      data: result.strategy,
      meta: {
        pausedTaskOrdersCount: result.pausedTaskOrdersCount,
        pausedStrategyTasksCount: result.pausedStrategyTasksCount,
      },
    });
  } catch (error) {
    console.error('暂停策略失败:', error);
    return NextResponse.json({ success: false, error: '暂停策略失败' }, { status: 500 });
  }
}
