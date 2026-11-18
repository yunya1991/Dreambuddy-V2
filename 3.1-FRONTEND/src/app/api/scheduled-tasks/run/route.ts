import { NextRequest, NextResponse } from "next/server";
import {
  isDue,
  readScheduledTasks,
  writeScheduledTasks,
} from "@/lib/scheduled-tasks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/scheduled-tasks/run
 * body: { id } 立即执行一条；body: {} 执行所有到期任务。
 *
 * 执行复用现有任务中台（/api/task），不在这里另建执行器。
 * last_run_at 先落盘再执行，避免并发重复触发。
 */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const id = typeof body?.id === "string" ? body.id : "";
  const tasks = await readScheduledTasks();
  const now = Date.now();

  const targets = tasks.filter((task) =>
    id ? task.id === id : isDue(task, now),
  );
  if (targets.length === 0) {
    return NextResponse.json({ success: true, ran: 0 });
  }

  for (const task of targets) task.last_run_at = now;
  await writeScheduledTasks(tasks);

  const results = await Promise.all(
    targets.map(async (task) => {
      try {
        const response = await fetch(new URL("/api/task", request.nextUrl.origin), {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            message: task.prompt,
            thinking_mode: "quick",
            session_id: `scheduled:${task.id}`,
          }),
          signal: AbortSignal.timeout(60_000),
        });
        const data = (await response.json().catch(() => null)) as
          | { success?: boolean; error?: string }
          | null;
        return {
          id: task.id,
          title: task.title,
          ok: response.ok && data?.success !== false,
          error: data?.error,
        };
      } catch (error) {
        return {
          id: task.id,
          title: task.title,
          ok: false,
          error: error instanceof Error ? error.message : "run_failed",
        };
      }
    }),
  );

  return NextResponse.json({ success: true, ran: results.length, results });
}
