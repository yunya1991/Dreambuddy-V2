/**
 * Cost Keeper — 成本控制器（P0）
 * =============================================
 * 追踪每次请求的 Token 用量，判断是否需要提前终止。
 *
 * 设计原则：
 *   1. 低侵入：作为单例存在，不破坏现有接口签名
 *   2. 可观测：每个请求生成一份结构化报告，记录每步的 token 用量
 *   3. 可回滚：通过 Feature Flag 一键关闭，不影响既有逻辑
 *
 * 接入点：callDeepSeekAPI 调用前后记录 token 用量
 */

// ============================================================
// 1. 类型定义
// ============================================================

export interface StepTokenRecord {
  stepId: string;                 // 步骤 ID（如 S1_RESEARCH, callLLMStep.S2）
  stepName: string;               // 可读名称
  promptTokens: number;           // 输入 tokens
  completionTokens: number;       // 输出 tokens
  totalTokens: number;            // 合计
  latencyMs: number;              // 耗时（毫秒）
  skippedByGate: boolean;         // 是否被 Skip Gate 跳过
  skipReason?: string;            // 跳过的原因（若被跳过）
  moduleType: 'llm' | 'market' | 'rag' | 'strategy_engine' | 'other';
}

export interface CostKeeperReport {
  sessionId: string;
  intent: string;                 // 用户意图（便于分类分析）
  complexity: string;             // simple/moderate/complex
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalTokens: number;
  totalLatencyMs: number;
  steps: StepTokenRecord[];
  skippedSteps: string[];         // 被 Skip Gate 跳过的步骤
  reachedBudgetLimit: boolean;    // 是否触发了预算上限
  budgetTokens: number;           // 设定的预算
  createdAt: number;              // 创建时间
}

export interface CostKeeperConfig {
  enabled: boolean;               // 总开关（Feature Flag）
  defaultBudgetTokens: number;    // 默认预算（每请求）
  budgetsByComplexity?: {         // 不同复杂度的预算（可覆盖默认值）
    simple?: number;
    moderate?: number;
    complex?: number;
  };
  logLevel: 'silent' | 'summary' | 'verbose'; // 日志级别
}

// ============================================================
// 2. 默认配置
// ============================================================

const DEFAULT_CONFIG: CostKeeperConfig = {
  enabled: true,
  defaultBudgetTokens: 5000,
  budgetsByComplexity: {
    simple: 1200,        // 简单问答：~1次 LLM 调用
    moderate: 3500,      // 中等分析：~2-3 次 LLM 调用
    complex: 8000,       // 完整交易分析：S1-S5 全链路
  },
  logLevel: 'summary',
};

// ============================================================
// 3. 全局状态（单例 per session）
// ============================================================

// 用 WeakMap 保存 session 级状态，便于 GC 回收
const sessionStates = new Map<string, SessionCostState>();

interface SessionCostState {
  config: CostKeeperConfig;
  intent: string;
  complexity: 'simple' | 'moderate' | 'complex';
  steps: StepTokenRecord[];
  skippedSteps: string[];
  currentStepId: string | null;
  currentStepStart: number;
  totalTokens: number;
  budgetTokens: number;
  terminated: boolean;           // 是否因预算耗尽终止
  createdAt: number;
}

// ============================================================
// 4. 核心 API
// ============================================================

/**
 * 初始化一个请求的成本追踪。必须在每个请求开始时调用。
 * @param sessionId 会话唯一标识（用于隔离不同用户/请求）
 * @param intent  意图类型（如 market_query, deep_analysis）
 * @param complexity  复杂度等级
 * @param customConfig  可选的自定义配置（覆盖默认）
 */
