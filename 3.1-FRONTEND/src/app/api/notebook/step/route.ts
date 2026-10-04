// ============================================================
// /api/notebook/step — 步进操作 (3.1 内存版)
// POST   { taskId, stepId, output, artifacts } — 完成一步
// PATCH  { taskId, action, stepId, targetStep, reason } — 决策动作
// GET    ?taskId=... — 查询当前激活步骤
// ============================================================

import { NextRequest, NextResponse } from 'next/server';
import {
  loadState,
  completeStep,
  skipStep,
  activateNextStep,
  applyAction,
  initDZEChain,
  updateStep,
} from '@/lib/notebook/step-controller';
import type { StepId, StepAction } from '@/lib/notebook/types';

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const taskId = url.searchParams.get('taskId');
  const state = loadState();
  const task = taskId
    ? state.tasks.find((t) => t.id === taskId)
    : state.tasks.find((t) => t.id === state.currentTaskId);
  const active = task?.steps.find((s) => s.status === 'active');
  return NextResponse.json({
    success: true,
    data: {
      currentTask: task || null,
      activeStep: active || null,
      allSteps: task?.steps || [],
    },
  });
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { taskId, stepId, output = '', artifacts = [], notes = '' } = body;
    if (!taskId || !stepId) {
      return NextResponse.json(
        { success: false, error: 'taskId and stepId required' },
        { status: 400 }
      );
    }

    if (notes) {
      updateStep(taskId, stepId as StepId, { notes });
    }

    const state = completeStep(taskId, stepId as StepId, output, artifacts);
    const result = activateNextStep(taskId);

    return NextResponse.json({
      success: true,
      data: {
        state: result.state,
        nextStepId: result.nextStepId,
        completedStep: stepId,
        message: result.nextStepId
          ? `步骤 ${stepId} 完成，已激活下一步 ${result.nextStepId}`
          : '全部步骤完成，任务归档中',
      },
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
    const { taskId, action, stepId, targetStep, reason, output, artifacts, initDZE } = body;
    if (!taskId) {
      return NextResponse.json(
        { success: false, error: 'taskId required' },
        { status: 400 }
      );
    }

    // D-Z-E 链初始化
    if (initDZE) {
      const chain = initDZEChain(taskId, body.dzeScope || taskId);
      return NextResponse.json({
        success: true,
        data: { chain, state: loadState() },
      });
    }

    // output 更新
    if (output !== undefined && !action) {
      const state = updateStep(taskId, stepId as StepId, { output, artifacts: artifacts || [] });
      return NextResponse.json({ success: true, data: { state } });
    }

    // 决策动作
    if (action) {
      const state = applyAction(taskId, action as StepAction, targetStep, reason);
      return NextResponse.json({
        success: true,
        data: { state, action },
      });
    }

    // skip 单步
    if (stepId && reason) {
      const state = skipStep(taskId, stepId as StepId, reason);
      return NextResponse.json({ success: true, data: { state } });
    }

    return NextResponse.json(
      { success: false, error: 'no valid action provided' },
      { status: 400 }
    );
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : String(err) },
      { status: 500 }
    );
  }
}
