import { NextRequest, NextResponse } from 'next/server';
import {
  createAndExecuteTask,
  getTaskStatus,
  listTasks,
  canCreateTask,
  cleanupOldTasks,
  getEstimatedTimeMs,
  triggerWorkBuddyAsync,
  isTradeIntent,
  ARTIFACTS_DIR,
  TASKS_DIR,
  RESULTS_DIR,
  type TaskStatus,
} from '@/lib/task-manager';
import { emitMonitorEvent } from '@/lib/monitor-bus';
import { collectStrategyTaskOrderFeedItems } from '@/lib/strategy-artifacts';
import * as fs from 'fs';
import * as path from 'path';

/**
 * POST /api/task - 创建任务并立即执行（v2.0 中台即时触发）
 *
 * 核心变更：
 * - 对话任务：中台内联执行，POST响应直接包含结果（秒级）
 * - 交易任务：返回待确认提示，需用户确认执行时间
 * - 异步回退：如果内联执行不适用，触发WorkBuddy异步执行
 *
 * 响应模式：
 * - 同步完成：data.status='completed' + data.content 直接可用
 * - 待确认：data.status='completed' + data.content 含确认提示
 * - 异步执行：data.status='processing' + poll_url，前端轮询
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { message, thinking_mode, session_id, llm_model, intent_method } = body;

    if (!message || typeof message !== 'string') {
      return NextResponse.json(
        { success: false, error: 'message is required and must be a string' },
        { status: 400 }
      );
    }

    // 并发限制检查
    if (!canCreateTask()) {
      return NextResponse.json(
        {
          success: false,
          error: 'Too many pending tasks. Please wait for current tasks to complete.',
          pending_limit: 3,
        },
        { status: 429 }
      );
    }

    // 清理过期任务
    cleanupOldTasks();

    // 📡 监控埋点: 用户请求进入
    const tempTraceId = `task_${Date.now()}_pending`;
    emitMonitorEvent({
      trace_id: tempTraceId,
      uid: session_id || 'anonymous',
      layer: 'frontend',
      phase: 'user_input',
      status: 'received',
      thinking_mode: thinking_mode || 'quick',
      message_preview: message.slice(0, 50),
    });

    // v2.0 核心：创建并立即执行
    const { task, result, needAsync } = await createAndExecuteTask({
      message: message.trim(),
      thinking_mode: thinking_mode || 'quick',
      session_id,
      llm_model,
      intent_method,
    });

    const estimatedTime = getEstimatedTimeMs(result?.execution_summary?.chain_executed || []);
    const isTrade = isTradeIntent(task.intent.type);

    // 📡 监控埋点: 意图识别完成
    emitMonitorEvent({
      trace_id: task.task_id,
      uid: session_id || 'anonymous',
      layer: 'frontend',
      phase: 'intent_recognized',
      status: 'completed',
      intent: task.intent.type,
      thinking_mode: task.thinking_mode,
      chain: result?.execution_summary?.chain_executed || [],
    });

    console.log(
      `[TaskAPI] Task ${isTrade ? 'pending-confirmation' : 'executed'}: ${task.task_id} | ` +
      `intent: ${task.intent.type} | mode: ${task.thinking_mode} | ` +
      `${result ? `result: ${result.status}` : 'async'}`
    );

    // 如果需要异步执行（回退模式）
    if (needAsync) {
      // 异步触发WorkBuddy执行（不阻塞响应）
      triggerWorkBuddyAsync(task.task_id).catch(err => {
        console.error(`[TaskAPI] Async trigger failed: ${task.task_id}`, err);
      });

      return NextResponse.json({
        success: true,
        data: {
          task_id: task.task_id,
          status: 'processing',
          intent: task.intent.type,
          confidence: task.intent.confidence,
          thinking_mode: task.thinking_mode,
          poll_url: `/api/task?id=${task.task_id}`,
          estimated_time_ms: estimatedTime,
          created_at: task.created_at,
          status_message: 'WorkBuddy is executing asynchronously...',
        },
      });
    }

    // 同步完成（对话任务）或待确认（交易任务）
    const responseData: Record<string, unknown> = {
      task_id: task.task_id,
      status: result!.status,
      intent: task.intent,
      thinking_mode: task.thinking_mode,
      created_at: task.created_at,
      updated_at: task.updated_at,
      // 直接携带结果内容，前端无需轮询
      content: result!.content,
      content_type: result!.content_type,
      execution_time_ms: result!.execution_time_ms,
      artifacts_produced: result!.artifacts_produced,
      execution_summary: result!.execution_summary,
      metadata: result!.metadata,
    };

    // 交易任务标记
    if (isTrade) {
      responseData.trade_requires_confirmation = true;
      responseData.status_message = '交易任务需确认执行时间';
    }

    return NextResponse.json({
      success: true,
      data: responseData,
    });
  } catch (error) {
    console.error('[TaskAPI] POST error:', error);
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}

/**
 * GET /api/task - 查询任务状态或列表
 *
 * 查询模式:
 * - ?id=task_xxx       → 查询单个任务状态
 * - ?action=list       → 列出所有任务
 * - ?action=list&status=pending → 按状态过滤
 * - ?action=cleanup    → 清理过期任务
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const taskId = searchParams.get('id');
    const action = searchParams.get('action');

    // 查询单个任务状态
    if (taskId) {
      const { task, result } = getTaskStatus(taskId);

      if (!task) {
        return NextResponse.json(
          { success: false, error: `Task not found: ${taskId}` },
          { status: 404 }
        );
      }

      // 合并任务和结果信息
      const responseData: Record<string, unknown> = {
        task_id: task.task_id,
        status: task.status,
        message: task.message,
        intent: task.intent,
        thinking_mode: task.thinking_mode,
        created_at: task.created_at,
        updated_at: task.updated_at,
      };

      // 如果有结果，附加结果内容
      if (result) {
        responseData.status = result.status;
        responseData.content = result.content;
        responseData.content_type = result.content_type;
        responseData.execution_time_ms = result.execution_time_ms;
        responseData.artifacts_produced = result.artifacts_produced;
        responseData.execution_summary = result.execution_summary;
        responseData.metadata = result.metadata;
      }

      // 如果失败，附加错误信息
      if (result?.error) {
        responseData.error = result.error;
      }

      // 状态消息
      if (task.status === 'pending') {
        responseData.status_message = 'Waiting for WorkBuddy to process...';
      } else if (task.status === 'processing') {
        responseData.status_message = 'WorkBuddy is executing...';
      } else if (task.status === 'timeout') {
        responseData.status_message = 'Task timed out (30 min). You can retry or use direct mode.';
      }

      return NextResponse.json({
        success: true,
        data: responseData,
      });
    }

    // 列出任务
    if (action === 'list') {
      const limit = parseInt(searchParams.get('limit') || '20', 10);
      const status = searchParams.get('status') as TaskStatus | null;
      const tasks = listTasks(limit, status || undefined);

      return NextResponse.json({
        success: true,
        data: {
          tasks,
          total: tasks.length,
        },
      });
    }

    // 清理过期任务
    if (action === 'cleanup') {
      const deleted = cleanupOldTasks();
      return NextResponse.json({
        success: true,
        data: { deleted, message: `Cleaned up ${deleted} old task/result files` },
      });
    }

    // Product Hub feed 接口 - 供产物中台消费
    if (action === 'feed') {
      return handleFeed(searchParams);
    }

    // 默认：返回任务系统状态
    return NextResponse.json({
      success: true,
      data: {
        mode: 'gateway_inline_v2',
        description: '中台即时触发模式：POST创建任务后立即执行，对话任务秒级响应',
        tasks_dir: 'artifacts/tasks/',
        results_dir: 'artifacts/results/',
        max_concurrent: 3,
        timeout_minutes: 30,
        execution_modes: {
          conversation: '内联执行（秒级响应）',
          trade: '返回待确认（需用户确认执行时间）',
          async: '异步回退（通过task_poller.py执行）',
        },
        usage: {
          create_and_execute: 'POST /api/task { message, thinking_mode?, session_id? }',
          poll: 'GET /api/task?id=task_xxx',
          list: 'GET /api/task?action=list&limit=20',
          feed: 'GET /api/task?action=feed (Product Hub compatible)',
          cleanup: 'GET /api/task?action=cleanup',
        },
      },
    });
  } catch (error) {
    console.error('[TaskAPI] GET error:', error);
    return NextResponse.json(
      { success: false, error: error instanceof Error ? error.message : 'Unknown error' },
      { status: 500 }
    );
  }
}

/**
 * Product Hub feed 接口
 * 返回兼容产物中台 index.json 格式的任务和结果列表
 */
