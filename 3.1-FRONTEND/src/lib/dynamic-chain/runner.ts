/**
 * Dynamic Chain - Runner
 *
 * 主循环：generateInitialPlan → executeStepPlan → reflect → 调整/进入下一步
 *
 * 返回 DynamicChainResult，可被 task-manager.ts 直接使用或转换为 Markdown。
 */

import type { GraphReflectionState } from '../graph-reflection-bridge';
import { generateInitialPlan, initGraphState } from './graph-planner';
import { executeStepPlan } from './executor';
import { reflect, DYNAMIC_CHAIN_CONSTANTS } from './reflect-engine';

import type {
  DynamicChainContext,
  DynamicChainResult,
  DynamicPlan,
  PlanStep,
  ReflectDecision,
  StepExecutionResult,
} from './types';

export type { DynamicChainResult, DynamicChainContext };

const { MAX_ITERATIONS, MAX_REFLECTIONS_PER_STEP } = DYNAMIC_CHAIN_CONSTANTS;

// ============================================================
// Utility: 汇总输出
// ============================================================

function buildSummary(
  plan: DynamicPlan,
  results: StepExecutionResult[],
  graphState: GraphReflectionState,
  trace: { stepId: string; decision: string; reason: string }[],
): string {
  const intro = `# 动态思维链结果 · ${plan.chainId}\n\n` +
                `**意图**：${plan.steps[0]?.name ?? 'N/A'}（动态计划共 ${plan.steps.length} 步）\n\n` +
                `**思考模式**：动态计划-执行-反思闭环\n\n`;

  // 每个步骤的内容
  const body = plan.steps
    .map((s, idx) => {
      const res = results.find((r) => r.stepId === s.id);
      if (!res) return `### ${s.name}\n\n*步骤未执行*`;
      return `### ${idx + 1}. ${s.name}\n\n` +
             `${res.content}\n\n` +
             `**评估**：Confidence=${res.confidence.toFixed(2)}，Risk=${res.riskScore.toFixed(2)}，` +
             `问题=${res.issuesFound.length}，耗时=${res.latencyMs}ms / ${res.tokenCost} tokens\n\n`;
    })
    .join('\n---\n\n');

  // 摘要
  const completedNodes = Array.from(graphState.architectureNodes.values()).filter(
    (n) => n.status === 'completed'
  );
  const avgConf =
    completedNodes.reduce((s, n) => s + (n.confidence ?? 0), 0) /
    Math.max(completedNodes.length, 1);
  const maxRisk = Math.max(
    ...completedNodes.map((n) => n.riskScore ?? 0),
    0
  );

  const summary = `---\n\n## 综合评估\n\n` +
    `- 完成步骤：${completedNodes.length} / ${plan.steps.length}\n` +
    `- 平均置信度：${avgConf.toFixed(2)}\n` +
    `- 最高风险评分：${maxRisk.toFixed(2)}\n` +
    `- 反思决策次数：${trace.filter((t) => t.decision !== 'CONTINUE').length}\n` +
    `- highValue 节点（压缩后保留）：${graphState.compressionSignal.highValueNodes.length}\n` +
    `- compressible 节点（可压缩）：${graphState.compressionSignal.compressibleNodes.length}\n`;

  const traceBlock = `\n\n## 反思决策跟踪\n\n${
    trace.length === 0
      ? '_无额外反思决策，流程一次性完成_'
      : trace
          .map(
            (t) => `- **${t.decision}** · ${t.stepId} · ${t.reason}`
          )
          .join('\n')
  }\n`;

  return intro + body + summary + traceBlock;
}

// ============================================================
// Runner 主循环
// ============================================================

/**
 * 入口：根据 DynamicChainContext 执行动态链（plan-execute-reflect）
 */
