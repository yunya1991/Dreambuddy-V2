/**
 * Skip Gate — 步骤旁路判断（P0）
 * =============================================
 * 用轻量启发式判断「这个步骤对当前问题真的必要吗？」
 * 如果不必要 → 直接跳过，节省 token 和时间。
 *
 * 判断维度（从便宜到昂贵，依次递进）：
 *   1. 关键词/正则匹配（0 cost, 0ms）
 *   2. 意图类型映射（0 cost, 0ms）
 *   3. 上下文长度/质量启发（0 cost, 0ms）
 *   4. [可选] Embedding 相似度（~1 token, 10-50ms）
 *
 * 返回结果：
 *   'execute' → 正常执行（不跳过）
 *   'skip'    → 跳过此步骤，附带跳过原因
 *   'compact'  → 执行但启用精简模式（输出更短，节省 completion tokens）
 */

// ============================================================
// 1. 类型 & 判断结果定义
// ============================================================

export type SkipDecision = 'execute' | 'skip' | 'compact';

export interface SkipJudgment {
  decision: SkipDecision;
  reason: string;           // 中文可读原因，可直接插入报告
  confidence: number;        // 0.0 - 1.0，判断的置信度
  suggestedFallback?: string; // 如果跳过，建议用什么简短内容替代（可选）
}

export interface GateContext {
  userInput: string;           // 用户原始输入
  intent: string;              // 已识别的意图类型
  complexity: 'simple' | 'moderate' | 'complex';
  sessionId: string;
  previousStepOutput?: string; // 已有内容（用于判断是否足够）
  currentStep: StepName;       // 当前要判断的步骤
  symbolsFoundInInput: string[]; // 用户提到的交易对/资产名
}

export type StepName =
  | 'S1_RESEARCH'
  | 'S2_ANALYSIS'
  | 'S3_DESIGN'
  | 'S4_VALIDATE'
  | 'S5_EXECUTE'
  | 'MARKET_DATA'
  | 'RAG_KNOWLEDGE'
  | 'STRATEGY_ENGINE'
  | 'USER_PREFERENCE_MEMORY';

// ============================================================
// 2. 步骤元信息 — 每种步骤的"何时需要"
// ============================================================

interface StepMeta {
  stepName: StepName;
  requiredWhen: string[];      // 满足这些关键词/条件时必须执行
  neverNeededWhen: string[];   // 满足时可以跳过
  intentWhitelist: string[];   // 白名单意图（必须执行）
  intentBlacklist: string[];   // 黑名单意图（通常跳过）
  compactModeSupport: boolean; // 是否支持"精简模式"
  description: string;
}

