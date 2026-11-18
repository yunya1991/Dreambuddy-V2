import { NextResponse } from "next/server";
import { listTaskBoards } from "@/lib/task-board/server-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/tasks — 工作台顶部任务切换器：最近任务列表 */
export async function GET() {
  const tasks = await listTaskBoards(30);
  return NextResponse.json({ success: true, tasks });
}
