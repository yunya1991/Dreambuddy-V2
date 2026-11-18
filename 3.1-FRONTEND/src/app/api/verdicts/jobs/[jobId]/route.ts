import { NextRequest, NextResponse } from "next/server";
import { getVerdictJob } from "@/lib/verdict/verdict-jobs";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/verdicts/jobs/[jobId]：查询异步裁决 job 状态与结果 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  const job = await getVerdictJob(jobId);
  if (!job) {
    return NextResponse.json(
      { success: false, error: "job_not_found" },
      { status: 404 },
    );
  }
  return NextResponse.json({ success: true, job });
}
