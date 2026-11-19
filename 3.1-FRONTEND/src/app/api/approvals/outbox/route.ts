import { NextRequest, NextResponse } from "next/server";
import {
  processApprovalOutbox,
  readApprovalOutboxStatus,
} from "@/lib/task-board/approval-outbox";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/approvals/outbox — 消费 approval_outbox → GateFlow 推进。
 * GET  /api/approvals/outbox — 查看游标与已应用数量。
 *
 * 供 cron/launchd 或运维手动触发；配置 APPROVAL_OUTBOX_TOKEN 后需带
 * `x-approval-token` 请求头。未配置时仅限本机可信调用。
 */
function authorized(request: NextRequest): boolean {
  const token = process.env.APPROVAL_OUTBOX_TOKEN?.trim();
  if (!token) return true;
  return (request.headers.get("x-approval-token") || "").trim() === token;
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  if (!authorized(request)) {
    return NextResponse.json(
      { success: false, error: "unauthorized" },
      { status: 401 },
    );
  }
  return NextResponse.json({
    success: true,
    ...(await readApprovalOutboxStatus()),
  });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!authorized(request)) {
    return NextResponse.json(
      { success: false, error: "unauthorized" },
      { status: 401 },
    );
  }
  const result = await processApprovalOutbox();
  return NextResponse.json(
    { success: result.ok, ...result },
    { status: result.ok ? 200 : 500 },
  );
}
