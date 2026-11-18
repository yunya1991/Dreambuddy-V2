import { NextRequest, NextResponse } from "next/server";
import { readTaskBoard } from "@/lib/task-board/server-store";
import { precheckGate } from "@/lib/task-board/gate-precheck";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/task/[id]/gate/precheck — 机器预审（只读，不改变门禁状态）。
 *
 * 返回各模型票与会签建议；人工确认仍需走 `/gate`。
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await request.json().catch(() => null);
  const gateId =
    typeof body?.gate_id === "string" ? body.gate_id.trim() : "";

  if (!gateId) {
    return NextResponse.json(
      { success: false, error: "gate_id_required" },
      { status: 400 },
    );
  }

  const snapshot = await readTaskBoard(id);
  const gate = snapshot.gates.find((item) => item.gate_id === gateId);
  if (!gate) {
    return NextResponse.json(
      { success: false, error: "gate_not_found" },
      { status: 404 },
    );
  }

  const precheck = await precheckGate(snapshot, gate);
  return NextResponse.json({ success: true, precheck });
}