export function runDynamicChain(ctx: DynamicChainContext): DynamicChainResult {
  // 初始化 graph state & plan
  const graphState = initGraphState(ctx.sessionId);
  const initialPlan = generateInitialPlan(ctx);

  // 运行时变量
  const plan: DynamicPlan = { ...initialPlan, steps: [...initialPlan.steps] };
  const executedResults: StepExecutionResult[] = [];
  const trace: { stepId: string; decision: string; reason: string }[] = [];
  const skippedSteps: string[] = [];
  let iteration = 0;
  let currentIndex = 0;
  let reflectionCountOnStep = 0;
  let lastStepId: string | null = null;

  // 主循环
  while (currentIndex < plan.steps.length && iteration < MAX_ITERATIONS) {
    iteration++;
    const step: PlanStep = plan.steps[currentIndex];

    // 同一 step 若已达到反射上限 → 强制继续
    if (lastStepId === step.id) {
      reflectionCountOnStep += 1;
    } else {
      reflectionCountOnStep = 0;
      lastStepId = step.id;
    }

    // 执行步骤
    const result = executeStepPlan(step, ctx, graphState, executedResults);
    executedResults.push(result);

    // 反思
    const decision: ReflectDecision = reflect(
      plan,
      graphState,
      result,
      ctx,
      iteration,
      reflectionCountOnStep
    );
    trace.push({
      stepId: step.id,
      decision: decision.type,
      reason: decision.reason,
    });

    // 写回 graphState.dynamicChain
    graphState.dynamicChain.iteration = iteration;
    graphState.dynamicChain.lastDecision = decision.type;
    graphState.dynamicChain.lastDecisionTargetStepId = decision.targetStepId;
    graphState.dynamicChain.lastDecisionReason = decision.reason;
    graphState.dynamicChain.planTrace.push({
      stepId: step.id,
      decision: decision.type,
      confidence: result.confidence,
    });

    // 按决策推进
    switch (decision.type) {
      case 'CONTINUE':
        currentIndex++;
        break;

      case 'REDO': {
        // 在 plan 末尾附加该 step（标记为重做）
        const redoIndex = plan.steps.findIndex((s) => s.id === decision.targetStepId);
        if (redoIndex >= 0) {
          currentIndex = redoIndex;
        } else {
          currentIndex++;
        }
        break;
      }

      case 'INSERT_BEFORE': {
        if (decision.newStep) {
          plan.steps.splice(currentIndex + 1, 0, decision.newStep);
          currentIndex++; // 跳过到新子步骤
        } else {
          currentIndex++;
        }
        break;
      }

      case 'JUMP_TO': {
        const jumpIdx = plan.steps.findIndex((s) => s.id === decision.targetStepId);
        if (jumpIdx >= 0) {
          // 标记被跳过的步骤
          for (let i = currentIndex + 1; i < jumpIdx; i++) {
            skippedSteps.push(plan.steps[i].id);
          }
          currentIndex = jumpIdx;
        } else {
          currentIndex++;
        }
        break;
      }

      case 'EARLY_TERMINATE':
        currentIndex = plan.steps.length; // 退出循环
        break;

      default:
        currentIndex++;
    }
  }

  // 汇总
  const avgConf =
    executedResults.reduce((s, r) => s + r.confidence, 0) /
    Math.max(executedResults.length, 1);
  const maxRisk = Math.max(...executedResults.map((r) => r.riskScore), 0);
  const totalLatency = executedResults.reduce((s, r) => s + r.latencyMs, 0);
  const totalTokens = executedResults.reduce((s, r) => s + r.tokenCost, 0);
  const summaryMarkdown = buildSummary(plan, executedResults, graphState, trace);

  return {
    success: true,
    chainId: plan.chainId,
    steps: plan.steps,
    stepResults: executedResults,
    avgConfidence: avgConf,
    maxRisk,
    totalLatencyMs: totalLatency,
    totalTokens,
    iterations: iteration,
    summaryMarkdown,
    graphState,
    metadata: {
      reflectionTrace: trace.map((t) => ({
        stepId: t.stepId,
        decision: t.decision,
        reason: t.reason,
      })),
      skippedSteps,
      planRationale: plan.rationale,
      isDynamic: true,
    },
  };
}

/**
 * 便捷入口：快速组装 context 并执行动态链（供 task-manager 等调用者使用）
 */
export function quickRun(params: {
  intent: DynamicChainContext['intent'];
  message: string;
  sessionId: string;
  symbol: string;
  category: string;
  displayName: string;
  instId: string;
  thinkingMode?: 'quick' | 'standard' | 'deep';
  lang?: 'zh' | 'en';
  entities?: DynamicChainContext['entities'];
  marketData?: DynamicChainContext['marketData'];
}): DynamicChainResult {
  const ctx: DynamicChainContext = {
    intent: params.intent,
    message: params.message,
    sessionId: params.sessionId,
    symbol: params.symbol,
    category: params.category,
    displayName: params.displayName,
    instId: params.instId,
    thinkingMode: params.thinkingMode ?? 'standard',
    lang: params.lang ?? 'zh',
    entities: params.entities,
    marketData: params.marketData,
  };
  return runDynamicChain(ctx);
}