const STEP_META: Record<StepName, StepMeta> = {
  MARKET_DATA: {
    stepName: 'MARKET_DATA',
    requiredWhen: ['btc', 'eth', 'gold', 'price', '行情', '价格', '美元', '黄金', '当前', '实时', '支撑', '阻力', '点位'],
    neverNeededWhen: ['什么是', '解释一下', '如何', '怎么', '教程', '定义', '概念', 'how to', 'what is', 'define', 'explain'],
    intentWhitelist: ['market_query', 'deep_analysis', 'execute_trade', 'scenario_sim', 'strategy_verify', 'asset_comparison', 'entry_timing', 'exit_timing', 'risk_analysis', 'portfolio_allocation', 'volatility_analysis', 'macro_analysis', 'strategy_recommendation', 'position_sizing', 'dca_strategy', 'sector_rotation', 'triple_chain'],
    intentBlacklist: ['simple_qa', 'concept_explain', 'system_config', 'credits_query'],
    compactModeSupport: true,
    description: 'OKX / Tavily 市场数据获取（~200-800 tokens 输出，但 0 LLM tokens）',
  },

  RAG_KNOWLEDGE: {
    stepName: 'RAG_KNOWLEDGE',
    requiredWhen: [],
    neverNeededWhen: ['hi', '你好', 'hello', 'ping', '帮助', 'help'],
    intentWhitelist: ['deep_analysis', 'strategy_verify', 'scenario_sim', 'execute_trade', 'concept_explain', 'asset_comparison', 'risk_analysis', 'strategy_recommendation', 'portfolio_allocation', 'entry_timing', 'exit_timing', 'macro_analysis', 'volatility_analysis', 'position_sizing', 'dca_strategy', 'triple_chain'],
    intentBlacklist: ['simple_qa', 'credits_query', 'system_config', 'command'],
    compactModeSupport: true,
    description: '知识库向量检索（~50-300 tokens 注入到 prompt）',
  },

  STRATEGY_ENGINE: {
    stepName: 'STRATEGY_ENGINE',
    requiredWhen: ['策略', '回测', '验证', '验证一下', 'strategy', 'backtest', '入场', '止损', '仓位', 'position size'],
    neverNeededWhen: ['什么是', '解释', '概念', 'how', 'what'],
    intentWhitelist: ['execute_trade', 'strategy_verify', 'scenario_sim', 'deep_analysis', 'entry_timing', 'exit_timing', 'position_sizing', 'strategy_recommendation', 'portfolio_allocation', 'dca_strategy', 'triple_chain'],
    intentBlacklist: ['simple_qa', 'concept_explain', 'market_query', 'credits_query', 'system_config'],
    compactModeSupport: true,
    description: 'Python 策略回测引擎（0 LLM tokens，但有 HTTP 开销）',
  },

  S1_RESEARCH: {
    stepName: 'S1_RESEARCH',
    requiredWhen: [],
    neverNeededWhen: [],
    intentWhitelist: ['deep_analysis', 'execute_trade', 'scenario_sim', 'strategy_verify', 'triple_chain', 'asset_comparison', 'entry_timing', 'exit_timing', 'portfolio_allocation', 'strategy_recommendation'],
    intentBlacklist: ['simple_qa', 'concept_explain', 'system_config', 'credits_query', 'risk_alert_response', 'artifact_query', 'command'],
    compactModeSupport: true,
    description: 'S1 调研（通常 500-1500 tokens LLM 输出）',
  },

  S2_ANALYSIS: {
    stepName: 'S2_ANALYSIS',
    requiredWhen: [],
    neverNeededWhen: [],
    intentWhitelist: ['deep_analysis', 'execute_trade', 'scenario_sim', 'strategy_verify', 'triple_chain', 'asset_comparison', 'entry_timing', 'exit_timing', 'risk_analysis', 'portfolio_allocation', 'strategy_recommendation'],
    intentBlacklist: ['simple_qa', 'concept_explain', 'market_query', 'system_config', 'credits_query'],
    compactModeSupport: true,
    description: 'S2 分析（通常 500-1500 tokens LLM 输出）',
  },

  S3_DESIGN: {
    stepName: 'S3_DESIGN',
    requiredWhen: [],
    neverNeededWhen: [],
    intentWhitelist: ['deep_analysis', 'execute_trade', 'scenario_sim', 'strategy_verify', 'triple_chain', 'entry_timing', 'exit_timing', 'portfolio_allocation', 'strategy_recommendation', 'position_sizing'],
    intentBlacklist: ['simple_qa', 'concept_explain', 'market_query', 'system_config', 'credits_query', 'asset_comparison'],
    compactModeSupport: true,
    description: 'S3 策略设计（通常 500-1500 tokens LLM 输出）',
  },

  S4_VALIDATE: {
    stepName: 'S4_VALIDATE',
    requiredWhen: ['验证', '回测', '检查策略', '风险评估'],
    neverNeededWhen: [],
    intentWhitelist: ['execute_trade', 'strategy_verify', 'deep_analysis', 'scenario_sim', 'triple_chain', 'risk_analysis'],
    intentBlacklist: ['simple_qa', 'concept_explain', 'market_query', 'system_config', 'credits_query', 'asset_comparison', 'entry_timing', 'exit_timing'],
    compactModeSupport: true,
    description: 'S4 验证（最昂贵步骤之一，含 Python 桥接）',
  },

  S5_EXECUTE: {
    stepName: 'S5_EXECUTE',
    requiredWhen: ['开仓', '买入', '卖出', '执行', '入场', 'execute', 'open'],
    neverNeededWhen: [],
    intentWhitelist: ['execute_trade', 'entry_timing', 'exit_timing', 'triple_chain'],
    intentBlacklist: ['simple_qa', 'concept_explain', 'market_query', 'deep_analysis', 'strategy_verify', 'scenario_sim', 'system_config', 'credits_query'],
    compactModeSupport: true,
    description: 'S5 执行（仅真正需要交易操作时启用）',
  },

  USER_PREFERENCE_MEMORY: {
    stepName: 'USER_PREFERENCE_MEMORY',
    requiredWhen: [],
    neverNeededWhen: [],
    intentWhitelist: ['execute_trade', 'strategy_recommendation', 'portfolio_allocation', 'dca_strategy', 'triple_chain'],
    intentBlacklist: ['simple_qa', 'concept_explain', 'market_query', 'system_config', 'credits_query', 'risk_alert_response'],
    compactModeSupport: false,
    description: '用户偏好记忆注入（~100 tokens，非常便宜，但仅个性化场景有用）',
  },
};

// ============================================================
// 3. 辅助函数 — 关键词检测
// ============================================================

