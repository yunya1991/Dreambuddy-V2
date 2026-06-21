/**
 * 交叉验证接口 - 三链投票机制
 *
 * 位置: 6-图结构上下文压缩/planner/cross-validation-types.ts
 *
 * 核心理念: S/C/F 三链在关键节点做交叉验证
 * 多源印证 → 高置信度 / 链间冲突 → 深入分析
 */

import { SkillChain } from './skill-types';
import { ThinkStage } from './step-types';
import { SerializedNode } from '../types';

// ============================================================
// 交叉验证配置
// ============================================================

/**
 * 交叉验证节点配置
 * 定义在哪些步骤后进行交叉验证
 */
export interface CrossValidationConfig {
  /** 节点 ID */
  nodeId: string;

  /** 在哪个步骤后进行 */
  afterStep: string;

  /** 参与的链 */
  participatingChains: SkillChain[];

  /** 投票权重 */
  weights: ChainWeights;

  /** 触发条件 */
  triggerCondition: TriggerCondition;

  /** 降级策略 */
  fallback: FallbackStrategy;
}

/** 触发条件 */
export interface TriggerCondition {
  /** 触发类型 */
  type: 'always' | 'on_conflict' | 'on_low_confidence';

  /** 阈值 */
  threshold?: number;
}

/** 降级策略 */
export interface FallbackStrategy {
  /** 降级类型 */
  type: 'majority_vote' | 'highest_confidence' | 'weighted_average' | 'manual_override';

  /** 是否需要用户确认 */
  requireUserConfirmation?: boolean;
}

/** 链权重 */
export interface ChainWeights {
  s_chain: number;
  c_chain: number;
  f_chain: number;
}

// ============================================================
// 交叉验证结果
// ============================================================

/**
 * 信号方向
 */
export type SignalDirection = 'long' | 'short' | 'neutral' | 'wait';

/**
 * 链信号
 */
export interface ChainSignal {
  chain: SkillChain;
  direction: SignalDirection;
  confidence: number;
  reasoning: string;
  sourceSteps: string[];
  outputs: Record<string, unknown>;
}

/**
 * 投票详情
 */
export interface VoteDetail {
  chain: SkillChain;
  weight: number;
  rawConfidence: number;
  weightedContribution: number;
}

/**
 * 一致性等级
 */
export type AgreementLevel = 'strong' | 'moderate' | 'weak' | 'conflict';

/**
 * 投票共识
 */
export interface VoteConsensus {
  direction: SignalDirection;
  overallConfidence: number;
  agreementLevel: AgreementLevel;
  votes: VoteDetail[];
}

/**
 * 冲突类型
 */
export type ConflictType = 'direction_conflict' | 'confidence_gap' | 'reasoning_inconsistency';

/**
 * 冲突
 */
export interface Conflict {
  id: string;
  type: ConflictType;
  involvedChains: SkillChain[];
  description: string;
  resolution?: string;
}

/**
 * 决策建议
 */
export type ValidationDecision = 'proceed' | 'deep_dive' | 'pause' | 'override';

/**
 * 深入分析计划
 */
export interface DeepDivePlan {
  additionalSkills: string[];
  expectedImprovement: number;
  estimatedExtraCost: number;
}

/**
 * 交叉验证节点
 */
export interface CrossValidationNode {
  nodeId: string;
  stage: ThinkStage;
  triggeredAt: number;

  /** 各链的信号 */
  signals: ChainSignal[];

  /** 加权投票结果 */
  consensus: VoteConsensus;

  /** 冲突检测 */
  conflicts: Conflict[];

  /** 决策建议 */
  recommendedAction: ValidationDecision;
  recommendationReason: string;

  /** 深入分析计划（如果需要） */
  deepDivePlan?: DeepDivePlan;

  /** 架构节点 */
  architectureNode: SerializedNode;
}

// ============================================================
// 投票配置
// ============================================================

/**
 * 默认投票配置
 */
export const DEFAULT_VOTING_CONFIG: VotingConfig = {
  weights: {
    s_chain: 0.35,
    c_chain: 0.45,
    f_chain: 0.20,
  },
  confidenceThreshold: {
    strong: 80,
    moderate: 60,
    weak: 40,
    conflict: 0,
  },
  directionMapping: {
    long: 1,
    short: -1,
    neutral: 0,
    wait: 0,
  },
};

/**
 * 投票配置
 */
export interface VotingConfig {
  /** 基础权重 */
  weights: ChainWeights;

