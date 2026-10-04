// ============================================================================
// 交易榜单: 历史榜单 API
// ============================================================================
// GET /api/trading-ranking/history?date=YYYY-MM-DD
// 返回指定日期的历史 Top10 榜单
// ============================================================================

import { NextRequest, NextResponse } from "next/server";
import { getHistoryRanking } from "@/lib/trading-ranking-service";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date");

    if (!date) {
      return NextResponse.json(
        { success: false, error: "缺少 date 参数，格式 YYYY-MM-DD" },
        { status: 400 },
      );
    }

    // 验证日期格式
    const parsed = new Date(date);
    if (isNaN(parsed.getTime())) {
      return NextResponse.json(
        { success: false, error: "日期格式无效，应为 YYYY-MM-DD" },
        { status: 400 },
      );
    }

    const ranking = await getHistoryRanking(date);

    return NextResponse.json({
      success: true,
      date,
      total: ranking.length,
      items: ranking,
    });
  } catch (error) {
    console.error("[trading-ranking/history]", error);
    return NextResponse.json(
      { success: false, error: "获取历史榜单失败" },
      { status: 500 },
    );
  }
}
