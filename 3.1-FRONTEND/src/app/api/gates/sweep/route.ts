import { NextResponse } from "next/server";
import { sweepGateSla } from "@/lib/task-board/server-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/gates/sweep — 超时巡检。
 * 只写提醒/升级事件，绝不自动通过；重复调用幂等。
 */
export async function POST() {
  const results = await sweepGateSla();
  return NextResponse.json({
    success: true,
    count: results.length,
    results,
  });
}
