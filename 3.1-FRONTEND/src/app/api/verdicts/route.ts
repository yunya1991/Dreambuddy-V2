import { NextRequest, NextResponse } from "next/server";
import {
  assessVerdict,
  type VerdictInput,
} from "@/lib/verdict/uncertainty-verdict";
import { recordVerdict } from "@/lib/verdict/verdict-events";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/verdicts
 * 生成并落盘一条 UncertaintyVerdict。
 * 注意：生产模型/Worker 不应直接调用；调用方应为 A 层裁决服务身份。
 */
export async function POST(request: NextRequest) {
  let body: VerdictInput;
  try {
    body = (await request.json()) as VerdictInput;
  } catch {
    return NextResponse.json(
      { success: false, error: "invalid_json" },
      { status: 400 },
    );
  }

  if (!body?.task_id || !body?.claim) {
    return NextResponse.json(
      { success: false, error: "task_id_and_claim_required" },
      { status: 400 },
    );
  }

  const { verdict, issues } = assessVerdict(body);
  const errors = issues.filter((issue) => issue.level === "error");
  if (errors.length > 0) {
    return NextResponse.json(
      { success: false, error: "invalid_verdict", issues },
      { status: 400 },
    );
  }

  await recordVerdict(verdict);
  return NextResponse.json({ success: true, verdict, issues });
}
