/**
 * 交易参数配置 API 路由
 * GET    - 获取当前用户的交易参数 + 门禁状态 + 交易所连接状态
 * PATCH  - 更新交易参数
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveTradingParamsRouteUid } from '@/lib/development-route-uids';

// GET /api/config/trading-params
export async function GET(request: NextRequest) {
  const uid = await resolveTradingParamsRouteUid(request);

  try {
    // 并行查询: UserProfile + TradingParams + Exchange ApiConfig
    const [profile, tradingParams, exchangeConfig] = await Promise.all([
      prisma.userProfile.findUnique({ where: { uid } }),
      prisma.tradingParams.findUnique({ where: { uid } }),
      prisma.apiConfig.findFirst({
        where: { uid, category: 'EXCHANGE' },
        select: {
          provider: true,
          isVerified: true,
          environment: true,
          lastVerifiedAt: true,
        },
      }),
    ]);

    // 如果没有profile，返回默认值
    const params = {
      availableCapital: profile?.availableCapital ?? null,
      capitalPercentage: profile?.capitalPercentage ?? 0.10,
      tradeType: profile?.tradeType ?? 'SPOT',
      tradeMode: profile?.tradeMode ?? 'SPOT_MODE',
      marginMode: profile?.marginMode ?? null,
      positionMode: profile?.positionMode ?? 'NET',
      leverageMax: profile?.leverageMax ?? 3,
      dailyLossLimit: profile?.dailyLossLimit ?? 500,
      dailyLossPercent: profile?.dailyLossPercent ?? 0.05,
      accountLossLimit: profile?.accountLossLimit ?? 2000,
      accountLossPercent: profile?.accountLossPercent ?? 0.20,
      allowedSymbols: profile?.allowedSymbols ?? ['BTC-USDT-SWAP'],
      allowedTradeModes: profile?.allowedTradeModes ?? ['SPOT_MODE'],
      isTradingEnabled: profile?.isTradingEnabled ?? false,
      optionsType: profile?.optionsType ?? null,
      expiryDate: profile?.expiryDate ?? null,
      riskTolerance: profile?.riskTolerance ?? 'MODERATE',
      preferredFrequency: profile?.preferredFrequency ?? 'FOUR_H',
    };

    const liveStatus = {
      todayLoss: tradingParams?.todayLoss ?? 0,
      todayTradeCount: tradingParams?.todayTradeCount ?? 0,
      totalLoss: tradingParams?.totalLoss ?? 0,
      totalTradeCount: tradingParams?.totalTradeCount ?? 0,
      status: tradingParams?.status ?? 'ACTIVE',
      lastResetDate: tradingParams?.lastResetDate ?? new Date().toISOString().split('T')[0],
    };

    const exchangeStatus = exchangeConfig ? {
      provider: exchangeConfig.provider,
      isConfigured: true,
      isVerified: exchangeConfig.isVerified,
      environment: (exchangeConfig.environment as 'demo' | 'live') ?? 'demo',
      lastVerifiedAt: exchangeConfig.lastVerifiedAt?.toISOString(),
    } : null;

    return NextResponse.json({
      success: true,
      data: { params, liveStatus, exchangeStatus },
    });
  } catch (error) {
    console.error('获取交易参数失败:', error);
    return NextResponse.json(
      { success: false, error: '获取交易参数失败' },
      { status: 500 }
    );
  }
}

// PATCH /api/config/trading-params
export async function PATCH(request: NextRequest) {
  const uid = await resolveTradingParamsRouteUid(request);

  try {
    const body = await request.json();
    const warnings: string[] = [];

    // 参数范围校验
    if (body.leverageMax !== undefined) {
      if (body.leverageMax < 1 || body.leverageMax > 5) {
        return NextResponse.json(
          { success: false, error: '杠杆倍数需在1x-5x之间' },
          { status: 400 }
        );
      }
      if (body.leverageMax >= 3) {
        warnings.push(`${body.leverageMax}x杠杆风险较高，请谨慎操作`);
      }
    }

    if (body.dailyLossPercent !== undefined) {
      if (body.dailyLossPercent < 0.01 || body.dailyLossPercent > 1) {
        return NextResponse.json(
          { success: false, error: '日亏损百分比需在1%-100%之间' },
          { status: 400 }
        );
      }
    }

    if (body.accountLossPercent !== undefined) {
      if (body.accountLossPercent < 0.01 || body.accountLossPercent > 1) {
        return NextResponse.json(
          { success: false, error: '账户亏损百分比需在1%-100%之间' },
          { status: 400 }
        );
      }
    }

    if (body.capitalPercentage !== undefined) {
      if (body.capitalPercentage < 0.01 || body.capitalPercentage > 1) {
        return NextResponse.json(
          { success: false, error: '交易百分比需在1%-100%之间' },
          { status: 400 }
        );
      }
    }

    // 构建更新数据
    const updateData: Record<string, unknown> = {};
    const allowedFields = [
      'availableCapital', 'capitalPercentage', 'tradeType', 'tradeMode',
      'marginMode', 'positionMode', 'leverageMax',
      'dailyLossLimit', 'dailyLossPercent', 'accountLossLimit', 'accountLossPercent',
      'allowedSymbols', 'allowedTradeModes', 'isTradingEnabled',
      'optionsType', 'expiryDate', 'riskTolerance', 'preferredFrequency',
    ];

    for (const field of allowedFields) {
      if (body[field] !== undefined) {
        updateData[field] = body[field];
      }
    }

    // 合约模式时自动设置tradeType为SWAP
    if (body.tradeMode && ['SWAP_MODE', 'FUTURES_MODE', 'OPTIONS_MODE', 'MARGIN_MODE'].includes(body.tradeMode)) {
      updateData.tradeType = 'SWAP';
    } else if (body.tradeMode === 'SPOT_MODE') {
      updateData.tradeType = 'SPOT';
    }

    if (Object.keys(updateData).length === 0) {
      return NextResponse.json(
        { success: false, error: '没有需要更新的字段' },
        { status: 400 }
      );
    }

    // Upsert UserProfile
    await prisma.userProfile.upsert({
      where: { uid },
      update: updateData,
      create: {
        uid,
        ...updateData,
      },
    });

    return NextResponse.json({
      success: true,
      data: {
        updatedFields: Object.keys(updateData),
        warnings: warnings.length > 0 ? warnings : undefined,
      },
    });
  } catch (error) {
    console.error('更新交易参数失败:', error);
    return NextResponse.json(
      { success: false, error: '更新交易参数失败' },
      { status: 500 }
    );
  }
}
