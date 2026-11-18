import { NextRequest, NextResponse } from "next/server";
import { appendTaskEvents, readTaskBoard } from "@/lib/task-board/server-store";
import { resolveGateRoles } from "@/lib/task-board/roles";
import type { TaskBoardEvent } from "@/types/task-board";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/task/[id]/terminate — 管理员终止任务。
 *
 * 制度约束：
 * - 只有 admin（bootstrap 本地单用户除外）可终止；
 * - 必须填写原因，写入 append-only 事件；
 * - 终止后门禁不再接受推进，待办中心不再展示。
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  if ((request.headers.get("x-agent-id") || "").trim()) {
    return NextResponse.json(
      { success: false, error: "terminate_admin_only" },
      { status: 403 },
    );
  }

  const email =
    request.headers.get("x-user-email") ||
    request.headers.get("x-user-id") ||
    "workspace-user";
  const resolved = resolveGateRoles(email);
  if (!resolved.bootstrap && !resolved.roles.includes("admin")) {
    return NextResponse.json(
      { success: false, error: "admin_required", roles: resolved.roles },
      { status: 403 },
    );
  }

  const body = await request.json().catch(() => null);
  const reason =
    typeof body?.reason === "string" ? body.reason.trim() : "";
  if (!reason) {
    return NextResponse.json(
      { success: false, error: "terminate_reason_required" },
      { status: 400 },
    );
  }

  const snapshot = await readTaskBoard(id);
  if (snapshot.terminated) {
    return NextResponse.json({
      success: true,
      snapshot,
      idempotent: true,
    });
  }

  const now = Date.now();
  const event: TaskBoardEvent = {
    task_id: id,
    trace_id: snapshot.trace_id || id,
    seq: 0,
    ts: now,
    type: "task.terminated",
    payload: { reason, by: resolved.email || email, at: now },
  };

  const next = await appendTaskEvents(id, [event]);
  return NextResponse.json({ success: true, snapshot: next });
}
