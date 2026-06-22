/**
 * 执行规划器接口 - AI 推理的核心调度器
 *
 * 位置: 6-图结构上下文压缩/planner/planner-types.ts
 *
 * 核心理念: 根据用户请求，动态生成执行计划，然后逐步执行
 */

import { SkillChain, SkillResult, ExecutionContext } from './skill-types.ts';
import { ThinkingStepDefinition, StepExecutionResult } from './step-types.ts';

// ============================================================
// 规划上下文
// ============================================================

/** 用户意图类型 */
export type IntentType =
  | 'market_query'      // 行情查询
  | 'deep_analysis'      // 深度分析
  | 'scenario_sim'       // 情景模拟
  | 'strategy_verify'    // 策略验证
  | 'execute_trade'      // 执行交易
  | 'risk_alert'         // 风险告警
  | 'simple_qa'          // 简单问答
  | 'system_config'      // 系统配置
  | 'credits_query'      // 积分查询
  | 'artifact_query'      // 知识查询
  | 'command';           // 命令

/** 复杂度级别 */
export type ComplexityLevel = 'quick' | 'standard' | 'deep';

/** 历史上下文 */
export interface PriorHistory {
  /** 之前的步骤结果 */
  previousSteps?: StepExecutionResult[];

  /** 之前的结论 */
  previousConclusions?: string[];

  /** 之前的置信度 */
  previousConfidences?: number[];

  /** 历史对话摘要 */
  summary?: string;
}

/**
 * 规划上下文
 * 用于生成执行计划的输入
 */
export interface PlannerContext {
  /** 会话 ID */
  sessionId: string;

  /** 用户的自然语言请求 */
  userRequest: string;

  /** 识别的意图类型 */
  intent: IntentType;

  /** 复杂度级别 */
  complexity: ComplexityLevel;

  /** 交易标的 */
  symbol?: string;

  /** 历史上下文 */
  priorHistory?: PriorHistory;

  /** 用户偏好 */
  userPreferences?: ExecutionContext['userPreferences'];

  /** 交易模式 */
  tradingMode: 'ai_skill' | 'classic' | 'hybrid';

  /** 约束条件 */
  constraints?: PlannerConstraints;

  /** 动态权重 */
  chainWeights: {
    s_chain: number;
    c_chain: number;
    f_chain: number;
  };
}

/** 规划约束 */
export interface PlannerConstraints {
  /** 最大 token 预算 */
  maxTokens?: number;

  /** 最大延迟（毫秒） */
  maxLatencyMs?: number;

  /** 最大步骤数 */
  maxSteps?: number;

  /** 强制使用的链 */
  forcedChains?: SkillChain[];

  /** 禁止使用的技能 */
  bannedSkills?: string[];

  /** 强制使用的技能 */
  requiredSkills?: string[];
}

// ============================================================
// 执行计划
// ============================================================

/** 调用模式 */
export type InvocationMode = 'parallel' | 'sequential';

/**
 * 计划的单个步骤
 */
export interface PlannedStep {
  /** 步骤 ID */
  stepId: string;

  /** 所属链 */
  chain: SkillChain;

  /** 思维阶段 */
  stage: string;

  /** 调用的技能 */
  selectedSkills: PlannedSkillCall[];

  /** 预期置信度 */
  expectedConfidence: number;

  /** 可接受的最低置信度 */
  acceptableMinConfidence: number;

  /** 是否允许迭代 */
  allowIteration: boolean;

  /** 最大迭代次数 */
  maxIterations: number;

  /** 步骤定义（运行时填充） */
  definition?: ThinkingStepDefinition;
}

/**
 * 计划的技能调用
 */
export interface PlannedSkillCall {
  /** 技能 ID */
  skillId: string;

  /** 优先级 (1=最高) */
  priority: number;

  /** 调用模式 */
  invocationMode: InvocationMode;

  /** 依赖的技能 ID（串行时） */
  dependsOn?: string[];

  /** 预估 token 消耗 */
  estimatedTokens: number;

  /** 预估延迟 */
  estimatedLatencyMs: number;
}

/**
 * 计划的交叉验证节点
 */
export interface PlannedCrossValidation {
  /** 节点 ID */
  nodeId: string;

  /** 在哪个步骤后进行 */
  afterStep: string;

  /** 参与的链 */
  participatingChains: SkillChain[];

  /** 投票权重 */
  weights: {
    s_chain: number;
    c_chain: number;
    f_chain: number;
  };

  /** 触发条件 */
  triggerCondition: CrossValidationTrigger;

  /** 降级策略 */
  fallback: CrossValidationFallback;
}

/** 交叉验证触发条件 */
export interface CrossValidationTrigger {
  /** 触发类型 */
  type: 'always' | 'on_conflict' | 'on_low_confidence';

  /** 阈值（低于此置信度触发） */
  threshold?: number;
}

/** 交叉验证降级策略 */
export interface CrossValidationFallback {
  /** 降级类型 */
  type: 'majority_vote' | 'highest_confidence' | 'weighted_average' | 'manual_override';

  /** 是否需要用户确认 */
  requireUserConfirmation?: boolean;
}

/**
 * 执行计划
 */
export interface ExecutionPlan {
  /** 计划 ID */
  planId: string;

  /** 创建时间 */
  createdAt: number;

  /** 计划的思维步骤序列 */
  steps: PlannedStep[];

  /** 成本预估 */
  estimatedTokens: number;

  /** 延迟预估 */
  estimatedLatencyMs: number;

  /** 交叉验证节点 */
  crossValidationNodes: PlannedCrossValidation[];

