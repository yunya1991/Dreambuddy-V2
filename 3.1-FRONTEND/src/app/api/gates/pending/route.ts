import { NextResponse } from "next/server";
import { listPendingGateTasks } from "@/lib/task-board/server-store";
import { getGateMode } from "@/lib/task-board/gate-policy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/gates/pending — 待办中心：仍有未确认门禁的任务 */
export async function GET() {
  const tasks = await listPendingGateTasks();
  return NextResponse.json({
    success: true,
    mode: getGateMode(),
    count: tasks.length,
    tasks,
  });
}