function hasAnyKeyword(input: string, keywords: string[]): boolean {
  const lower = input.toLowerCase();
  for (const kw of keywords) {
    if (lower.includes(kw.toLowerCase())) return true;
  }
  return false;
}

function extractSymbols(input: string): string[] {
  const symbols: string[] = [];
  const common = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ORDI', 'GOLD', 'XAU', '黄金', '美元', 'USDT'];
  const lower = input.toLowerCase();
  for (const s of common) {
    if (lower.includes(s.toLowerCase())) symbols.push(s);
  }
  return symbols;
}

// ============================================================
// 4. 核心判断逻辑
// ============================================================

/**
 * 对某个步骤做"是否需要执行"的判断。
 *
 * 判定优先级（从强到弱）：
 *   1. 意图白名单/黑名单（最强信号）
 *   2. requiredWhen 关键词（用户明确问了相关内容）
 *   3. neverNeededWhen 关键词（用户问的是概念/教程类）
 *   4. complexity 等级（simple 倾向精简）
 *   5. 已有上下文长度（如果前面步骤已经内容丰富，后续可 compact）
 */
export function judgeStep(ctx: GateContext): SkipJudgment {
  const meta = STEP_META[ctx.currentStep];
  if (!meta) {
    return { decision: 'execute', reason: '步骤未注册到 Skip Gate，默认执行', confidence: 0.3 };
  }

  const userInputLower = ctx.userInput.toLowerCase();
  const symbols = ctx.symbolsFoundInInput.length > 0
    ? ctx.symbolsFoundInInput
    : extractSymbols(ctx.userInput);

  // ---------- 强信号 1: 意图黑名单（直接跳过）
  if (meta.intentBlacklist.includes(ctx.intent)) {
    return {
      decision: 'skip',
      reason: `意图 '${ctx.intent}' 在 ${ctx.currentStep} 的黑名单中 — 此类问题无需执行此步骤`,
      confidence: 0.85,
      suggestedFallback: buildFallbackForStep(ctx.currentStep, ctx.intent),
    };
  }

  // ---------- 强信号 2: requiredWhen 关键词（必须执行）
  if (hasAnyKeyword(ctx.userInput, meta.requiredWhen) && meta.requiredWhen.length > 0) {
    return {
      decision: 'execute',
      reason: `用户输入命中关键词 (${meta.requiredWhen.filter(kw => hasAnyKeyword(ctx.userInput, [kw])).slice(0, 3).join(', ')})`,
      confidence: 0.8,
    };
  }

  // ---------- 强信号 3: neverNeededWhen 关键词（跳过）
  // 仅在用户明显是"概念查询/教学"时适用
  if (hasAnyKeyword(ctx.userInput, meta.neverNeededWhen) && meta.neverNeededWhen.length > 0) {
    // 但如果同时命中 requiredWhen，则仍要执行（例如"什么是BTC的当前价格"）
    if (!hasAnyKeyword(ctx.userInput, STEP_META.MARKET_DATA.requiredWhen)) {
      return {
        decision: 'skip',
        reason: `判断为"概念查询/教学类"问题，不需要 ${ctx.currentStep} 的实时或结构化分析`,
        confidence: 0.7,
        suggestedFallback: buildFallbackForStep(ctx.currentStep, ctx.intent),
      };
    }
  }

  // ---------- 中等信号: complexity 等级
  // simple 复杂度 — 尽可能用 compact 模式或跳过非关键步骤
  if (ctx.complexity === 'simple') {
    // 对 simple 意图，如果不在白名单中明确列出，给 compact 或 skip
    if (!meta.intentWhitelist.includes(ctx.intent)) {
      return {
        decision: 'skip',
        reason: `simple 复杂度问题，且意图 '${ctx.intent}' 未在 ${ctx.currentStep} 白名单中 — 精简路径`,
        confidence: 0.6,
        suggestedFallback: buildFallbackForStep(ctx.currentStep, ctx.intent),
      };
    }
    // 白名单中的 simple 类请求，用 compact 模式（而不是全量执行）
    if (meta.compactModeSupport) {
      return {
        decision: 'compact',
        reason: `simple 复杂度问题，启用精简模式（输出长度减半）`,
        confidence: 0.55,
      };
    }
  }

  // ---------- 中等信号: moderate 且前面已输出大量内容 → 后续步骤用 compact
  if (ctx.complexity === 'moderate' && ctx.previousStepOutput) {
    const prevLen = ctx.previousStepOutput.length;
    if (prevLen > 2000 && meta.compactModeSupport) {
      return {
        decision: 'compact',
        reason: `前面步骤已有 ${prevLen} chars 输出，当前步骤切换为精简模式`,
        confidence: 0.5,
      };
    }
  }

  // ---------- 启发信号: 用户没提到任何具体资产 → 跳过 MARKET_DATA 和 STRATEGY_ENGINE
  if (symbols.length === 0 && (ctx.currentStep === 'MARKET_DATA' || ctx.currentStep === 'STRATEGY_ENGINE')) {
    return {
      decision: 'skip',
      reason: `用户输入未提到任何具体资产（BTC/ETH/黄金等），无需获取实时行情或回测`,
      confidence: 0.75,
      suggestedFallback: '（无具体资产 → 跳过行情数据 / 策略引擎）',
    };
  }

  // ---------- 默认: 正常执行
  return {
    decision: 'execute',
    reason: `${ctx.currentStep} — 无明确跳过信号，正常执行`,
    confidence: 0.4,
  };
}

