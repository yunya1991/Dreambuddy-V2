import { NextRequest } from 'next/server';
import {
  createAndExecuteTask,
  canCreateTask,
  cleanupOldTasks,
} from '@/lib/task-manager';
import { emitMonitorEvent } from '@/lib/monitor-bus';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;

  const stream = new ReadableStream({
    start(c) {
      controller = c;
    },
    cancel() {
      controller = null;
    },
  });

  const sendEvent = (event: string, data: Record<string, unknown>) => {
    if (!controller) return;
    try {
      const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
      controller.enqueue(encoder.encode(payload));
    } catch {
      // 客户端断开连接，忽略错误
    }
  };

  // 异步执行任务
  (async () => {
    try {
      const body = await request.json();
      const { message, thinking_mode, session_id, llm_model, intent_method, lang, trading_mode } = body;

      if (!message || typeof message !== 'string') {
        sendEvent('error', { error: 'message is required and must be a string' });
        controller?.close();
        return;
      }

      // 并发限制检查
      if (!canCreateTask()) {
        sendEvent('error', { error: 'Too many pending tasks', pending_limit: 3 });
        controller?.close();
        return;
      }

      // 清理过期任务
      cleanupOldTasks();

      // 📡 监控埋点: 用户请求进入
      emitMonitorEvent({
        trace_id: `stream_${Date.now()}_pending`,
        uid: session_id || 'anonymous',
        layer: 'frontend',
        phase: 'user_input',
        status: 'received',
        thinking_mode: thinking_mode || 'quick',
        message_preview: message.slice(0, 50),
      });

      // 发送开始事件
      sendEvent('started', { message: '任务已开始执行' });

      // 创建并执行任务，透传进度回调
      const { task, result } = await createAndExecuteTask({
        message: message.trim(),
        thinking_mode: thinking_mode || 'quick',
        session_id,
        llm_model,
        intent_method,
        lang: lang || 'zh',
        trading_mode: trading_mode || 'ai_skill',
        onProgress: (event) => {
          // 将Planner进度事件转发到SSE
          sendEvent('progress', event);
        },
      });

      // 发送完成事件
      if (result) {
        // 构建 chain_trace 数据
        const plannerResult = (result.execution_summary as any)?.planner_result;
        
        let chain_trace: Record<string, unknown> | undefined;
        
        if (plannerResult) {
          const STAGE_ICONS: Record<string, string> = {
            research: '🔍', analysis: '🧠', design: '📐', validate: '✅', execute: '⚡',
          };
          const getSkillIcon = (skillId: string): string => {
            if (skillId.startsWith('dream-')) return '🤖';
            if (skillId.startsWith('Regime') || skillId.startsWith('Classic')) return '📊';
            if (skillId.includes('fundamental') || skillId.includes('news')) return '📰';
            return '⚙️';
          };

          const plannerSteps = plannerResult.steps || [];
          const aNodes: any[] = [];

          for (const step of plannerSteps) {
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
            });
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
              complexity: (result.execution_summary as any)?.thinking_depth || task.thinking_mode || 'standard',
              total_budget: plannerResult.totalTokensUsed || 6000,
              rationale: 'ExecutionPlanner 动态编排',
            },
            nodes: [
              { id: 'B1_intent', name: '意图识别', icon: '🎯', layer: 'B', status: 'done', confidence: task.intent.confidence },
              { id: 'B2_route', name: '链路选择', icon: '🔀', layer: 'B', status: 'done' },
              { id: 'B3_complexity', name: '复杂度评估', icon: '📏', layer: 'B', status: 'done' },
              ...aNodes,
              { id: 'C1_execute', name: '链路执行', icon: '⚡', layer: 'C', status: 'done', latency_ms: result.execution_time_ms },
              { id: 'C2_reflect', name: '反射决策', icon: '🔄', layer: 'C', status: 'done' },
              { id: 'C3_aggregate', name: '结果聚合', icon: '📦', layer: 'C', status: 'done' },
            ],
            final: {
              execution_chain: plannerSteps.map((s: any) => s.stepId).join(' → '),
              quality_score: plannerResult.overallConfidence ? plannerResult.overallConfidence / 100 : 0.7,
              risk_score: 0.3,
              grade: 'good',
            },
          };
        }

        sendEvent('done', {
          task_id: task.task_id,
          status: result.status,
          intent: task.intent,
          thinking_mode: task.thinking_mode,
          content: result.content,
          content_type: result.content_type,
          execution_time_ms: result.execution_time_ms,
          artifacts_produced: result.artifacts_produced,
          execution_summary: result.execution_summary,
          metadata: result.metadata,
          chain_trace,
          trade_requires_confirmation: result.status === 'completed' && task.intent.type === 'execute_trade',
        });
      } else {
        sendEvent('done', {
          task_id: task.task_id,
          status: 'processing',
          intent: task.intent,
          thinking_mode: task.thinking_mode,
        });
      }

      controller?.close();
    } catch (error) {
      console.error('[TaskStreamAPI] Error:', error);
      sendEvent('error', { error: error instanceof Error ? error.message : 'Unknown error' });
      controller?.close();
    }
  })();

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