export function initCostKeeper(
  sessionId: string,
  intent: string,
  complexity: 'simple' | 'moderate' | 'complex' = 'moderate',
  customConfig?: Partial<CostKeeperConfig>
): CostKeeperConfig {
  const config: CostKeeperConfig = {
    ...DEFAULT_CONFIG,
    ...customConfig,
  };

  // 读取环境变量中的 Feature Flag（可在部署时覆盖）
  if (typeof process !== 'undefined') {
    const envFlag = process.env.USE_SCHEDULER;
    if (envFlag === 'false' || envFlag === '0') config.enabled = false;
    if (envFlag === 'true' || envFlag === '1') config.enabled = true;

    const budget = process.env.SCHEDULER_BUDGET_TOKENS;
    if (budget && !isNaN(parseInt(budget))) {
      config.defaultBudgetTokens = parseInt(budget);
    }
  }

  const budget = config.budgetsByComplexity?.[complexity] ?? config.defaultBudgetTokens;

  sessionStates.set(sessionId, {
    config,
    intent,
    complexity,
    steps: [],
    skippedSteps: [],
    currentStepId: null,
    currentStepStart: 0,
    totalTokens: 0,
    budgetTokens: budget,
    terminated: false,
    createdAt: Date.now(),
  });

  if (config.logLevel !== 'silent') {
    console.log(
      `[CostKeeper] Init session=${sessionId}, intent=${intent}, ` +
      `complexity=${complexity}, budget=${budget} tokens, enabled=${config.enabled}`
    );
  }

  return config;
}

/**
 * 标记一个步骤开始执行（开始计时）
 */
export function markStepStart(sessionId: string, stepId: string, stepName: string): void {
  const state = sessionStates.get(sessionId);
  if (!state || !state.config.enabled) return;

  state.currentStepId = stepId + ':' + stepName;
  state.currentStepStart = Date.now();

  if (state.config.logLevel === 'verbose') {
    console.log(`[CostKeeper] Step start: ${stepId} (${stepName})`);
  }
}

/**
 * 标记一个步骤结束并记录 token 用量
 * @param sessionId 会话
 * @param stepId  步骤 ID
 * @param stepName  可读名称
 * @param tokenUsage  token 用量（从 LLM 返回，或自己估算）
 * @param moduleType  模块类型（llm / market / rag ...）
 */
export function markStepEnd(
  sessionId: string,
  stepId: string,
  stepName: string,
  tokenUsage: { promptTokens: number; completionTokens: number; totalTokens?: number },
  moduleType: StepTokenRecord['moduleType'] = 'llm'
): void {
  const state = sessionStates.get(sessionId);
  if (!state || !state.config.enabled) return;

  const latency = Date.now() - state.currentStepStart;
  const total = tokenUsage.totalTokens ?? tokenUsage.promptTokens + tokenUsage.completionTokens;

  const record: StepTokenRecord = {
    stepId,
    stepName,
    promptTokens: tokenUsage.promptTokens,
    completionTokens: tokenUsage.completionTokens,
    totalTokens: total,
    latencyMs: latency,
    skippedByGate: false,
    moduleType,
  };

  state.steps.push(record);
  state.totalTokens += total;

  if (state.config.logLevel === 'verbose') {
    console.log(
      `[CostKeeper] Step end: ${stepId} | ${total} tokens | ${latency}ms | ` +
      `session total: ${state.totalTokens}/${state.budgetTokens}`
    );
  }

  // 判断是否达到预算上限
  if (state.totalTokens >= state.budgetTokens && !state.terminated) {
    state.terminated = true;
    console.log(
      `[CostKeeper] ⚠ BUDGET EXCEEDED! session=${sessionId}, ` +
      `used=${state.totalTokens}, budget=${state.budgetTokens}`
    );
  }
}

/**
 * 标记一个步骤被 Skip Gate 跳过（不执行任何高成本操作）
 */
export function markStepSkipped(
  sessionId: string,
  stepId: string,
  stepName: string,
  reason: string
): void {
  const state = sessionStates.get(sessionId);
  if (!state || !state.config.enabled) return;

  const record: StepTokenRecord = {
    stepId,
    stepName,
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    latencyMs: 0,
    skippedByGate: true,
    skipReason: reason,
    moduleType: 'other',
  };

  state.steps.push(record);
  state.skippedSteps.push(`${stepId}: ${reason}`);

  if (state.config.logLevel === 'verbose') {
    console.log(`[CostKeeper] Step SKIPPED: ${stepId} (${stepName}) — ${reason}`);
  }
}

