/**
 * 实时干预 API (F7.4)
 * POST /api/intent/steer - 提交用户干预指令
 * GET  /api/intent/steer?task_id=xxx - 获取待处理的干预指令
 *
 * 支持的 steer 操作:
 * - skip_steps: ["recall"|"debate"|"jeval"|"supplement"]
 * - force_direction: "LONG"|"SHORT"|"NEUTRAL"
 * - override_confidence: number (0-1)
 *
 * 注: 生产环境应使用 Redis/DB 存储，此处用模块级内存 map（单进程）。
 */
import { NextRequest, NextResponse } from "next/server";

// 内存存储: task_id -> steer 指令队列
const steerQueue = new Map<string, Array<Record<string, unknown>>>();

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const taskId = body.task_id;
    const steer = body.steer || {};

    if (!taskId) {
      return NextResponse.json({ success: false, error: "缺少 task_id" }, { status: 400 });
    }

    const validSteps = ["recall", "debate", "jeval", "supplement"];
    const validDirections = ["LONG", "SHORT", "NEUTRAL"];

    // 参数校验
    if (steer.skip_steps && !Array.isArray(steer.skip_steps)) {
      return NextResponse.json({ success: false, error: "skip_steps 必须是数组" }, { status: 400 });
    }
    if (steer.skip_steps) {
      for (const s of steer.skip_steps) {
        if (!validSteps.includes(s)) {
          return NextResponse.json({ success: false, error: `无效步骤: ${s}` }, { status: 400 });
        }
      }
    }
    if (steer.force_direction && !validDirections.includes(steer.force_direction)) {
      return NextResponse.json({ success: false, error: `无效方向: ${steer.force_direction}` }, { status: 400 });
    }
    if (steer.override_confidence !== undefined) {
      const c = Number(steer.override_confidence);
      if (isNaN(c) || c < 0 || c > 1) {
        return NextResponse.json({ success: false, error: "override_confidence 必须在 0-1 之间" }, { status: 400 });
      }
    }

    if (!steerQueue.has(taskId)) {
      steerQueue.set(taskId, []);
    }
    steerQueue.get(taskId)!.push({ ...steer, submitted_at: new Date().toISOString() });

    return NextResponse.json({ success: true, task_id: taskId, queued: steerQueue.get(taskId)!.length });
  } catch (e) {
    return NextResponse.json(
      { success: false, error: e instanceof Error ? e.message : String(e) },
      { status: 500 },
    );
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const taskId = searchParams.get("task_id");
  if (!taskId) {
    return NextResponse.json({ success: false, error: "缺少 task_id" }, { status: 400 });
  }
  const queue = steerQueue.get(taskId) || [];
  // 返回并清空队列（消费）
  steerQueue.set(taskId, []);
  return NextResponse.json({ success: true, task_id: taskId, steer_instructions: queue });
}
