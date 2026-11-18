import { NextRequest, NextResponse } from "next/server";
import {
  createVerdictJob,
  executeVerdictJob,
  listVerdictJobs,
  type VerdictJobRequest,
} from "@/lib/verdict/verdict-jobs";
import { executeVerdictJobRequest } from "@/lib/verdict/verdict-job-runner";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/verdicts/jobs
 * 投递 U2/U3 异步裁决 job，立即返回 202；完成后写 L0 `verdict.updated`。
 */
export async function POST(request: NextRequest) {
  let body: VerdictJobRequest;
  try {
    body = (await request.json()) as VerdictJobRequest;
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
  if (body.level !== "U2" && body.level !== "U3") {
    return NextResponse.json(
      { success: false, error: "level_must_be_u2_or_u3" },
      { status: 400 },
    );
  }

  const job = await createVerdictJob(body);
  // 异步执行：不阻塞 HTTP，job 状态可轮询
  void executeVerdictJob(job.job_id, executeVerdictJobRequest).catch(
    () => undefined,
  );

  return NextResponse.json({ success: true, job }, { status: 202 });
}

/** GET /api/verdicts/jobs?task_id=...：按任务列出 job（默认全部） */
export async function GET(request: NextRequest) {
  const taskId = request.nextUrl.searchParams.get("task_id") ?? undefined;
  const jobs = await listVerdictJobs(taskId);
  return NextResponse.json({ success: true, count: jobs.length, jobs });
}
