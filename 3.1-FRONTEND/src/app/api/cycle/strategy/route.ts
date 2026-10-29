import { NextResponse } from "next/server";
import {
  CYCLE_DISCLAIMER,
  readCycleArtifact,
  extractEffectiveConfidence,
} from "@/lib/cycle-data";

/**
 * GET /api/cycle/strategy
 * P4 策略映射只读端点
 *
 * 红线：
 * - 只产建议不产交易信号
 * - 前端消费 effective_confidence 而非原始置信度（顶层显式暴露）
 * - 呈现标注研究建议，与交易 UI 隔离
 */
export async function GET() {
  try {
    const strategyMapping = readCycleArtifact("strategy_mapping.json");

    if (!strategyMapping.ok) {
      return NextResponse.json(
        {
          success: false,
          error: strategyMapping.error,
          disclaimer: CYCLE_DISCLAIMER,
        },
        { status: 404 }
      );
    }

    const effectiveConfidence = extractEffectiveConfidence(strategyMapping.data);

    return NextResponse.json({
      success: true,
      disclaimer: CYCLE_DISCLAIMER,
      research_only: true,
      effective_confidence: effectiveConfidence,
      strategy_mapping: strategyMapping.data,
      meta: {
        modified_at: strategyMapping.modified_at,
        size_bytes: strategyMapping.size_bytes,
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
