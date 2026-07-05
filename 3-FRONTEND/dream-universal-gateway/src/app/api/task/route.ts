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
    const { message, thinking_mode, session_id, llm_model, intent_method, lang } = body;

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
      lang: lang || 'zh',
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

    // 构建编排追踪数据 (三层架构可视化)
    const stepMeta: Record<string, { label: string; icon: string }> = {
      'S0_DIRECT_ANSWER': { label: '快速回答', icon: '💬' },
      'S1_RESEARCH':       { label: '调研', icon: '🔍' },
      'S2_ANALYSIS':       { label: '分析', icon: '🧠' },
      'S3_DESIGN':         { label: '设计', icon: '📐' },
      'S4_VALIDATE':       { label: '验证', icon: '✅' },
      'S5_EXECUTE':        { label: '执行', icon: '⚡' },
    };

    const summary = result!.execution_summary;
    const executedChain = summary?.chain_executed || [];
    const stepMetaList = summary?.step_metadata || [];
    const quality = summary?.quality;

    // 检查是否来自 ExecutionPlanner
    const plannerResult = (summary as any)?.planner_result;

    let chain_trace: Record<string, unknown>;

    if (plannerResult) {
      // ============================================================
      // 动态编排模式 — 从 ExecutionPlanner 结果构建 chain_trace
      // A层 = 思维阶段 + 动态选中技能（跨A/C/F链）
      // ============================================================
      const STAGE_ICONS: Record<string, string> = {
        research: '🔍', analysis: '🧠', design: '📐', validate: '✅', execute: '⚡',
      };

      // 技能链图标
      const getSkillIcon = (skillId: string): string => {
        if (skillId.startsWith('dream-')) return '🤖';
        if (skillId.startsWith('Regime') || skillId.startsWith('Classic')) return '📊';
        if (skillId.includes('fundamental') || skillId.includes('news')) return '📰';
        return '⚙️';
      };

      // A层节点：思维阶段 + 技能
      const plannerSteps = plannerResult.steps || [];
      const aNodes: any[] = [];

      for (const step of plannerSteps) {
        // 思维阶段节点
        const stepDef = step.definition || {};
        aNodes.push({
          id: step.stepId,
          name: stepDef.label || step.stepId,
          icon: stepDef.icon || STAGE_ICONS[step.stage] || '⚙️',
          layer: 'A',
          stage: step.stage,
          chain: step.chain,
          is_skill: false,
          status: step.status === 'completed' ? 'done' : step.status === 'running' ? 'active' : step.status,
          confidence: step.confidence ? step.confidence / 100 : undefined,
          tokens_used: step.tokensUsed,
          reflect_action: step.decision,
          artifact: result!.artifacts_produced?.find((a: any) =>
            a.chain_phase?.toLowerCase() === step.stepId.toLowerCase()
          )?.file,
        });

        // 技能子节点
        for (const skillCall of (step.skillsCalled || [])) {
          aNodes.push({
            id: skillCall.skillId,
            name: skillCall.skillName,
            icon: getSkillIcon(skillCall.skillId),
            layer: 'A',
            stage: step.stage,
            chain: step.chain,
            is_skill: true,
            status: 'done',
            confidence: skillCall.result?.confidence ? skillCall.result.confidence / 100 : undefined,
            tokens_used: skillCall.result?.tokensUsed,
            latency_ms: skillCall.latencyMs,
          });
        }
      }

      chain_trace = {
        intent: {
          type: task.intent.type,
          confidence: task.intent.confidence,
          method: 'llm' as const,
          entities: task.intent.entities || {},
        },
        plan: {
          chain_id: plannerResult.planId || 'dynamic',
          chain_name: plannerSteps.map((s: any) => s.stepId).join(' → '),
          planned_steps: plannerSteps.map((s: any) => ({
            step_id: s.stepId,
            stage: s.stage,
            chain: s.chain,
            selected_skills: (s.skillsCalled || []).map((sk: any) => sk.skillId),
          })),
          complexity: summary?.thinking_depth || task.thinking_mode || 'standard',
          total_budget: plannerResult.totalTokensUsed || 6000,
          rationale: 'ExecutionPlanner 动态编排',
        },
        nodes: [
          // B层 — 意图蓝图
          { id: 'B1_intent', name: '意图识别', icon: '🎯', layer: 'B', status: 'done', confidence: task.intent.confidence },
          { id: 'B2_route', name: '链路选择', icon: '🔀', layer: 'B', status: 'done' },
          { id: 'B3_complexity', name: '复杂度评估', icon: '📏', layer: 'B', status: 'done' },
          // A层 — 动态编排的步骤+技能
          ...aNodes,
          // C层 — 执行记录
          { id: 'C1_execute', name: '链路执行', icon: '⚡', layer: 'C', status: 'done', latency_ms: result!.execution_time_ms },
          { id: 'C2_reflect', name: '反射决策', icon: '🔄', layer: 'C', status: 'done' },
          { id: 'C3_aggregate', name: '结果聚合', icon: '📦', layer: 'C', status: 'done' },
        ],
        cost_report: undefined,
        compression: undefined,
        final: {
          execution_chain: plannerSteps.map((s: any) => s.stepId).join(' → '),
          quality_score: plannerResult.overallConfidence ? plannerResult.overallConfidence / 100 : (quality?.average_confidence || task.intent.confidence),
          risk_score: quality?.max_risk || 0.3,
          grade: quality?.overall_quality || 'good',
        },
      };
    } else {
      // ============================================================
      // S 链模式 — 保留原有逻辑（降级路径）
      // ============================================================
      chain_trace = {
        intent: {
          type: task.intent.type,
          confidence: task.intent.confidence,
          method: 'llm' as const,
          entities: task.intent.entities || {},
        },
        plan: {
          chain_id: task.intent.type,
          chain_name: executedChain.map((s: string) => stepMeta[s]?.label || s).join(' → '),
          complexity: summary?.thinking_depth || task.thinking_mode || 'moderate',
          total_budget: 6000,
          rationale: `链路=${task.thinking_mode}，节点=${executedChain.length}`,
        },
        nodes: [
          // B层 — 意图蓝图
          { id: 'B1_intent', name: '意图识别', icon: '🎯', layer: 'B', status: 'done', confidence: task.intent.confidence },
          { id: 'B2_route', name: '链路选择', icon: '🔀', layer: 'B', status: 'done' },
          { id: 'B3_complexity', name: '复杂度评估', icon: '📏', layer: 'B', status: 'done' },
          // A层 — 编排计划 (链路中的节点)
          ...executedChain.map((stepId: string) => {
            const meta = stepMeta[stepId] || { label: stepId, icon: '⚙️' };
            const stepData = stepMetaList.find((s: any) => s.step === stepId);
            const isSkipped = summary?.skipped_steps?.includes(stepId);
            return {
              id: stepId,
              name: meta.label,
              icon: meta.icon,
              layer: 'A' as const,
              status: isSkipped ? 'skipped' : 'done',
              confidence: stepData?.confidence,
              risk: stepData?.risk,
              artifact: result!.artifacts_produced?.find((a: any) =>
                a.chain_phase?.toLowerCase() === stepId.toLowerCase() ||
                a.chain_phase?.toLowerCase() === stepId.replace(/^S\d+_/, '').toLowerCase()
              )?.file,
            };
          }),
          // C层 — 执行记录
          { id: 'C1_execute', name: '链路执行', icon: '⚡', layer: 'C', status: 'done', latency_ms: result!.execution_time_ms },
          { id: 'C2_reflect', name: '反射决策', icon: '🔄', layer: 'C', status: 'done' },
          { id: 'C3_aggregate', name: '结果聚合', icon: '📦', layer: 'C', status: 'done' },
        ],
        cost_report: undefined,
        compression: undefined,
        final: {
          execution_chain: executedChain.join(' → '),
          quality_score: quality?.average_confidence || task.intent.confidence,
          risk_score: quality?.max_risk || 0.3,
          grade: quality?.overall_quality || 'good',
        },
      };
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
      chain_trace,
    };

    // 步进确认任务（D/Z/E 链中途等待用户选择）
    if (result!.status === 'awaiting_confirmation') {
      responseData.step_confirmation = result!.step_confirmation;
      responseData.status_message = '等待用户选择下一步操作';
    }

    // 意图澄清任务（LLM不确定用户意图，需用户选择选项）
    if (result!.status === 'awaiting_clarification') {
      responseData.clarification_state = (result as any).clarification_state;
      responseData.status_message = '意图不明确，请选择你要做的操作';
    }

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
