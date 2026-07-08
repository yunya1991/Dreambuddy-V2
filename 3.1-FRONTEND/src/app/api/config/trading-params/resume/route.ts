/**
 * POST /api/config/trading-params/resume
 * 恢复交易功能
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveTradingParamsResumeRouteUid } from '@/lib/development-route-uids';

export async function POST(request: NextRequest) {
  const uid = await resolveTradingParamsResumeRouteUid(request);

  try {
    // 更新TradingParams状态
    await prisma.tradingParams.upsert({
      where: { uid },
      update: { status: 'ACTIVE' },
      create: { uid, status: 'ACTIVE', lastResetDate: new Date().toISOString().split('T')[0] },
    });

    // 同时开启交易开关
    await prisma.userProfile.update({
      where: { uid },
      data: { isTradingEnabled: true },
    }).catch(() => {});

    return NextResponse.json({
      success: true,
      data: { status: 'ACTIVE' },
    });
  } catch (error) {
    console.error('恢复交易失败:', error);
    return NextResponse.json(
      { success: false, error: '恢复交易失败' },
      { status: 500 }
    );
  }
}
