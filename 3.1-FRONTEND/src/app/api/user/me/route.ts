import { NextRequest, NextResponse } from "next/server";
import { auth } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

/**
 * GET /api/user/me
 * 获取当前登录用户的详细信息（包含Profile、TradingParams、CreditsAccount）
 */
export async function GET(req: NextRequest) {
  try {
    // 验证登录状态
    const session = await auth();
    if (!session?.user?.id) {
      return NextResponse.json(
        { message: "未登录" },
        { status: 401 }
      );
    }

    const uid = session.user.id;

    // 获取用户详细信息（关联查询）
    const user = await prisma.user.findUnique({
      where: { uid },
      select: {
        uid: true,
        email: true,
        emailVerified: true,
        displayName: true,
        avatarUrl: true,
        role: true,
        lastLoginAt: true,
        createdAt: true,
        profile: true,
        tradingParams: true,
        creditsAccount: true,
        _count: {
          select: {
            strategies: true,
            apiConfigs: true,
            channels: true,
          },
        },
      },
    });

    if (!user) {
      return NextResponse.json(
        { message: "用户不存在" },
        { status: 404 }
      );
    }

    return NextResponse.json({
      user,
    });
  } catch (err: any) {
    console.error("[api/user/me]", err);
    return NextResponse.json(
      { message: "服务器错误" },
      { status: 500 }
    );
  }
}
