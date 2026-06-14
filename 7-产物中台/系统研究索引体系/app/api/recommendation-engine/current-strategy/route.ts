// ============================================================================
// 推荐策略引擎: 当前推荐策略 API
// ============================================================================
// GET /api/recommendation-engine/current-strategy
// 获取当前推荐的策略（状态为 APPROVED 或 APPLIED 的最新 RECOMMENDED 策略）
// ============================================================================

import { NextResponse } from "next/server";
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    // 获取当前推荐的策略
    const current = await prisma.strategy.findFirst({
      where: {
        type: "RECOMMENDED",
        status: { in: ["APPROVED", "APPLIED"] },
      },
      orderBy: { createdAt: "desc" },
      include: {
        backtestRecords: {
          orderBy: { backtestDate: "desc" },
          take: 5,
        },
      },
    });

    // 获取当前推荐天数
    const recentRecommendations = await prisma.strategy.findMany({
      where: { type: "RECOMMENDED", status: { in: ["APPROVED", "APPLIED"] } },
      orderBy: { createdAt: "desc" },
      take: 1,
      select: { recommendedDays: true, isBetterThanBaseline: true },
    });

    const recommendedDays = recentRecommendations[0]?.recommendedDays ?? 0;
    const isBetterThanBaseline =
      recentRecommendations[0]?.isBetterThanBaseline ?? false;

    // 获取策略库统计
    const libraryCount = await prisma.strategy.count({
      where: { isInLibrary: true, libraryActive: true },
    });

    return NextResponse.json({
      success: true,
      strategy: current
        ? {
            ...current,
            recommendedDays,
            isBetterThanBaseline,
          }
        : null,
      meta: {
        recommendedDays,
        daysUntilForcedRefresh: Math.max(0, 5 - recommendedDays),
        isBetterThanBaseline,
        libraryCount,
      },
    });
  } catch (error) {
    console.error("[recommendation-engine/current-strategy]", error);
    return NextResponse.json(
      { success: false, error: "获取推荐策略失败" },
      { status: 500 }
    );
  }
}
