// ============================================================
// POST /api/notebook — 启动新笔记本任务
// GET  /api/notebook — 查询笔记本状态
// PATCH /api/notebook — 切换当前任务
// 3.1 迁移版: 使用内存态 step-controller
// ============================================================

import { NextRequest, NextResponse } from 'next/server';
import {
  loadState,
  startTask as scStartTask,
  getStats,
  setCurrentTask,
  seedMockData,
} from '@/lib/notebook/step-controller';

export async function GET(_req: NextRequest) {
  const state = loadState();
  const stats = getStats();
  return NextResponse.json({
    success: true,
    data: { state, stats },
    timestamp: new Date().toISOString(),
  });
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const {
      title,
      userInput,
      intent = 'triple_chain',
      sessionId = `sess_${Date.now()}`,
      entities = {},
      routing = null,
    } = body;

    if (!title || !userInput) {
      return NextResponse.json(
        { success: false, error: 'title and userInput required' },
        { status: 400 }
      );
    }

    const { state, task } = scStartTask({
      title,
      userInput,
      intent,
      sessionId,
      entities,
      routing,
    });

    return NextResponse.json({
      success: true,
      data: { task, state },
      message: `任务 "${title}" 已创建 — Step 1 需求解析完成, Step 2 思维链调研已激活`,
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const body = await req.json();
    const { taskId } = body;
    const state = setCurrentTask(taskId);
    return NextResponse.json({
      success: true,
      data: { state },
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
