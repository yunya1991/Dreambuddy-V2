// ============================================================================
// 推荐策略引擎: 回测历史 API
// ============================================================================
// GET /api/recommendation-engine/backtests
// 查询推荐策略的回测历史记录
// ============================================================================

import { NextRequest, NextResponse } from "next/server";
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const page = parseInt(searchParams.get("page") || "1", 10);
  const pageSize = parseInt(searchParams.get("pageSize") || "20", 10);
  const strategyId = searchParams.get("strategyId");
  const baselineVersion = searchParams.get("baselineVersion");

  try {
    const where: Record<string, unknown> = {};

    if (strategyId) {
      where.strategyId = strategyId;
    }

    if (baselineVersion) {
      where.baselineVersion = baselineVersion;
    }

    const [records, total] = await Promise.all([
      prisma.strategyBacktestRecord.findMany({
        where,
        include: {
          strategy: {
            select: {
              id: true,
              name: true,
              direction: true,
              symbol: true,
              regime: true,
            },
          },
        },
        orderBy: { backtestDate: "desc" },
        skip: (page - 1) * pageSize,
        take: pageSize,
      }),
      prisma.strategyBacktestRecord.count({ where }),
    ]);

    const items = records.map((r) => ({
      id: r.id,
      strategyId: r.strategyId,
      strategyName: r.strategy.name,
      strategyDirection: r.strategy.direction,
      backtestDate: r.backtestDate.toISOString(),
      backtestPeriod: r.backtestPeriod,
      baselineVersion: r.baselineVersion,
      symbol: r.symbol,

      // 策略性能
      sharpeRatio: r.sharpeRatio,
      maxDrawdown: r.maxDrawdown,
      winRate: r.winRate,
      profitFactor: r.profitFactor,
      totalReturn: r.totalReturn,
      tradeCount: r.tradeCount,

      // 基线性能
      baselineSharpe: r.baselineSharpe,
      baselineMaxDD: r.baselineMaxDrawdown,
      baselineTotalReturn: r.baselineTotalReturn,

      // 对比
      isBetterThanBaseline: r.isBetterThanBaseline,
      runId: r.runId,

      // 差值
      sharpeDiff: r.sharpeRatio - r.baselineSharpe,
      ddDiff: r.baselineMaxDrawdown - r.maxDrawdown,
      returnDiff: r.totalReturn - r.baselineTotalReturn,
    }));

    return NextResponse.json({
      success: true,
      items,
      total,
      page,
      pageSize,
      totalPages: Math.ceil(total / pageSize),
    });
  } catch (error) {
    console.error("[recommendation-engine/backtests]", error);
    return NextResponse.json(
      { success: false, error: "获取回测历史失败" },
      { status: 500 }
    );
  }
}
