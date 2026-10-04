/**
 * 持仓 API 路由 (P1)
 * GET - 获取当前用户交易账户下的持仓列表
 */
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { resolvePositionsRouteUid } from "@/lib/development-route-uids";

export async function GET(request: NextRequest) {
  const uid = await resolvePositionsRouteUid(request);

  try {
    const tradingAccount = await prisma.tradingAccount.findUnique({
      where: { customerUid: uid },
      include: {
        positions: {
          orderBy: { openedAt: "desc" },
        },
      },
    });

    if (!tradingAccount) {
      return NextResponse.json({ success: true, data: { positions: [], summary: null } });
    }

    const openPositions = (tradingAccount.positions as Array<{ status: string; [k: string]: unknown }>).filter((p) => p.status === "OPEN");

    return NextResponse.json({
      success: true,
      data: {
        summary: {
          marginBalance: tradingAccount.marginBalance,
          usedMargin: tradingAccount.usedMargin,
          availableMargin: tradingAccount.availableMargin,
          totalPositionValue: tradingAccount.totalPositionValue,
          unrealizedPnl: tradingAccount.unrealizedPnl,
        },
        positions: openPositions,
      },
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "查询失败" },
      { status: 500 },
    );
  }
}
