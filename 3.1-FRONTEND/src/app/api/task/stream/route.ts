import { NextRequest } from 'next/server';
import {
  createAndExecuteTask,
  canCreateTask,
  cleanupOldTasks,
  listTasks,
  TASKS_DIR,
  RESULTS_DIR,
} from '@/lib/task-manager';
import { emitMonitorEvent } from '@/lib/monitor-bus';
import { readFile } from 'fs/promises';
import { existsSync } from 'fs';
import { join } from 'path';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  // closeStream: 安全关闭流，避免 TS 在闭包中对 controller 做窄化（never）
  const closeStream = () => {
    const c = controller;
    if (c) {
      try { c.close(); } catch { /* already closed */ }
      controller = null;
    }
  };

  const stream = new ReadableStream({
    start(c) {
      controller = c;
    },
    cancel() {
      controller = null;
    },
  });

  const sendEvent = (event: string, data: Record<string, unknown>) => {
    const c = controller;
    if (!c) return;
    try {
      const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
      c.enqueue(encoder.encode(payload));
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
        closeStream();
        return;
      }

      // ===== 澄清回复检测：关联到原任务继续执行 =====
      // 用户回复"1-4"或"快速概览"等选项关键词时，关联到最近的 awaiting_clarification 任务
      const clarificationPatterns = ['1', '2', '3', '4', '快速概览', '技术分析', '基本面分析', '深度分析', '深度报告', 'quick overview', 'technical analysis', 'fundamental analysis', 'deep analysis', 'detailed report'];
      const normalizedMsg = message.trim().toLowerCase();
      const isClarificationReply = clarificationPatterns.some(p => normalizedMsg === p.toLowerCase());

      let clarificationContext: { originalTaskId: string; originalIntent: any; originalMessage: string } | null = null;

      if (isClarificationReply) {
        // 查找最近的 awaiting_clarification 任务
        const recentTasks = listTasks(5, 'awaiting_clarification');
        if (recentTasks.length > 0) {
          const latestTask = recentTasks[0];
          try {
            const taskFile = await readFile(join(TASKS_DIR, `${latestTask.task_id}.json`), 'utf-8');
            const originalTask = JSON.parse(taskFile);
            clarificationContext = {
              originalTaskId: latestTask.task_id,
              originalIntent: originalTask.intent,
              originalMessage: originalTask.message,
            };
            console.log(`[TaskStream] 检测到澄清回复 "${message}"，关联到原任务 ${latestTask.task_id}`);
          } catch (e) {
            console.warn('[TaskStream] 关联原任务失败:', e);
          }
        }
      }

      // 并发限制检查
      if (!canCreateTask()) {
        sendEvent('error', { error: 'Too many pending tasks', pending_limit: 3 });
        closeStream();
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
      // 如果是澄清回复，使用原任务的完整上下文
      const effectiveMessage = clarificationContext
        ? `${clarificationContext.originalMessage} [用户选择: ${message.trim()}]`
        : message.trim();

      const effectiveThinkingMode = clarificationContext?.originalIntent?.thinking_mode || thinking_mode || 'quick';

      const { task, result } = await createAndExecuteTask({
        message: effectiveMessage,
        thinking_mode: effectiveThinkingMode,
        session_id,
        llm_model,
        intent_method,
        lang: lang || 'zh',
        trading_mode: trading_mode || 'ai_skill',
        onProgress: (event) => {
          // 将Planner进度事件转发到SSE
          sendEvent('progress', event as unknown as Record<string, unknown>);
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
        } else {
          // 回退路径：内联执行（gateway_inline_v2_with_graph_reflection）
          // 从 execution_summary.graph_reflection + step_metadata 构建 chain_trace
          const execSummary = result.execution_summary as any;
          const graphReflection = execSummary?.graph_reflection;
          const stepMetadatas = (result.metadata as any)?.step_metadata || [];
          const chainExecuted: string[] = execSummary?.chain_executed || [];

          const STEP_ICONS: Record<string, string> = {
            S1_RESEARCH: '🔍', S2_ANALYSIS: '🧠', S3_DESIGN: '📐',
            S4_VALIDATE: '✅', S5_EXECUTE: '⚡',
          };
          const STEP_NAMES: Record<string, string> = {
            S1_RESEARCH: '市场感知', S2_ANALYSIS: '第一性分析', S3_DESIGN: '场景设计',
            S4_VALIDATE: '策略验证', S5_EXECUTE: '执行计划',
          };

          const aNodes = stepMetadatas.map((sm: any) => ({
            id: sm.step,
            name: STEP_NAMES[sm.step] || sm.step,
            icon: STEP_ICONS[sm.step] || '⚙️',
            layer: 'A',
            stage: sm.step?.split('_')[0]?.toLowerCase() || 'execute',
            chain: 'S_SERIES',
            is_skill: false,
            status: 'done',
            confidence: sm.confidence,
            risk_score: sm.riskScore,
            issues: sm.issues || [],
            corrections: sm.corrections || [],
            gate_passed: sm.gatePassed,
          }));

          const quality = execSummary?.quality || {};

          chain_trace = {
            intent: {
              type: task.intent.type,
              confidence: task.intent.confidence,
              method: 'llm',
              entities: task.intent.entities || {},
            },
            plan: {
              chain_id: 'inline_s_series',
              chain_name: chainExecuted.join(' → '),
              planned_steps: chainExecuted.map((s: string) => ({
                step_id: s,
                stage: s?.split('_')[0]?.toLowerCase() || 'execute',
                chain: 'S_SERIES',
                selected_skills: [],
              })),
              complexity: execSummary?.thinking_depth || task.thinking_mode || 'standard',
              total_budget: 6000,
              rationale: '内联执行 S 系列链路（Graph Reflection 融合）',
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
              execution_chain: chainExecuted.join(' → '),
              quality_score: quality.average_confidence ?? execSummary?.confidence ?? 0.7,
              risk_score: quality.max_risk ?? 0.3,
              grade: quality.overall_quality || 'good',
            },
            // 缺口4: 暴露图架构上下文数据（G 层）
            graph_reflection: graphReflection || null,
            step_metadata: stepMetadatas,
            rollbacks: (result.metadata as any)?.rollbacks || [],
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
          graph_reflection: (result.execution_summary as any)?.graph_reflection || null,
          trade_requires_confirmation: result.status === 'completed' && task.intent.type === 'execute_trade',
          chart_specs: result.chart_specs || [],
        });
      } else {
        sendEvent('done', {
          task_id: task.task_id,
          status: 'processing',
          intent: task.intent,
          thinking_mode: task.thinking_mode,
        });
      }

      closeStream();
    } catch (error) {
      console.error('[TaskStreamAPI] Error:', error);
      sendEvent('error', { error: error instanceof Error ? error.message : 'Unknown error' });
      closeStream();
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
