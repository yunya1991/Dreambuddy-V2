import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    const tasks = await prisma.strategyTask.findMany({
      select: {
        id: true,
        tradeCount: true,
        executionCount: true,
        lastExecutionAt: true,
        strategy: {
          select: {
            name: true,
          },
        },
      },
      orderBy: { updatedAt: "desc" },
      take: 20,
    });

    return NextResponse.json({
      success: true,
      data: tasks.map((t) => ({
        id: t.id,
        name: t.strategy.name,
        totalTrades: t.tradeCount ?? 0,
        winRate: t.executionCount > 0 ? t.tradeCount / t.executionCount : 0,
        pnl: 0,
        appliedAt: t.lastExecutionAt?.toISOString(),
      })),
    });
  } catch(err) {
    return NextResponse.json({ success:false, error: err instanceof Error ? err.message : "db_error" }, { status:500 });
  }
}
