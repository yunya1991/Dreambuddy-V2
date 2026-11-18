import { NextRequest, NextResponse } from "next/server";
import { latestVerdictL0, listVerdictsL0 } from "@/lib/verdict/verdict-events";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/verdicts/[taskId]：返回最新裁决与历史（append-only） */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> },
) {
  const { taskId } = await params;
  const [latest, all] = await Promise.all([
    latestVerdictL0(taskId),
    listVerdictsL0(taskId),
  ]);
  return NextResponse.json({
    success: true,
    task_id: taskId,
    latest,
    count: all.length,
    history: all,
  });
}
