/**
 * 双维度编排架构 - 统一导出
 *
 * 位置: 6-图结构上下文压缩/planner/index.ts
 *
 * 导出所有核心类型和类
 */

// ============================================================
// 类型导出
// ============================================================

// 技能类型
export {
  type SkillChain,
  type SkillCategory,
  type ThinkStage,
  type TradeDirection,
  type SkillInput,
  type SkillOutput,
  type SkillTrigger,
  type SkillMetadata,
  type SkillCapability,
  type ExecutionContext,
  type ChainWeights,
  type UserPreferences,
  type SkillResult,
  type SkillOutputs,
  type ConfidenceDimensions,
  type SkillStatus,
  type SkillRecommendation,
  type SkillQueryParams,
  type SkillInvocation,
  createDefaultContext,
  createSuccessResult,
  createFailureResult,
  createFallbackResult,
} from './skill-types.ts';

// 步骤类型
export {
  type ThinkingStepDefinition,
  type ConfidenceThresholds,
  type StepStatus,
  type StepDecision,
  type GapType,
  type Gap,
  type SkillCallRecord,
  type IterationLogEntry,
  type CrossChainReference,
  type StepExecutionResult,
  S_CHAIN_STEPS,
  C_CHAIN_STEPS,
  F_CHAIN_STEPS,
  getStepDefinition,
  getStepsByChain,
  getAllSteps,
  getStepsByStage,
  shouldProceed,
  shouldIterate,
  shouldWarn,
  getDecision,
} from './step-types.ts';

// 规划器类型
export {
  type IntentType,
  type ComplexityLevel,
  type PriorHistory,
  type PlannerContext,
  type PlannerConstraints,
  type PlannedStep,
  type PlannedSkillCall,
  type InvocationMode,
  type PlannedCrossValidation,
  type CrossValidationTrigger,
  type CrossValidationFallback,
  type ExecutionPlan,
  type PlannerExecutionResult,
  type CrossValidationResult,
  type ChainSignal,
  type VoteConsensus,
  type VoteDetail,
  type Conflict,
  type PlannerConclusion,
  type NextStep,
  createDefaultPlannerContext,
  inferComplexity,
  inferPrimaryChain,
  calculatePlanCost,
} from './planner-types.ts';

// 交叉验证类型
export {
  type CrossValidationConfig,
  type TriggerCondition,
  type FallbackStrategy,
  type SignalDirection,
  type ChainSignal as CVChainSignal,
  type VoteDetail as CVVoteDetail,
  type AgreementLevel,
  type VoteConsensus as CVVoteConsensus,
  type ConflictType,
  type Conflict as CVConflict,
  type ValidationDecision,
  type DeepDivePlan,
  type CrossValidationNode,
  type VotingConfig,
  DEFAULT_VOTING_CONFIG,
  CROSS_VALIDATION_CONFIGS,
  createEmptyCrossValidationNode,
  shouldTriggerCrossValidation,
  getDirectionLabel,
  getAgreementLevelLabel,
} from './cross-validation-types.ts';

// ============================================================
// 类导出
// ============================================================

export { SkillsRegistry } from './skills-registry.ts';
export { ExecutionPlanner } from './planner.ts';
export { ConfidenceEvaluator } from './confidence-evaluator.ts';
export { SkillSelector } from './skill-selector.ts';
export { VotingCalculator } from './voting-calculator.ts';
export { CrossValidator } from './cross-validator.ts';

// ============================================================
// 单例函数导出
// ============================================================

export { getSkillsRegistry, createSkillsRegistry } from './skills-registry.ts';
export { getConfidenceEvaluator } from './confidence-evaluator.ts';
export { getVotingCalculator } from './voting-calculator.ts';
export { getCrossValidator } from './cross-validator.ts';
export { orchestrate } from './planner.ts';

// 技能注册模块 - 提供 A 系列核心技能注册功能
export {
  registerASeriesSkills,
  initializeSkillsRegistry,
  getSkillsSummary,
  ensureRegistryInitialized,
  A_SERIES_SKILLS,
} from './skills-registry-init.ts';

// C/F 链技能模块
export {
  createC1Skill,
  createC2Skill,
  createC3Skill,
  createC4Skill,
  createC5Skill,
  createF1Skill,
  createF2Skill,
  createF3Skill,
  createF4Skill,
  createF5Skill,
  getAllCSkills,
  getAllFSkills,
  getAllChainSkills,
  getChainSummary,
} from './chains-registry.ts';

// ============================================================
// 工具函数
// ============================================================

import { createSuccessResult, createFailureResult } from './skill-types.ts';

export const utils = {
  createSuccessResult,
  createFailureResult,
};

export default {
  // 类型
  SkillChain: ['A', 'C', 'F'] as const,
  SkillCategory: [
    'execution',
    'intelligence',
    'governance',
    'research',
    'classic-indicators',
    'classic-strategy',
    'classic-backtest',
    'classic-execution',
    'fundamental-news',
    'fundamental-flow',
    'fundamental-sentiment',
    'fundamental-onchain',
    'fundamental-macro',
  ] as const,
  ThinkStage: ['research', 'analysis', 'design', 'validate', 'execute'] as const,
  TradeDirection: ['long', 'short', 'neutral', 'wait'] as const,
  IntentType: [
    'market_query',
    'deep_analysis',
    'scenario_sim',
    'strategy_verify',
    'execute_trade',
    'risk_alert',
    'simple_qa',
    'system_config',
    'credits_query',
    'artifact_query',
    'command',
  ] as const,
};