  /** 置信度门槛 */
  confidenceThreshold: {
    strong: number;
    moderate: number;
    weak: number;
    conflict: number;
  };

  /** 方向映射 */
  directionMapping: {
    long: number;
    short: number;
    neutral: number;
    wait: number;
  };
}

// ============================================================
// 预设的交叉验证节点
// ============================================================

/**
 * 交叉验证节点配置列表
 */
export const CROSS_VALIDATION_CONFIGS: CrossValidationConfig[] = [
  {
    nodeId: 'CV1',
    afterStep: 'S1',
    participatingChains: ['S', 'C', 'F'],
    weights: { s_chain: 0.35, c_chain: 0.45, f_chain: 0.20 },
    triggerCondition: { type: 'always' },
    fallback: { type: 'majority_vote' },
  },
  {
    nodeId: 'CV2',
    afterStep: 'S2',
    participatingChains: ['S', 'C', 'F'],
    weights: { s_chain: 0.35, c_chain: 0.40, f_chain: 0.25 },
    triggerCondition: { type: 'always' },
    fallback: { type: 'weighted_average' },
  },
  {
    nodeId: 'CV3',
    afterStep: 'S3',
    participatingChains: ['S', 'C'],
    weights: { s_chain: 0.40, c_chain: 0.60 },
    triggerCondition: { type: 'on_conflict' },
    fallback: { type: 'highest_confidence', requireUserConfirmation: true },
  },
  {
    nodeId: 'CV4',
    afterStep: 'S4',
    participatingChains: ['S', 'C'],
    weights: { s_chain: 0.30, c_chain: 0.70 },
    triggerCondition: { type: 'always' },
    fallback: { type: 'majority_vote' },
  },
  {
    nodeId: 'CV5',
    afterStep: 'S5',
    participatingChains: ['S', 'C'],
    weights: { s_chain: 0.45, c_chain: 0.55 },
    triggerCondition: { type: 'on_low_confidence', threshold: 60 },
    fallback: { type: 'weighted_average', requireUserConfirmation: true },
  },
];

// ============================================================
// 工具函数
// ============================================================

/**
 * 创建空的交叉验证节点
 */
export function createEmptyCrossValidationNode(
  nodeId: string,
  stage: ThinkStage
): CrossValidationNode {
  return {
    nodeId,
    stage,
    triggeredAt: Date.now(),
    signals: [],
    consensus: {
      direction: 'neutral',
      overallConfidence: 0,
      agreementLevel: 'conflict',
      votes: [],
    },
    conflicts: [],
    recommendedAction: 'pause',
    recommendationReason: '缺少足够的信号数据',
    architectureNode: {
      id: nodeId,
      type: 'cross-validation',
      name: `交叉验证节点 ${nodeId}`,
      level: 'B',
      status: 'pending',
    },
  };
}

/**
 * 判断是否应该触发交叉验证
 */
export function shouldTriggerCrossValidation(
  config: CrossValidationConfig,
  stepsResults: Map<string, { confidence: number; direction?: SignalDirection }>
): boolean {
  const { triggerCondition } = config;

  switch (triggerCondition.type) {
    case 'always':
      return true;

    case 'on_conflict':
      // 检测是否有方向冲突
      const directions = Array.from(stepsResults.values())
        .map(r => r.direction)
        .filter((d): d is SignalDirection => d !== undefined);
      const uniqueDirections = new Set(directions);
      return uniqueDirections.size > 1;

    case 'on_low_confidence':
      // 检测是否有低置信度
      const confidences = Array.from(stepsResults.values()).map(r => r.confidence);
      const avgConfidence = confidences.reduce((a, b) => a + b, 0) / confidences.length;
      return avgConfidence < (triggerCondition.threshold || 60);

    default:
      return true;
  }
}

/**
 * 获取方向的中文标签
 */
export function getDirectionLabel(direction: SignalDirection): string {
  switch (direction) {
    case 'long':
      return '做多';
    case 'short':
      return '做空';
    case 'neutral':
      return '中性';
    case 'wait':
      return '观望';
  }
}

/**
 * 获取一致性等级的中文标签
 */
export function getAgreementLevelLabel(level: AgreementLevel): string {
  switch (level) {
    case 'strong':
      return '强一致';
    case 'moderate':
      return '中等一致';
    case 'weak':
      return '弱一致';
    case 'conflict':
      return '冲突';
  }
}
