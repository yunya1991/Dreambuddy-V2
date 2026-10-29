import { NextResponse } from "next/server";
import {
  CYCLE_DISCLAIMER,
  readCycleArtifact,
  listCycleArtifacts,
  extractEffectiveConfidence,
} from "@/lib/cycle-data";

/**
 * GET /api/cycle
 * 40-周期神经网络系统 汇总只读端点
 *
 * 返回：周期状态 + 策略映射（含 effective_confidence）+ 执行层状态 + 产出物清单
 * 红线：只读；呈现标注研究建议；消费 effective_confidence 而非原始置信度
 */
export async function GET() {
  try {
    const cycleState = readCycleArtifact("cycle_state.json");
    const strategyMapping = readCycleArtifact("strategy_mapping.json");
    const executionState = readCycleArtifact("execution_state.json");
    const x1Status = readCycleArtifact("x1_metrics_status.json");

    const effectiveConfidence = strategyMapping.ok
      ? extractEffectiveConfidence(strategyMapping.data)
      : null;

    return NextResponse.json({
      success: true,
      disclaimer: CYCLE_DISCLAIMER,
      research_only: true,
      effective_confidence: effectiveConfidence,
      cycle_state: cycleState.ok ? cycleState.data : { error: cycleState.error },
      strategy_mapping: strategyMapping.ok
        ? strategyMapping.data
        : { error: strategyMapping.error },
      execution_state: executionState.ok
        ? executionState.data
        : { error: executionState.error },
      x1_metrics_status: x1Status.ok ? x1Status.data : { error: x1Status.error },
      artifacts: listCycleArtifacts(),
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
