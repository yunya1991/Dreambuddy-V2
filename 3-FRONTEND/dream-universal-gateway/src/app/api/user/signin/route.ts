import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

const SIGNIN_CREDITS = 10; // 签到奖励积分
const SIGNIN_COOLDOWN_MS = 24 * 60 * 60 * 1000; // 24小时冷却

/**
 * POST /api/user/signin
 * 用户签到，每天1次，获得10积分
 */
export async function POST(req: NextRequest) {
  try {
    // 验证登录状态
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json(
        { success: false, message: "请先登录" },
        { status: 401 }
      );
    }

    const uid = session.user.id;

    // 获取用户的积分账户
    let account = await prisma.creditsAccount.findUnique({
      where: { uid },
    });

    if (!account) {
      // 创建积分账户（如果不存在）
      account = await prisma.creditsAccount.create({
        data: {
          uid,
          balance: 0,
          totalEarned: 0,
          totalSpent: 0,
        },
      });
    }

    // 检查签到冷却
    const now = new Date();
    const lastSignin = account.lastSigninAt ? new Date(account.lastSigninAt) : new Date(0);
    const timeSinceLastSignin = now.getTime() - lastSignin.getTime();

    if (timeSinceLastSignin < SIGNIN_COOLDOWN_MS) {
      const remainingHours = Math.ceil((SIGNIN_COOLDOWN_MS - timeSinceLastSignin) / (60 * 60 * 1000));
      const remainingMinutes = Math.ceil((SIGNIN_COOLDOWN_MS - timeSinceLastSignin) / (60 * 1000));

      return NextResponse.json({
        success: false,
        message: `今日已签到，请 ${remainingHours > 0 ? `${remainingHours}小时后` : `${remainingMinutes}分钟后`}再试`,
        nextSigninAt: new Date(lastSignin.getTime() + SIGNIN_COOLDOWN_MS).toISOString(),
      });
    }

    // 执行签到：更新积分和最后签到时间
    const updated = await prisma.creditsAccount.update({
      where: { uid },
      data: {
        balance: account.balance + SIGNIN_CREDITS,
        totalEarned: account.totalEarned + SIGNIN_CREDITS,
        lastSigninAt: now,
      },
    });

    // 记录积分变动日志
    await prisma.creditsTransaction.create({
      data: {
        uid,
        amount: SIGNIN_CREDITS,
        type: 'EARN',
        category: 'SIGNIN',
        description: '每日签到奖励',
        balanceAfter: updated.balance,
      },
    });

    return NextResponse.json({
      success: true,
      message: `签到成功！获得 ${SIGNIN_CREDITS} 积分`,
      credits: SIGNIN_CREDITS,
      newBalance: updated.balance,
      nextSigninAt: new Date(now.getTime() + SIGNIN_COOLDOWN_MS).toISOString(),
    });

  } catch (err: any) {
    console.error("[api/user/signin]", err);
    return NextResponse.json(
      { success: false, message: "服务器错误" },
      { status: 500 }
    );
  }
}

/**
 * GET /api/user/signin
 * 获取签到状态
 */
export async function GET(req: NextRequest) {
  try {
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json(
        { success: false, message: "请先登录" },
        { status: 401 }
      );
    }

    const uid = session.user.id;
    const account = await prisma.creditsAccount.findUnique({
      where: { uid },
    });

    if (!account) {
      return NextResponse.json({
        success: true,
        canSignin: true,
        lastSigninAt: null,
        nextSigninAt: null,
        balance: 0,
      });
    }

    const now = new Date();
    const lastSignin = account.lastSigninAt ? new Date(account.lastSigninAt) : new Date(0);
    const timeSinceLastSignin = now.getTime() - lastSignin.getTime();
    const canSignin = timeSinceLastSignin >= SIGNIN_COOLDOWN_MS;

    return NextResponse.json({
      success: true,
      canSignin,
      lastSigninAt: account.lastSigninAt,
      nextSigninAt: canSignin ? null : new Date(lastSignin.getTime() + SIGNIN_COOLDOWN_MS).toISOString(),
      balance: account.balance,
      creditsPerSignin: SIGNIN_CREDITS,
    });

  } catch (err: any) {
    console.error("[api/user/signin GET]", err);
    return NextResponse.json(
      { success: false, message: "服务器错误" },
      { status: 500 }
    );
  }
}
