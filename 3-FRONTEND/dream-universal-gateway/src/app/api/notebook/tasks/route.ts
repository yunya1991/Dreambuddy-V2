// ============================================================
// /api/notebook/tasks — 任务列表管理
// GET  ?phase=todo|active|done|archive&limit=20
// POST 创建任务 (同 /api/notebook POST, 但可选 phase=todo)
// DELETE /:id  删除任务
// 版本: v1.0 | 日期: 2026-06-15
// ============================================================

import { NextRequest, NextResponse } from "next/server";
import {
  loadState,
  saveState,
  createTask,
  setTaskPhase,
  getStats,
} from "@/lib/notebook/step-controller";
import type { TaskPhase } from "@/lib/notebook/types";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const phase = url.searchParams.get("phase") as TaskPhase | null;
  const limit = parseInt(url.searchParams.get("limit") || "20", 10) || 20;

  let state = loadState();
  let tasks = state.tasks;
  if (phase) {
    tasks = tasks.filter((t) => t.phase === phase);
  }
  tasks = tasks.slice(0, limit);

  return NextResponse.json({
    success: true,
    data: { tasks, stats: getStats(), currentTaskId: state.currentTaskId },
    count: tasks.length,
    total: state.tasks.length,
  });
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const {
      title,
      userInput,
      intent = "triple_chain",
      sessionId = `sess_${Date.now()}`,
      entities = {},
      routing = null,
      phase = "active" as TaskPhase,
    } = body;

    if (!title || !userInput) {
      return NextResponse.json(
        { success: false, error: "title and userInput required" },
        { status: 400 }
      );
    }

    const task = createTask(title, userInput, intent, sessionId, entities, routing);
    task.phase = phase;

    const state = loadState();
    state.tasks = [task, ...state.tasks].slice(0, 100);
    if (phase === "active") {
      state.currentTaskId = task.id;
    }
    saveState(state);

    return NextResponse.json({
      success: true,
      data: { task, state },
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}

// PATCH — 修改任务 phase
export async function PATCH(req: NextRequest) {
  try {
    const body = await req.json();
    const { taskId, phase } = body;
    if (!taskId || !phase) {
      return NextResponse.json(
        { success: false, error: "taskId and phase required" },
        { status: 400 }
      );
    }
    const state = setTaskPhase(taskId, phase as TaskPhase);
    return NextResponse.json({ success: true, data: { state } });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
