import { NextRequest, NextResponse } from "next/server";
import { appendTaskEvents, readTaskBoard } from "@/lib/task-board/server-store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/task/[id]/spec/confirm
 *
 * 用户在工作台内确认 SPEC（对话内动作，不产生治理待办）。
 * 追加一条 spec.updated（version+1、status=confirmed），
 * 让后续执行以确认版为准；重复确认幂等。
 */
export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const snapshot = await readTaskBoard(id);

  if (!snapshot.spec) {
    return NextResponse.json(
      { success: false, error: "spec_not_found" },
      { status: 400 },
    );
  }
  if (snapshot.spec.status === "confirmed") {
    return NextResponse.json({ success: true, snapshot });
  }

  await appendTaskEvents(id, [
    {
      task_id: id,
      trace_id: snapshot.trace_id || id,
      seq: 0,
      ts: Date.now(),
      type: "spec.updated",
      payload: {
        ...snapshot.spec,
        version: snapshot.spec.version + 1,
        status: "confirmed",
      },
    },
  ]);

  return NextResponse.json({
    success: true,
    snapshot: await readTaskBoard(id),
  });
}