// ============================================================
// 5. 生成跳过步骤时的"简短替代内容"（保持输出连贯）
// ============================================================

function buildFallbackForStep(step: StepName, intent: string): string {
  switch (step) {
    case 'MARKET_DATA':
      return `（未获取实时行情 — 此问题不涉及具体资产的实时价格）`;
    case 'RAG_KNOWLEDGE':
      return `（未检索知识库 — 此问题属于通用问答，基于已有方法论框架即可回答）`;
    case 'STRATEGY_ENGINE':
      return `（未执行策略回测 — 此问题暂不需要回测验证）`;
    case 'S1_RESEARCH':
    case 'S2_ANALYSIS':
    case 'S3_DESIGN':
      return `（${step}：基于输入复杂度判断可跳过，直接给出结论）`;
    case 'S4_VALIDATE':
      return `（S4 验证：暂跳过 — 当前问题不需要回测验证）`;
    case 'S5_EXECUTE':
      return `（S5 执行：暂跳过 — 用户未请求实际交易操作）`;
    case 'USER_PREFERENCE_MEMORY':
      return `（用户偏好暂不注入 — 非个性化交易决策场景）`;
    default:
      return `（${step}：已跳过）`;
  }
}

// ============================================================
// 6. 便捷 API — 一次性判断多个步骤（批量）
// ============================================================

export interface BatchJudgeResult {
  judgments: Record<StepName, SkipJudgment>;
  summary: string;           // 一句话汇总（用于日志）
  executeCount: number;
  skipCount: number;
  compactCount: number;
}

/**
 * 对所有步骤一次性执行判断（便于提前规划执行路径）
 */
export function judgeAllSteps(
  userInput: string,
  intent: string,
  complexity: 'simple' | 'moderate' | 'complex',
  sessionId: string,
  previousOutput: string = ''
): BatchJudgeResult {
  const allSteps: StepName[] = [
    'MARKET_DATA', 'RAG_KNOWLEDGE', 'USER_PREFERENCE_MEMORY',
    'S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN',
    'S4_VALIDATE', 'STRATEGY_ENGINE', 'S5_EXECUTE',
  ];

  const symbols = extractSymbols(userInput);
  const judgments = {} as Record<StepName, SkipJudgment>;

  let executeCount = 0, skipCount = 0, compactCount = 0;

  for (const step of allSteps) {
    const judgment = judgeStep({
      userInput,
      intent,
      complexity,
      sessionId,
      previousStepOutput: previousOutput,
      currentStep: step,
      symbolsFoundInInput: symbols,
    });
    judgments[step] = judgment;
    if (judgment.decision === 'execute') executeCount++;
    if (judgment.decision === 'skip') skipCount++;
    if (judgment.decision === 'compact') compactCount++;
  }

  const summary = `[SkipGate] 执行: ${executeCount}, 跳过: ${skipCount}, 精简: ${compactCount} | intent=${intent}, complexity=${complexity}, assets=[${symbols.join(',') || 'none'}]`;

  return { judgments, summary, executeCount, skipCount, compactCount };
}

// ============================================================
// 7. 对外导出 — 便捷函数
// ============================================================

/**
 * 简单判断 — 对单个步骤快速给出 yes/no
 * 适合在 route.ts 的循环内调用。
 */
export function shouldSkipStep(
  step: StepName,
  userInput: string,
  intent: string,
  complexity: 'simple' | 'moderate' | 'complex'
): { skip: boolean; reason: string; mode: 'full' | 'compact' } {
  const symbols = extractSymbols(userInput);
  const judgment = judgeStep({
    userInput,
    intent,
    complexity,
    sessionId: 'inline',
    currentStep: step,
    symbolsFoundInInput: symbols,
  });

  return {
    skip: judgment.decision === 'skip',
    reason: judgment.reason,
    mode: judgment.decision === 'compact' ? 'compact' : 'full',
  };
}
