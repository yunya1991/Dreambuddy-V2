import { NextRequest, NextResponse } from 'next/server';
import {
  readTask,
  readResult,
  isTradeIntent,
  TASKS_DIR,
  RESULTS_DIR,
  type TaskFile,
  type ResultFile,
} from '@/lib/task-manager';
import { routeIntent } from '@/lib/intent';
import * as fs from 'fs';
import * as path from 'path';

/**
 * POST /api/task/confirm - 交易任务确认/定时/取消
 *
 * 请求体:
 * - task_id: string (必须)
 * - action: 'confirm' | 'schedule' | 'cancel' (必须)
 * - scheduled_time?: string (ISO8601, action=schedule时必须)
 *
 * 响应:
 * - confirm: 立即执行交易 → 触发WorkBuddy异步执行
 * - schedule: 定时执行 → 更新task文件scheduled字段
 * - cancel: 取消 → 更新task状态为cancelled
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { task_id, action, scheduled_time } = body;

    // 参数校验
    if (!task_id || typeof task_id !== 'string') {
      return NextResponse.json(
        { success: false, error: 'task_id is required' },
        { status: 400 }
      );
    }

    const validActions = ['confirm', 'schedule', 'cancel'];
    if (!action || !validActions.includes(action)) {
      return NextResponse.json(
        { success: false, error: `action must be one of: ${validActions.join(', ')}` },
        { status: 400 }
      );
    }

    // 读取任务
    const task = readTask(task_id);
    if (!task) {
      return NextResponse.json(
        { success: false, error: `Task not found: ${task_id}` },
        { status: 404 }
      );
    }

    // 校验：只有交易任务可以确认
    if (!isTradeIntent(task.intent.type)) {
      return NextResponse.json(
        { success: false, error: 'Only trade tasks can be confirmed' },
        { status: 400 }
      );
    }

    // 校验：任务状态必须为completed（即已返回确认提示的状态）
    if (task.status !== 'completed') {
      return NextResponse.json(
        { success: false, error: `Task status is ${task.status}, cannot confirm` },
        { status: 400 }
      );
    }

    const taskPath = path.join(TASKS_DIR, `${task_id}.json`);
    const now = new Date().toISOString();

    // ===== confirm: 立即执行 =====
    if (action === 'confirm') {
      // 更新任务状态为processing，添加confirmed标记
      task.status = 'processing';
      task.updated_at = now;
      (task as TaskFile & { confirmed?: boolean; confirmed_at?: string }).confirmed = true;
      (task as TaskFile & { confirmed?: boolean; confirmed_at?: string }).confirmed_at = now;
      fs.writeFileSync(taskPath, JSON.stringify(task, null, 2), 'utf-8');

      // 更新结果文件
      const chain = routeIntent(task.intent.type, 'moderate', {
    session_id: task.session_id,
    user_role: 'FREE',
    thinking_mode: task.thinking_mode,
    message_history: [task.message],
  }).chain;
      const entities = task.intent.entities || {};
      const symbol = entities.symbol || 'BTC';

      const result: ResultFile = {
        task_id: task.task_id,
        status: 'completed',
        created_at: now,
        execution_time_ms: 0,
        content: `✅ **交易任务已确认 - 即将执行**\n\n> 确认时间: ${now}\n> 品种: ${symbol}-USDT-SWAP\n> 执行链路: ${chain.join(' → ')}\n\n🔄 正在触发WorkBuddy执行引擎...`,
        content_type: 'markdown',
        execution_summary: {
          chain_executed: chain,
          total_steps: chain.length,
          skipped_steps: [],
          regime: 'RANGE_BOUND',
          confidence: task.intent.confidence,
        },
        metadata: {
          executor: 'gateway_confirm_v2',
          model: task.metadata.llm_model,
          cost_credits: 150,
        },
      };

      const resultPath = path.join(RESULTS_DIR, `result_${task_id}.json`);
      fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf-8');

      console.log(`[TaskConfirm] Trade confirmed: ${task_id} | chain: ${chain.join('→')}`);

      return NextResponse.json({
        success: true,
        data: {
          task_id,
          status: 'processing',
          confirmed: true,
          confirmed_at: now,
          chain,
          message: '交易任务已确认，正在执行',
        },
      });
    }

    // ===== schedule: 定时执行 =====
    if (action === 'schedule') {
      if (!scheduled_time) {
        return NextResponse.json(
          { success: false, error: 'scheduled_time is required for schedule action (ISO8601 format, e.g. 2026-05-14T14:30)' },
          { status: 400 }
        );
      }

      // 解析并校验时间
      let scheduledDate: Date;
      try {
        scheduledDate = new Date(scheduled_time);
        if (isNaN(scheduledDate.getTime())) throw new Error('Invalid date');
      } catch {
        return NextResponse.json(
          { success: false, error: 'Invalid scheduled_time format. Use ISO8601 (e.g. 2026-05-14T14:30)' },
          { status: 400 }
        );
      }

      // 不能是过去的时间
      if (scheduledDate.getTime() < Date.now()) {
        return NextResponse.json(
          { success: false, error: 'scheduled_time must be in the future' },
          { status: 400 }
        );
      }

      // 更新任务
      const scheduledTask = task as TaskFile & {
        scheduled?: boolean;
        scheduled_time?: string;
        confirmed?: boolean;
      };
      scheduledTask.status = 'scheduled';
      scheduledTask.updated_at = now;
      scheduledTask.scheduled = true;
      scheduledTask.scheduled_time = scheduled_time;
      scheduledTask.confirmed = true;
      fs.writeFileSync(taskPath, JSON.stringify(scheduledTask, null, 2), 'utf-8');

      // 更新结果
      const chain = routeIntent(task.intent.type, 'moderate', {
    session_id: task.session_id,
    user_role: 'FREE',
    thinking_mode: task.thinking_mode,
    message_history: [task.message],
  }).chain;
      const result: ResultFile = {
        task_id: task.task_id,
        status: 'completed',
        created_at: now,
        execution_time_ms: 0,
        content: `🕐 **交易任务已定时**\n\n> 定时执行时间: ${scheduled_time}\n> 品种: ${(task.intent.entities?.symbol || 'BTC')}-USDT-SWAP\n> 执行链路: ${chain.join(' → ')}\n\n系统将在指定时间自动执行交易。`,
        content_type: 'markdown',
        metadata: {
          executor: 'gateway_schedule_v2',
          model: task.metadata.llm_model,
        },
      };

      const resultPath = path.join(RESULTS_DIR, `result_${task_id}.json`);
      fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf-8');

      console.log(`[TaskConfirm] Trade scheduled: ${task_id} | at: ${scheduled_time}`);

      return NextResponse.json({
        success: true,
        data: {
          task_id,
          status: 'scheduled',
          scheduled_time,
          chain,
          message: `交易任务已定时，将在 ${scheduled_time} 执行`,
        },
      });
    }

    // ===== cancel: 取消 =====
    if (action === 'cancel') {
      task.status = 'cancelled';
      task.updated_at = now;
      fs.writeFileSync(taskPath, JSON.stringify(task, null, 2), 'utf-8');

      // 更新结果
      const result: ResultFile = {
        task_id: task.task_id,
        status: 'completed',
        created_at: now,
        execution_time_ms: 0,
        content: `🚫 **交易任务已取消**\n\n> 取消时间: ${now}\n> 品种: ${(task.intent.entities?.symbol || 'BTC')}-USDT-SWAP\n\n交易已取消，不会执行任何操作。`,
        content_type: 'markdown',
        metadata: {
          executor: 'gateway_cancel_v2',
          model: task.metadata.llm_model,
        },
      };

      const resultPath = path.join(RESULTS_DIR, `result_${task_id}.json`);
      fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf-8');

      console.log(`[TaskConfirm] Trade cancelled: ${task_id}`);

      return NextResponse.json({
        success: true,
        data: {
          task_id,
          status: 'cancelled',
          message: '交易任务已取消',
        },
      });
    }

    // 不应该到达这里
    return NextResponse.json(
      { success: false, error: 'Unknown action' },
      { status: 400 }
    );
  } catch (error) {
    console.error('[TaskConfirm] POST error:', error);
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}
