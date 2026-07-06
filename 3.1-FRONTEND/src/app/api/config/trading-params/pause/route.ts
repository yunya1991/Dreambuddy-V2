/**
 * POST /api/config/trading-params/pause
 * 暂停交易功能
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveTradingParamsPauseRouteUid } from '@/lib/development-route-uids';

export async function POST(request: NextRequest) {
  const uid = await resolveTradingParamsPauseRouteUid(request);

  try {
    const body = await request.json().catch(() => ({}));
    const reason = body.reason || '用户主动暂停';

    // 更新TradingParams状态
    await prisma.tradingParams.upsert({
      where: { uid },
      update: { status: 'PAUSED' },
      create: { uid, status: 'PAUSED', lastResetDate: new Date().toISOString().split('T')[0] },
    });

    // 同时关闭交易开关
    await prisma.userProfile.update({
      where: { uid },
      data: { isTradingEnabled: false },
    }).catch(() => {}); // profile可能不存在

    return NextResponse.json({
      success: true,
      data: { status: 'PAUSED', reason },
    });
  } catch (error) {
    console.error('暂停交易失败:', error);
    return NextResponse.json(
      { success: false, error: '暂停交易失败' },
      { status: 500 }
    );
  }
}