/**
 * 判断当前请求是否应该因预算耗尽而提前终止
 */
export function shouldTerminate(sessionId: string): boolean {
  const state = sessionStates.get(sessionId);
  return !!(state && state.terminated);
}

/**
 * 获取当前 token 用量（供调用方做决策）
 */
export function getCurrentUsage(sessionId: string): {
  used: number;
  budget: number;
  percentage: number;
  stepCount: number;
} {
  const state = sessionStates.get(sessionId);
  if (!state) {
    return { used: 0, budget: 0, percentage: 0, stepCount: 0 };
  }
  return {
    used: state.totalTokens,
    budget: state.budgetTokens,
    percentage: Math.round((state.totalTokens / state.budgetTokens) * 100),
    stepCount: state.steps.length,
  };
}

/**
 * 生成请求级报告（用于日志、前端展示、优化分析）
 */
export function generateReport(sessionId: string): CostKeeperReport | null {
  const state = sessionStates.get(sessionId);
  if (!state) return null;

  const report: CostKeeperReport = {
    sessionId,
    intent: state.intent,
    complexity: state.complexity,
    totalPromptTokens: state.steps.reduce((sum, s) => sum + s.promptTokens, 0),
    totalCompletionTokens: state.steps.reduce((sum, s) => sum + s.completionTokens, 0),
    totalTokens: state.totalTokens,
    totalLatencyMs: state.steps.reduce((sum, s) => sum + s.latencyMs, 0),
    steps: state.steps,
    skippedSteps: state.skippedSteps,
    reachedBudgetLimit: state.terminated,
    budgetTokens: state.budgetTokens,
    createdAt: state.createdAt,
  };

  if (state.config.logLevel !== 'silent') {
    console.log(
      `[CostKeeper] Report: ${state.intent}/${state.complexity} | ` +
      `${report.totalTokens}/${report.budgetTokens} tokens | ` +
      `${report.totalLatencyMs}ms | ` +
      `skipped: ${report.skippedSteps.length} steps`
    );

    if (state.config.logLevel === 'verbose') {
      report.steps.forEach(s => {
        const prefix = s.skippedByGate ? '  🚫 SKIP' : '  ✅ DONE';
        console.log(
          `${prefix} | ${s.stepId} | ${s.totalTokens} tokens | ${s.latencyMs}ms` +
          (s.skippedByGate && s.skipReason ? ` — ${s.skipReason}` : '')
        );
      });
    }
  }

  return report;
}

/**
 * 清理会话状态（请求结束时必须调用，防止内存泄漏）
 */
export function cleanupSession(sessionId: string): void {
  sessionStates.delete(sessionId);
}

/**
 * 估算一段文本的 token 数量（粗略但实用 — 无需 tiktoken）
 * 规则: 英文 ≈ 4 chars/token，中文 ≈ 2 chars/token
 * 用于没有 LLM 返回 usage 信息时的兜底估算
 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  let chineseChars = 0;
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code >= 0x4e00 && code <= 0x9fff) chineseChars++;
  }
  const asciiChars = text.length - chineseChars;
  // 中文字符 ≈ 2 chars/token，英文 ≈ 4 chars/token
  return Math.ceil(chineseChars / 2) + Math.ceil(asciiChars / 4);
}

/**
 * 全局诊断：返回所有活跃会话的状态汇总
 */
export function getGlobalSummary(): {
  activeSessions: number;
  totalTokensAcrossSessions: number;
} {
  let totalTokens = 0;
  sessionStates.forEach((state) => { totalTokens += state.totalTokens; });
  return {
    activeSessions: sessionStates.size,
    totalTokensAcrossSessions: totalTokens,
  };
}

export function getSessionCount(): number {
  return sessionStates.size;
}
