import { NextRequest, NextResponse } from "next/server";
import { CYCLE_DISCLAIMER, readCycleArtifact, readRecentTrades } from "@/lib/cycle-data";

/**
 * GET /api/cycle/execution?limit=50
 * X0 执行层只读端点：执行状态 + X1 门槛状态 + 最近意图流
 *
 * 红线：
 * - 只读，不触发任何下单动作
 * - X0 意图流仅验证管道，不出具验证指标（X1 边界红线）
 * - 呈现标注研究建议，与交易 UI 隔离
 */
export async function GET(request: NextRequest) {
  try {
    const limitParam = request.nextUrl.searchParams.get("limit");
    let limit = 50;
    if (limitParam) {
      const parsed = parseInt(limitParam, 10);
      if (Number.isNaN(parsed) || parsed < 1 || parsed > 500) {
        return NextResponse.json(
          { success: false, error: "limit must be an integer between 1 and 500" },
          { status: 400 }
        );
      }
      limit = parsed;
    }

    const executionState = readCycleArtifact("execution_state.json");
    const x1Status = readCycleArtifact("x1_metrics_status.json");
    const trades = readRecentTrades(limit);

    return NextResponse.json({
      success: true,
      disclaimer: CYCLE_DISCLAIMER,
      research_only: true,
      execution_state: executionState.ok
        ? executionState.data
        : { error: executionState.error },
      x1_metrics_status: x1Status.ok ? x1Status.data : { error: x1Status.error },
      recent_intents: trades.ok
        ? trades.data
        : { error: trades.error },
      meta: {
        limit,
        trades_modified_at: trades.ok ? trades.modified_at : null,
        trades_size_bytes: trades.ok ? trades.size_bytes : null,
      },
    });
  } catch (err) {
    return NextResponse.json(
      {
        success: false,
        error: err instanceof Error ? err.message : String(err),
      },
      { status: 500 }
    );
  }
}
