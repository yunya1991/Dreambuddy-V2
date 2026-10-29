import { NextResponse } from "next/server";
import { CYCLE_DISCLAIMER, readCycleArtifact } from "@/lib/cycle-data";

/**
 * GET /api/cycle/state
 * 周期状态只读端点：真实周期（美林时钟锚）+ 技术锚（MA200）+ 资产轮动
 * 红线：只读；呈现标注研究建议
 */
export async function GET() {
  try {
    const cycleState = readCycleArtifact("cycle_state.json");
    const assetRotation = readCycleArtifact("asset_rotation.json");

    if (!cycleState.ok) {
      return NextResponse.json(
        {
          success: false,
          error: cycleState.error,
          disclaimer: CYCLE_DISCLAIMER,
        },
        { status: 404 }
      );
    }

    return NextResponse.json({
      success: true,
      disclaimer: CYCLE_DISCLAIMER,
      research_only: true,
      cycle_state: cycleState.data,
      asset_rotation: assetRotation.ok
        ? assetRotation.data
        : { error: assetRotation.error },
      meta: {
        cycle_state_modified_at: cycleState.modified_at,
        asset_rotation_modified_at: assetRotation.ok ? assetRotation.modified_at : null,
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