function handleFeed(searchParams: URLSearchParams): NextResponse {
  void searchParams;
  const feedItems: Array<Record<string, unknown>> = [];

  // 扫描任务文件
  try {
    if (fs.existsSync(TASKS_DIR)) {
      const taskFiles = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.json'));
      for (const f of taskFiles.slice(0, 50)) {
        try {
          const task = JSON.parse(fs.readFileSync(path.join(TASKS_DIR, f), 'utf-8'));
          feedItems.push({
            file: `tasks/${f}`,
            title: `Dashboard Task: ${task.message?.slice(0, 50) || 'Unknown'}`,
            date: task.created_at,
            type: 'dashboard_task',
            chain_phase: 'dashboard',
            tags: ['dashboard', task.intent?.type || 'unknown', task.thinking_mode || 'quick'],
            status: task.status,
            source: 'dashboard',
            task_id: task.task_id,
          });
        } catch { /* skip invalid */ }
      }
    }
  } catch { /* skip */ }

  // 扫描结果文件
  try {
    if (fs.existsSync(RESULTS_DIR)) {
      const resultFiles = fs.readdirSync(RESULTS_DIR).filter(f => f.endsWith('.json'));
      for (const f of resultFiles.slice(0, 50)) {
        try {
          const result = JSON.parse(fs.readFileSync(path.join(RESULTS_DIR, f), 'utf-8'));
          feedItems.push({
            file: `results/${f}`,
            title: `Dashboard Result: ${result.content?.slice(0, 50) || 'Completed'}`,
            date: result.created_at,
            type: 'dashboard_result',
            chain_phase: 'dashboard',
            tags: ['dashboard', 'result', result.status],
            status: result.status,
            source_task: result.task_id,
            execution_time_ms: result.execution_time_ms,
            artifacts_produced: result.artifacts_produced,
          });
        } catch { /* skip invalid */ }
      }
    }
  } catch { /* skip */ }

  try {
    feedItems.push(
      ...collectStrategyTaskOrderFeedItems({ artifactsDir: ARTIFACTS_DIR }),
    );
  } catch { /* skip */ }

  // 按时间倒序
  feedItems.sort((a, b) => new Date(b.date as string).getTime() - new Date(a.date as string).getTime());

  return NextResponse.json({
    success: true,
    data: {
      feed: feedItems,
      total: feedItems.length,
      format: 'product_hub_compatible',
    },
  });
}
