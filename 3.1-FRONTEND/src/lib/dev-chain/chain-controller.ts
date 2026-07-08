/**
 * S5 执行引擎 - 控制器
 *
 * 职责：
 *   1. 执行 E1 → E2 → E3（S5_EXECUTE 的内部链路）
 *   2. 生成策略代码、测试报告、部署信息
 *   3. 触发 WorkBuddy（后端实际执行）
 *
 * 对外暴露（供 S 系列 S5 步骤调用）：
 *   - executeS5(params) : 执行完整 E1→E2→E3 链
 *   - renderS5Summary(chainState, lang): 生成执行摘要
 */

import {
  S5ChainState,
  S5StepId,
  S5StepRuntime,
  S5StepExecutionResult,
  S5ExecutionContext,
  S5ExecutionResult,
} from './types';
import {
  S5_STEP_DEFINITIONS,
  S5_STEP_SEQUENCE,
  getS5StepDisplay,
  S5_ESTIMATED_TOTAL_MS,
} from './route';
import { executeStep } from './steps';

// ============================================================
// 1. 状态初始化
// ============================================================
function initS5Chain(ctx: S5ExecutionContext): S5ChainState {
  const now = new Date().toISOString();
  const steps: S5StepRuntime[] = S5_STEP_SEQUENCE.map(sid => ({
    id: sid,
    status: 'pending',
    output: '',
    artifacts: [],
  }));

  // 安全：对用户输入做 HTML 转义，防止 XSS
  const esc = (s: string) =>
    s.replace(/&/g, '&amp;')
     .replace(/</g, '&lt;')
     .replace(/>/g, '&gt;')
     .replace(/"/g, '&quot;')
     .replace(/'/g, '&#39;');
  const safeScope = ctx.userMessage ? esc(ctx.userMessage) : '';

  return {
    taskId: ctx.taskId,
    sessionId: ctx.sessionId,
    scopeDescription: safeScope,
    currentStepId: null,
    currentStepIndex: -1,
    steps,
    plannedStepIds: S5_STEP_SEQUENCE,
    createdAt: now,
    modifiedAt: now,
    totalDurationMs: 0,
    strategyParams: ctx.strategyParams,
  };
}

// ============================================================
// 2. 步进执行
// ============================================================
export interface S5AdvanceResult {
  state: S5ChainState;
  executedSteps: Array<{
    stepId: S5StepId;
    output: string;
    artifacts: string[];
    durationMs: number;
  }>;
  allStepsForDisplay: Array<{ id: S5StepId; label: string; icon: string; status: string }>;
  shouldTriggerWorkBuddy: boolean;
  isComplete: boolean;
}

function advanceS5Chain(
  state: S5ChainState,
  ctx: S5ExecutionContext,
): S5AdvanceResult {
  const executedSteps: Array<{
    stepId: S5StepId;
    output: string;
    artifacts: string[];
    durationMs: number;
  }> = [];
  let totalDuration = state.totalDurationMs;
  let shouldTrigger = false;
  const newSteps = [...state.steps];

  // 顺序执行所有待执行步骤（E 链无需用户确认）
  for (let i = state.currentStepIndex + 1; i < S5_STEP_SEQUENCE.length; i++) {
    const stepId = S5_STEP_SEQUENCE[i];
    const def = S5_STEP_DEFINITIONS[stepId];

    // 启动步骤
    newSteps[i] = {
      ...newSteps[i],
      status: 'active',
      startedAt: new Date().toISOString(),
    };

    // 执行
    const result: S5StepExecutionResult = executeStep({
      stepId,
      userMessage: ctx.userMessage,
      thinkingMode: ctx.thinkingMode,
      lang: ctx.lang,
      strategyParams: ctx.strategyParams,
    });

    // 更新状态
    newSteps[i] = {
      ...newSteps[i],
      status: 'done',
      output: result.output,
      artifacts: result.artifacts,
      completedAt: new Date().toISOString(),
      duration_ms: result.durationMs,
    };

    executedSteps.push({
      stepId,
      output: result.output,
      artifacts: result.artifacts,
      durationMs: result.durationMs,
    });

    totalDuration += result.durationMs;

    if (result.shouldTriggerWorkBuddy) {
      shouldTrigger = true;
    }
  }

  const updatedState: S5ChainState = {
    ...state,
    currentStepId: S5_STEP_SEQUENCE[S5_STEP_SEQUENCE.length - 1],
    currentStepIndex: S5_STEP_SEQUENCE.length - 1,
    steps: newSteps,
    modifiedAt: new Date().toISOString(),
    totalDurationMs: totalDuration,
  };

  const displaySteps = updatedState.steps.map(s => {
    const disp = getS5StepDisplay(s.id);
    return { id: s.id, label: disp.label, icon: disp.icon, status: s.status };
  });

  return {
    state: updatedState,
    executedSteps,
    allStepsForDisplay: displaySteps,
    shouldTriggerWorkBuddy: shouldTrigger,
    isComplete: true,
  };
}

// ============================================================
// 3. 主入口：对外暴露的 executeS5
// ============================================================
/**
 * 执行完整的 S5_EXECUTE（即 E1 → E2 → E3）
 *
 * 调用场景：
 *   - S 系列（S3/S4）完成后，需要生成策略代码
 *   - user 直接请求"帮我生成策略代码"
 */
export function executeS5(params: {
  taskId: string;
  sessionId: string;
  userMessage: string;
  thinkingMode: 'quick' | 'deep';
  lang: 'zh' | 'en';
  strategyParams?: {
    symbol?: string;
    timeframe?: string;
    entryRule?: string;
    stopLoss?: string;
    takeProfit?: string;
    positionSize?: string;
  };
}): S5ExecutionResult {
  const ctx: S5ExecutionContext = {
    taskId: params.taskId,
    sessionId: params.sessionId,
    userMessage: params.userMessage,
    thinkingMode: params.thinkingMode,
    lang: params.lang,
    strategyParams: params.strategyParams,
  };

  const state = initS5Chain(ctx);
  const result = advanceS5Chain(state, ctx);

  // 合并 Markdown：S5 头部 + E1→E2→E3 步骤内容
  const isZh = params.lang === 'zh';
  // 安全：对用户输入做 HTML 转义，防止 XSS
  const safeUserMessage = params.userMessage
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
  let content = `🚀 **S5 执行：策略代码开发（完整 E 链）**\n\n`;
  content += isZh ? `**任务**：${safeUserMessage}\n` : `**Task**: ${safeUserMessage}\n`;
  content += isZh ? `**执行链**：` : `**Chain**: `;
  content += result.allStepsForDisplay.map(s => `${s.icon}${s.label}`).join(' → ');
  content += `\n\n---\n\n`;

  for (const step of result.executedSteps) {
    content += step.output + '\n\n---\n\n';
  }

  content += isZh ? `✅ **策略代码开发完成**\n\n` : `✅ **Strategy code development complete**\n\n`;
  content += isZh ? `⏱️ 预估耗时：约 ${Math.round(S5_ESTIMATED_TOTAL_MS / 1000)} 秒\n` : `⏱️ Estimated: ~${Math.round(S5_ESTIMATED_TOTAL_MS / 1000)}s\n`;
  if (result.shouldTriggerWorkBuddy) {
    content += isZh ? `🔧 后端 WorkBuddy 将异步执行实际的代码生成与部署...\n` : `🔧 Backend WorkBuddy will execute actual code generation & deployment...\n`;
  }

  return {
    content,
    allStepsForDisplay: result.allStepsForDisplay,
    shouldTriggerWorkBuddy: result.shouldTriggerWorkBuddy,
    estimatedMs: S5_ESTIMATED_TOTAL_MS,
    isComplete: result.isComplete,
    scopeDescription: safeUserMessage,
  };
}

// ============================================================
// 4. 生成 Markdown 摘要（可选）
// ============================================================
export function renderS5Summary(
  state: S5ChainState,
  lang: 'zh' | 'en',
): string {
  const isZh = lang === 'zh';
  const lines: string[] = [];

  // 安全：对用户输入做 HTML 转义
  const esc = (s: string) =>
    s.replace(/&/g, '&amp;')
     .replace(/</g, '&lt;')
     .replace(/>/g, '&gt;')
     .replace(/"/g, '&quot;')
     .replace(/'/g, '&#39;');

  const safeScope = esc(state.scopeDescription || '');
  const safeStepCount = state.steps.length;
  const safeCurrent = state.currentStepIndex + 1;

  lines.push(isZh ? `## 🚀 S5 策略代码开发进度` : `## 🚀 S5 Strategy Code Development Progress`);
  lines.push('');
  lines.push(isZh ? `**任务描述**：${safeScope}` : `**Description**: ${safeScope}`);
  lines.push(isZh ? `**进度**：${safeCurrent} / ${safeStepCount} 步骤` : `**Progress**: ${safeCurrent} / ${safeStepCount} steps`);
  lines.push('');

  for (const step of state.steps) {
    const disp = getS5StepDisplay(step.id);
    const icon = step.status === 'done' ? '✅' : step.status === 'active' ? '🔵' : '⬜';
    lines.push(`${icon} **${disp.icon} ${disp.label}** — ${disp.description}`);
  }

  return lines.join('\n');
}
