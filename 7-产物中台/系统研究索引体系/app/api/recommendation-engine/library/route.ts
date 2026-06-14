// ============================================================================
// 推荐策略引擎: 策略库 API
// ============================================================================
// GET /api/recommendation-engine/library
// 查询策略库（所有优于基线的历史策略）
// ============================================================================

import { NextRequest, NextResponse } from "next/server";
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const includeArchived = searchParams.get("includeArchived") === "true";

  try {
    const where = {
      isInLibrary: true,
      ...(includeArchived ? {} : { libraryActive: true }),
    };

    const strategies = await prisma.strategy.findMany({
      where,
      include: {
        backtestRecords: {
          orderBy: { backtestDate: "desc" },
          take: 1,
        },
      },
      orderBy: { libraryScore: "desc" },
    });

    const items = strategies.map((s) => {
      const latestRecord = s.backtestRecords[0];
      return {
        id: s.id,
        name: s.name,
        direction: s.direction,
        symbol: s.symbol,
        regime: s.regime,

        // 性能
        backtestSharpe: s.backtestSharpe,
        backtestMaxDrawdown: s.backtestMaxDrawdown,
        backtestTotalReturn: s.backtestTotalReturn,
        baselineVersion: s.baselineVersion,
        isBetterThanBaseline: s.isBetterThanBaseline,

        // 库状态
        libraryScore: s.libraryScore,
        libraryActive: s.libraryActive,
        libraryArchivedAt: s.libraryArchivedAt?.toISOString() || null,

        // 历史
        generation: s.generation,
        sourceEngine: s.sourceEngine,
        createdAt: s.createdAt.toISOString(),
        lastDailyBacktestDate:
          s.lastDailyBacktestDate?.toISOString() || null,
        consecutiveBelowBaseline: s.consecutiveBelowBaseline,

        // 最新回测
        latestRecord: latestRecord
          ? {
              backtestDate: latestRecord.backtestDate.toISOString(),
              isBetterThanBaseline: latestRecord.isBetterThanBaseline,
              sharpeRatio: latestRecord.sharpeRatio,
            }
          : null,
      };
    });

    return NextResponse.json({
      success: true,
      items,
      total: items.length,
      activeCount: strategies.filter((s) => s.libraryActive).length,
      archivedCount: strategies.filter((s) => !s.libraryActive).length,
    });
  } catch (error) {
    console.error("[recommendation-engine/library]", error);
    return NextResponse.json(
      { success: false, error: "获取策略库失败" },
      { status: 500 }
    );
  }
}
