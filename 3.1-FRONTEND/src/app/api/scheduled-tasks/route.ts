import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";
import {
  readScheduledTasks,
  writeScheduledTasks,
  type ScheduledTask,
} from "@/lib/scheduled-tasks";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/scheduled-tasks — 定时任务列表 */
export async function GET() {
  return NextResponse.json({
    success: true,
    tasks: await readScheduledTasks(),
  });
}

/** POST /api/scheduled-tasks — 新建定时任务 */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const title = String(body?.title ?? "").trim();
  const prompt = String(body?.prompt ?? "").trim();
  const interval = Number(body?.interval_minutes ?? 60);

  if (!title || !prompt) {
    return NextResponse.json(
      { success: false, error: "title_and_prompt_required" },
      { status: 400 },
    );
  }

  const tasks = await readScheduledTasks();
  const task: ScheduledTask = {
    id: randomUUID(),
    title: title.slice(0, 80),
    prompt: prompt.slice(0, 2000),
    interval_minutes: Math.max(5, Math.min(10080, Math.round(interval))),
    enabled: true,
    created_at: Date.now(),
  };
  tasks.push(task);
  await writeScheduledTasks(tasks);
  return NextResponse.json({ success: true, task });
}

/** PATCH /api/scheduled-tasks — 启停 / 记录上次执行时间 */
export async function PATCH(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const id = String(body?.id ?? "").trim();
  if (!id) {
    return NextResponse.json(
      { success: false, error: "id_required" },
      { status: 400 },
    );
  }
  const tasks = await readScheduledTasks();
  const index = tasks.findIndex((item) => item.id === id);
  if (index < 0) {
    return NextResponse.json(
      { success: false, error: "not_found" },
      { status: 404 },
    );
  }
  if (typeof body?.enabled === "boolean") tasks[index].enabled = body.enabled;
  if (body?.mark_run === true) tasks[index].last_run_at = Date.now();
  await writeScheduledTasks(tasks);
  return NextResponse.json({ success: true, task: tasks[index] });
}

/** DELETE /api/scheduled-tasks?id=... */
export async function DELETE(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("id")?.trim();
  if (!id) {
    return NextResponse.json(
      { success: false, error: "id_required" },
      { status: 400 },
    );
  }
  const tasks = await readScheduledTasks();
  await writeScheduledTasks(tasks.filter((item) => item.id !== id));
  return NextResponse.json({ success: true });
}
