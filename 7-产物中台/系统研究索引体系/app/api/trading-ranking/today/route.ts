// ============================================================================
// 交易榜单: 每日 Top10 API
// ============================================================================
// GET /api/trading-ranking/today
// 返回今日 Top10 交易机会 + 决策卡 7 模块
// ============================================================================

import { NextResponse } from "next/server";
import { getTodayRanking } from "@/lib/trading-ranking-service";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const ranking = await getTodayRanking();

    return NextResponse.json({
      success: true,
      date: new Date().toISOString().slice(0, 10),
      total: ranking.length,
      items: ranking,
    });
  } catch (error) {
    console.error("[trading-ranking/today]", error);
    return NextResponse.json(
      { success: false, error: "获取今日榜单失败" },
      { status: 500 },
    );
  }
}
