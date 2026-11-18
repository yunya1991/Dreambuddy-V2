import { NextRequest, NextResponse } from "next/server";
import type { TaskBoardEvent } from "@/types/task-board";
import {
  appendTaskEvents,
  pendingGates,
  readTaskBoard,
} from "@/lib/task-board/server-store";
import { getGateMode } from "@/lib/task-board/gate-policy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/task/[id] — 回放快照 + 未确认门禁 + 当前运行模式 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const snapshot = await readTaskBoard(id);
  return NextResponse.json({
    snapshot,
    pending_gates: pendingGates(snapshot),
    mode: getGateMode(),
  });
}

/** POST /api/task/[id] — 上报业务事件（幂等：服务端按内容指纹去重） */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await request.json().catch(() => null);
  const events = Array.isArray(body?.events)
    ? (body.events as TaskBoardEvent[])
    : null;

  if (!events) {
    return NextResponse.json(
      { success: false, error: "events_required" },
      { status: 400 },
    );
  }

  const snapshot = await appendTaskEvents(id, events);
  return NextResponse.json({ success: true, snapshot });
}
