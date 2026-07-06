/**
 * 用户签到 API
 * POST /api/user/checkin
 * 每天签到1次，获得10积分
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveUserCheckinRouteUid } from '@/lib/development-route-uids';

// POST /api/user/checkin
export async function POST(request: NextRequest) {
  const uid = await resolveUserCheckinRouteUid(request);

  try {
    const today = new Date().toISOString().split('T')[0]; // "2026-05-14"

    // 检查今日是否已签到
    const todaySignin = await prisma.creditsTransaction.findFirst({
      where: {
        uid,
        category: 'SIGNIN',
        createdAt: {
          gte: new Date(`${today}T00:00:00Z`),
          lt: new Date(`${today}T23:59:59Z`),
        },
      },
    });

    if (todaySignin) {
      return NextResponse.json({
        success: false,
        error: '今日已签到，明日再来吧！',
        alreadySignedIn: true,
      }, { status: 400 });
    }

    // 获取或创建积分账户
    let account = await prisma.creditsAccount.findUnique({ where: { uid } });
    if (!account) {
      account = await prisma.creditsAccount.create({
        data: { uid, balance: 0, totalEarned: 0, totalSpent: 0 },
      });
    }

    const signinBonus = 10;
    const newBalance = account.balance + signinBonus;

    // 更新积分账户 + 记录流水
    await prisma.$transaction([
      prisma.creditsAccount.update({
        where: { uid },
        data: {
          balance: newBalance,
          totalEarned: { increment: signinBonus },
        },
      }),
      prisma.creditsTransaction.create({
        data: {
          uid,
          type: 'EARN',
          category: 'SIGNIN',
          amount: signinBonus,
          balanceAfter: newBalance,
          description: `每日签到获得 ${signinBonus} 积分`,
        },
      }),
    ]);

    return NextResponse.json({
      success: true,
      data: {
        bonus: signinBonus,
        newBalance,
        signedInAt: new Date().toISOString(),
      },
    });
  } catch (error) {
    console.error('签到失败:', error);
    return NextResponse.json(
      { success: false, error: '签到失败，请稍后重试' },
      { status: 500 }
    );
  }
}

// GET /api/user/checkin - 获取签到状态
export async function GET(request: NextRequest) {
  const uid = await resolveUserCheckinRouteUid(request);

  try {
    const today = new Date().toISOString().split('T')[0];

    const todaySignin = await prisma.creditsTransaction.findFirst({
      where: {
        uid,
        category: 'SIGNIN',
        createdAt: {
          gte: new Date(`${today}T00:00:00Z`),
          lt: new Date(`${today}T23:59:59Z`),
        },
      },
    });

    const account = await prisma.creditsAccount.findUnique({ where: { uid } });

    return NextResponse.json({
      success: true,
      data: {
        signedInToday: !!todaySignin,
        signedInAt: todaySignin?.createdAt?.toISOString() || null,
        balance: account?.balance ?? 0,
      },
    });
  } catch (error) {
    console.error('获取签到状态失败:', error);
    return NextResponse.json(
      { success: false, error: '获取签到状态失败' },
      { status: 500 }
    );
  }
}
