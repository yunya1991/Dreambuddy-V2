// ============================================================================
// 交易榜单: 监控指标 API
// ============================================================================
// GET /api/trading-ranking/monitor?date=YYYY-MM-DD
// 返回榜单监控指标（转化率/弃单率/到达率/满意度）
// ============================================================================

import { NextRequest, NextResponse } from "next/server";
import { getMonitorMetrics } from "@/lib/trading-ranking-service";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const date = searchParams.get("date") || undefined;

    const metrics = await getMonitorMetrics(date);

    return NextResponse.json({
      success: true,
      ...metrics,
    });
  } catch (error) {
    console.error("[trading-ranking/monitor]", error);
    return NextResponse.json(
      { success: false, error: "获取监控指标失败" },
      { status: 500 },
    );
  }
}