  /** 降级计划 */
  fallbackPlan?: ExecutionPlan;

  /** 计划元信息 */
  metadata?: {
    intent: IntentType;
    complexity: ComplexityLevel;
    chains: SkillChain[];
    primaryChain: SkillChain;
  };
}

// ============================================================
// 规划结果
// ============================================================

/**
 * 规划执行结果
 */
export interface PlannerExecutionResult {
  /** 是否成功 */
  success: boolean;

  /** 计划 ID */
  planId: string;

  /** 执行的步骤结果 */
  steps: StepExecutionResult[];

  /** 交叉验证节点结果 */
  crossValidationResults?: CrossValidationResult[];

  /** 总 token 消耗 */
  totalTokensUsed: number;

  /** 总延迟（毫秒） */
  totalLatencyMs: number;

  /** 总体置信度 */
  overallConfidence: number;

  /** 最终结论 */
  conclusion?: PlannerConclusion;

  /** 错误信息 */
  error?: string;

  /** 警告信息 */
  warnings?: string[];
}

/**
 * 交叉验证结果
 */
export interface CrossValidationResult {
  /** 节点 ID */
  nodeId: string;

  /** 各链信号 */
  signals: ChainSignal[];

  /** 投票结果 */
  consensus: VoteConsensus;

  /** 冲突列表 */
  conflicts?: Conflict[];

  /** 决策建议 */
  recommendedAction: 'proceed' | 'deep_dive' | 'pause' | 'override';

  /** 深入分析计划 */
  deepDivePlan?: {
    additionalSkills: string[];
    expectedImprovement: number;
    estimatedExtraCost: number;
  };
}

/** 链信号 */
export interface ChainSignal {
  chain: SkillChain;
  direction: 'long' | 'short' | 'neutral' | 'wait';
  confidence: number;
  reasoning: string;
  sourceSteps: string[];
}

/** 投票共识 */
export interface VoteConsensus {
  direction: 'long' | 'short' | 'neutral' | 'wait';
  overallConfidence: number;
  agreementLevel: 'strong' | 'moderate' | 'weak' | 'conflict';
  votes: VoteDetail[];
}

/** 投票详情 */
export interface VoteDetail {
  chain: SkillChain;
  weight: number;
  rawConfidence: number;
  weightedContribution: number;
}

/** 冲突 */
export interface Conflict {
  type: 'direction_conflict' | 'confidence_gap' | 'reasoning_inconsistency';
  involvedChains: SkillChain[];
  description: string;
  resolution?: string;
}

/**
 * 规划器结论
 */
export interface PlannerConclusion {
  /** 交易方向 */
  direction: 'long' | 'short' | 'neutral' | 'wait';

  /** 置信度 */
  confidence: number;

  /** 参与决策的链 */
  participatingChains: SkillChain[];

  /** 关键决策点 */
  keyDecisionPoints: string[];

  /** 推理路径 */
  reasoningPath: string[];

  /** 下一步建议 */
  nextSteps: NextStep[];
}

/** 下一步建议 */
export interface NextStep {
  action: 'EXECUTE' | 'MONITOR' | 'WAIT_FOR_SIGNAL' | 'REVISE_PLAN' | 'ASK_USER';
  reasoning: string;
  triggerConditions?: string[];
  estimatedConfidence?: number;
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 创建默认规划上下文
 */
export function createDefaultPlannerContext(
  sessionId: string,
  userRequest: string,
  intent: IntentType = 'deep_analysis'
): PlannerContext {
  return {
    sessionId,
    userRequest,
    intent,
    complexity: intent === 'simple_qa' ? 'quick' : intent === 'execute_trade' ? 'deep' : 'standard',
    tradingMode: 'hybrid',
    chainWeights: {
      s_chain: 0.35,
      c_chain: 0.45,
      f_chain: 0.20,
    },
  };
}

/**
 * 根据意图推断复杂度
 */
export function inferComplexity(intent: IntentType): ComplexityLevel {
  switch (intent) {
    case 'simple_qa':
    case 'market_query':
    case 'credits_query':
    case 'artifact_query':
      return 'quick';
    case 'risk_alert':
    case 'system_config':
    case 'strategy_verify':
    case 'scenario_sim':
      return 'standard';
    case 'deep_analysis':
    case 'execute_trade':
    case 'command':
      return 'deep';
    default:
      return 'standard';
  }
}

/**
 * 根据意图推断主要使用的链
 */
export function inferPrimaryChain(intent: IntentType, tradingMode: string): SkillChain {
  if (tradingMode === 'classic') return 'C';
  if (tradingMode === 'fundamental') return 'F';
  // hybrid 模式根据 intent 决定主链
  if (tradingMode === 'hybrid') {
    if (intent === 'deep_analysis' || intent === 'strategy_verify') return 'F';
    return 'S';
  }
  // ai_skill 或默认：deep_analysis 倾向 F 链（基本面驱动），其余走 S 链
  if (intent === 'deep_analysis' || intent === 'strategy_verify') return 'F';
  return 'S';
}

/**
 * 计算计划的总成本
 */
export function calculatePlanCost(steps: PlannedStep[]): { tokens: number; latencyMs: number } {
  let tokens = 0;
  let latencyMs = 0;

  for (const step of steps) {
    for (const skill of step.selectedSkills) {
      tokens += skill.estimatedTokens;
      if (skill.invocationMode === 'parallel') {
        latencyMs = Math.max(latencyMs, skill.estimatedLatencyMs);
      } else {
        latencyMs += skill.estimatedLatencyMs;
      }
    }
  }

  return { tokens, latencyMs };
}
