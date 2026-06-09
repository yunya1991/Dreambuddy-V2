import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import bcrypt from "bcryptjs";
import { generateUID } from "@/lib/uid";

export async function POST(req: NextRequest) {
  try {
    const { email, password } = await req.json();

    if (!email || !password) {
      return NextResponse.json(
        { message: "邮箱和密码不能为空" },
        { status: 400 }
      );
    }

    if (password.length < 8) {
      return NextResponse.json(
        { message: "密码长度至少为 8 位" },
        { status: 400 }
      );
    }

    // 检查用户是否已存在
    const existing = await prisma.user.findUnique({ where: { email } });
    if (existing) {
      return NextResponse.json(
        { message: "该邮箱已注册" },
        { status: 409 }
      );
    }

    // 创建用户 + 关联档案（事务）
    const uid = generateUID();
    const passwordHash = await bcrypt.hash(password, 10);

    await prisma.$transaction(async (tx) => {
      // 创建用户
      const user = await tx.user.create({
        data: {
          uid,
          email,
          passwordHash,
          role: "FREE",
          loginAttempts: 0,
        },
      });

      // 创建用户档案（使用 Schema 实际字段名）
      await tx.userProfile.create({
        data: {
          uid: user.uid,
          availableCapital: 0,
          capitalPercentage: 0.1,
          leverageMax: 3,
          dailyLossLimit: 500,
          dailyLossPercent: 0.05,
          accountLossLimit: 2000,
          accountLossPercent: 0.2,
          allowedSymbols: ["BTC-USDT-SWAP"],
          isTradingEnabled: false,
          riskTolerance: "MODERATE",
        },
      });

      // 创建交易参数
      await tx.tradingParams.create({
        data: {
          uid: user.uid,
          todayLoss: 0,
          todayTradeCount: 0,
          lastResetDate: new Date().toISOString().slice(0, 10),
          totalLoss: 0,
          totalTradeCount: 0,
          status: "ACTIVE",
        },
      });

      // 创建积分账户（新用户赠送 100 积分）
      await tx.creditsAccount.create({
        data: {
          uid: user.uid,
          balance: 100,
          totalEarned: 100,
          totalSpent: 0,
          pendingCredits: 0,
          signupBonus: true,
        },
      });
    });

    return NextResponse.json({ ok: true, uid });
  } catch (err: any) {
    const detail = process.env.NODE_ENV === "development" ? err.message : undefined;
    console.error("[api/register]", err);
    return NextResponse.json(
      { message: "服务器错误，请稍后重试", detail },
      { status: 500 }
    );
  }
}
