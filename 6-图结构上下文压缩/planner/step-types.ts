/**
 * 思维步骤接口 - 定义每个思维阶段的契约
 *
 * 位置: 6-图结构上下文压缩/planner/step-types.ts
 *
 * 核心理念: 思维链是"骨架"，不是"实现"
 * 每步内部由 AI 推理动态决定：调用什么技能、如何评估、是否迭代
 */

import { SkillChain, SkillResult, ThinkStage } from './skill-types.ts';
import { SerializedNode } from '../types.ts';

// ============================================================
// 步骤定义
// ============================================================

/**
 * 思维步骤定义
 * 定义每个思维阶段的标准接口
 */
export interface ThinkingStepDefinition {
  /** 步骤 ID，如 'S1', 'C2', 'F3' */
  id: string;

  /** 思维阶段 */
  stage: ThinkStage;

  /** 所属链 */
  chain: SkillChain;

  // ---- 可视化 ----

  /** 步骤标签，如 'S1_调研' */
  label: string;

  /** 步骤图标 */
  icon: string;

  /** 步骤描述 */
  description: string;

  // ---- 核心问题 ----

  /** 核心问题 - AI 需要回答的问题 */
  coreQuestion: string;

  /** 期望产出列表 */
  expectedOutputs: string[];

  // ---- 置信度要求 ----

  /** 置信度阈值配置 */
  confidenceThresholds: ConfidenceThresholds;

  // ---- 技能配置 ----

  /** 推荐调用的技能类别 */
  recommendedSkillCategories?: string[];

  /** 必须调用的技能 ID */
  requiredSkills?: string[];

  /** 依赖的前置步骤 */
  dependsOn?: string[];

  // ---- 迭代配置 ----

  /** 是否允许迭代 */
  allowIteration?: boolean;

  /** 最大迭代次数 */
  maxIterations?: number;

  // ---- 交叉验证 ----

  /** 是否是交叉验证节点 */
  isCrossValidationPoint?: boolean;

  /** 参与交叉验证的链 */
  crossValidationChains?: SkillChain[];
}

/** 置信度阈值配置 */
export interface ConfidenceThresholds {
  /** 高置信度阈值 >= 此值直接进入下一步 */
  high: number;

  /** 中置信度阈值 >= 此值进行迭代 */
  medium: number;

  /** 低置信度阈值 < 此值警告或降级 */
  low: number;
}

// ============================================================
// 步骤执行结果
// ============================================================

/**
 * 思维步骤执行状态
 */
export type StepStatus = 'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'iterating';

/**
 * 步骤执行决策
 */
export type StepDecision = 'proceed' | 'iterate' | 'skip' | 'warn' | 'escalate';

/**
 * 信息缺口类型
 */
export type GapType =
  | 'missing-data'
  | 'missing-skill'
  | 'logical-conflict'
  | 'insufficient-evidence'
  | 'low-confidence';

/**
 * 信息缺口
 */
export interface Gap {
  /** 缺口类型 */
  type: GapType;

  /** 缺口描述 */
  description: string;

  /** 建议的行动 */
  suggestedAction: string;

  /** 建议调用的技能 */
  suggestedSkillId?: string;

  /** 优先级 */
  priority: 'high' | 'medium' | 'low';
}

/**
 * 技能调用记录
 */
export interface SkillCallRecord {
  /** 技能 ID */
  skillId: string;

  /** 技能名称 */
  skillName: string;

  /** 执行结果 */
  result: SkillResult;

  /** 调用序号（迭代时递增） */
  invocationIndex: number;

  /** 调用耗时 */
  latencyMs?: number;

  /** 是否是降级调用 */
  isFallback?: boolean;
}

/**
 * 迭代日志条目
 */
export interface IterationLogEntry {
  /** 迭代序号 */
  iteration: number;

  /** 补充调用的技能 */
  addedSkills: string[];

  /** 迭代后置信度 */
  newConfidence: number;

  /** 迭代决策 */
  decision: StepDecision;

  /** 迭代原因 */
  reason?: string;
}

/**
 * 跨链关联
 */
export interface CrossChainReference {
  /** 关联的链 */
  chain: SkillChain;

  /** 关联的步骤 ID */
  stepId: string;

  /** 关联关系 */
  relationship: 'supports' | 'conflicts' | 'complements' | 'extends';
}

/**
 * 步骤执行结果
 */
export interface StepExecutionResult {
  /** 步骤 ID */
  stepId: string;

  /** 思维阶段 */
  stage: ThinkStage;

  /** 所属链 */
  chain: SkillChain;

  // ---- 执行状态 ----

  /** 状态 */
  status: StepStatus;

  /** 核心问题 */
  coreQuestion: string;

  /** AI 的回答 */
  answer: string;

  // ---- 技能调用 ----

  /** 调用的技能列表 */
  skillsCalled: SkillCallRecord[];

  // ---- 置信度评估 ----

  /** 综合置信度 (0-100) */
  confidence: number;

  /** 置信度分项评分 */
  confidenceDimensions?: {
    dataCompleteness: number;
    logicalConsistency: number;
    crossValidation?: number;
    historicalPerformance?: number;
  };

  // ---- 信息缺口 ----

  /** 识别的缺口 */
  gaps?: Gap[];

  // ---- 决策 ----

  /** 决策 */
  decision: StepDecision;

  /** 决策原因 */
  decisionReason: string;

  // ---- 迭代信息 ----

  /** 迭代次数 */
  iterations?: number;

  /** 迭代日志 */
  iterationLog?: IterationLogEntry[];

  /** 迭代原因 */
  iterationReason?: string;

  // ---- 性能指标 ----

  /** 使用的 token 数 */
  tokensUsed?: number;

  /** 执行延迟（毫秒） */
  latencyMs?: number;

  // ---- 跨链关联 ----

  /** 跨链引用 */
  crossChainReferences?: CrossChainReference[];

  // ---- 图架构 ----

  /** 架构节点（写入图压缩模块） */
  architectureNode: SerializedNode;
}

// ============================================================
// S 链步骤定义
// ============================================================

/**
 * S 链（通用交易思维）的步骤定义
 */
export const S_CHAIN_STEPS: ThinkingStepDefinition[] = [
  {
    id: 'S1',
    stage: 'research',
    chain: 'S',
    label: 'S1_调研',
    icon: '🔍',
    description: '市场数据、行情、技术指标、新闻收集',
    coreQuestion: '当前市场发生了什么？趋势是什么？有哪些关键事件？数据充分吗？',
    expectedOutputs: ['市场趋势', '关键事件列表', '数据质量评估', '信息完整性评分'],
    confidenceThresholds: { high: 80, medium: 50, low: 30 },
    recommendedSkillCategories: ['intelligence', 'execution'],
    allowIteration: true,
    maxIterations: 2,
    isCrossValidationPoint: true,
    crossValidationChains: ['S', 'C', 'F'],
  },
  {
    id: 'S2',
    stage: 'analysis',
    chain: 'S',
    label: 'S2_分析',
    icon: '🧠',
    description: '多维度分析（技术面、基本面、情绪面）',
    coreQuestion: '这意味着什么？信号强度如何？市场状态是什么？有哪些风险？信息缺口？',
    expectedOutputs: ['分析结论', '信号强度评分', '市场状态', '风险评级', '信息缺口列表'],
    confidenceThresholds: { high: 80, medium: 50, low: 30 },
    recommendedSkillCategories: ['execution', 'intelligence'],
    requiredSkills: ['dream-regime-detector'],
    allowIteration: true,
    maxIterations: 3,
    isCrossValidationPoint: true,
    crossValidationChains: ['S', 'C', 'F'],
  },
  {
    id: 'S3',
    stage: 'design',
    chain: 'S',
    label: 'S3_设计',
    icon: '🎯',
    description: '制定具体策略（入场点、止损、止盈、仓位）',
    coreQuestion: '应该怎么做？方向？入场点？止损？止盈？仓位？策略类型？',
    expectedOutputs: ['交易计划', '入场点位', '止损点位', '止盈策略', '仓位方案', '策略类型'],
    confidenceThresholds: { high: 75, medium: 50, low: 25 },
    recommendedSkillCategories: ['execution', 'research'],
    allowIteration: true,
    maxIterations: 2,
    isCrossValidationPoint: true,
    crossValidationChains: ['S', 'C'],
  },
  {
    id: 'S4',
    stage: 'validate',
    chain: 'S',
    label: 'S4_验证',
    icon: '✅',
    description: '回测验证、风险评估、模拟推演',
    coreQuestion: '这个方案经得起检验吗？历史回测如何？模拟推演暴露了什么风险？',
    expectedOutputs: ['验证报告', '回测结果', '风险评估', '置信度评分', '通过/否决标记'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['governance', 'research'],
    requiredSkills: ['dream-pretrade-gatekeeper'],
    allowIteration: true,
    maxIterations: 2,
    isCrossValidationPoint: true,
    crossValidationChains: ['S', 'C'],
  },
  {
    id: 'S5',
    stage: 'execute',
    chain: 'S',
    label: 'S5_执行',
    icon: '⚡',
    description: '生成执行计划、跟踪调整',
    coreQuestion: '怎么落地？下单指令？监控什么？离场条件？',
    expectedOutputs: ['执行指令', '监控指标', '离场条件', '应急预案'],
    confidenceThresholds: { high: 70, medium: 45, low: 25 },
    recommendedSkillCategories: ['execution'],
    allowIteration: false,
    isCrossValidationPoint: true,
    crossValidationChains: ['S', 'C'],
  },
];

// ============================================================
// C 链步骤定义
// ============================================================

/**
 * C 链（量化技术思维）的步骤定义
 */
export const C_CHAIN_STEPS: ThinkingStepDefinition[] = [
  {
    id: 'C1',
    stage: 'research',
    chain: 'C',
    label: 'C1_扫描',
    icon: '📊',
    description: '多周期技术指标扫描',
    coreQuestion: '各周期的技术指标显示什么信号？RSI/MACD/均线/波动率状态？',
    expectedOutputs: ['多周期信号矩阵', '关键指标读数', '信号强度排序'],
    confidenceThresholds: { high: 85, medium: 60, low: 40 },
    recommendedSkillCategories: ['classic-indicators'],
  },
  {
    id: 'C2',
    stage: 'analysis',
    chain: 'C',
    label: 'C2_识别',
    icon: '🔄',
    description: '市场状态自动识别',
    coreQuestion: '当前是趋势市场还是震荡市场？应该用什么策略家族？',
    expectedOutputs: ['市场状态', '推荐策略家族', '状态置信度'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['classic-strategy'],
    requiredSkills: ['RegimeHybridStrategy'],
  },
  {
    id: 'C3',
    stage: 'design',
    chain: 'C',
    label: 'C3_匹配',
    icon: '📋',
    description: '从策略库中匹配最优策略',
    coreQuestion: '有哪些可用策略？哪个最适合当前市场状态？',
    expectedOutputs: ['候选策略列表', '策略评分', '推荐策略', '策略元数据'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['classic-strategy'],
  },
  {
    id: 'C4',
    stage: 'validate',
    chain: 'C',
    label: 'C4_回测',
    icon: '📈',
    description: '历史数据回测验证',
    coreQuestion: '策略在历史上表现如何？胜率/夏普/最大回撤？',
    expectedOutputs: ['回测报告', '绩效指标', 'Gate评估结果', '通过/否决标记'],
    confidenceThresholds: { high: 85, medium: 60, low: 40 },
    recommendedSkillCategories: ['classic-backtest'],
  },
  {
    id: 'C5',
    stage: 'execute',
    chain: 'C',
    label: 'C5_参数',
    icon: '⚙️',
    description: '输出策略参数和信号阈值',
    coreQuestion: '具体的策略参数配置是什么？可以执行吗？',
    expectedOutputs: ['策略参数配置', '信号阈值', '执行就绪状态'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['classic-execution'],
  },
];

// ============================================================
// F 链步骤定义
// ============================================================

/**
 * F 链（基本面思维）的步骤定义
 */
export const F_CHAIN_STEPS: ThinkingStepDefinition[] = [
  {
    id: 'F1',
    stage: 'research',
    chain: 'F',
    label: 'F1_新闻',
    icon: '📰',
    description: '新闻事件扫描与分类',
    coreQuestion: '近期有哪些重要新闻和事件？它们对市场有什么影响？',
    expectedOutputs: ['新闻列表', '事件分类', '影响评估', '情感倾向'],
    confidenceThresholds: { high: 75, medium: 50, low: 30 },
    recommendedSkillCategories: ['fundamental-news'],
  },
  {
    id: 'F2',
    stage: 'analysis',
    chain: 'F',
    label: 'F2_资金',
    icon: '💰',
    description: '链上资金流向分析',
    coreQuestion: '聪明钱在流入还是流出？大额转账有什么信号？',
    expectedOutputs: ['资金流向', '异常标记', '交易所余额变化'],
    confidenceThresholds: { high: 75, medium: 50, low: 30 },
    recommendedSkillCategories: ['fundamental-flow'],
  },
  {
    id: 'F3',
    stage: 'analysis',
    chain: 'F',
    label: 'F3_情绪',
    icon: '😀',
    description: '市场情绪聚合分析',
    coreQuestion: '市场情绪是乐观还是悲观？有没有极端信号？',
    expectedOutputs: ['情绪指数', '热度评估', '极端信号'],
    confidenceThresholds: { high: 70, medium: 45, low: 25 },
    recommendedSkillCategories: ['fundamental-sentiment'],
  },
  {
    id: 'F4',
    stage: 'analysis',
    chain: 'F',
    label: 'F4_链上',
    icon: '⛓️',
    description: '链上指标综合评估',
    coreQuestion: 'MVRV/NUPL 等链上指标显示市场处于什么周期位置？',
    expectedOutputs: ['链上指标面板', '周期位置评估', '顶部/底部信号'],
    confidenceThresholds: { high: 80, medium: 55, low: 35 },
    recommendedSkillCategories: ['fundamental-onchain'],
  },
  {
    id: 'F5',
    stage: 'design',
    chain: 'F',
    label: 'F5_宏观',
    icon: '🌍',
    description: '宏观经济环境扫描',
    coreQuestion: '利率/CPI/就业等宏观因素如何？它们如何影响交易方向？',
    expectedOutputs: ['宏观指标', '环境影响评分', '风险提示'],
    confidenceThresholds: { high: 75, medium: 50, low: 30 },
    recommendedSkillCategories: ['fundamental-macro'],
  },
];

// ============================================================
// 工具函数
// ============================================================

/**
 * 根据步骤 ID 获取步骤定义
 */
export function getStepDefinition(stepId: string): ThinkingStepDefinition | undefined {
  const allSteps = [...S_CHAIN_STEPS, ...C_CHAIN_STEPS, ...F_CHAIN_STEPS];
  return allSteps.find(s => s.id === stepId);
}

/**
 * 根据链类型获取步骤列表
 */
export function getStepsByChain(chain: SkillChain): ThinkingStepDefinition[] {
  switch (chain) {
    case 'S':
      return S_CHAIN_STEPS;
    case 'C':
      return C_CHAIN_STEPS;
    case 'F':
      return F_CHAIN_STEPS;
    default:
      return [];
  }
}

/**
 * 获取所有步骤定义
 */
export function getAllSteps(): ThinkingStepDefinition[] {
  return [...S_CHAIN_STEPS, ...C_CHAIN_STEPS, ...F_CHAIN_STEPS];
}

/**
 * 根据阶段获取步骤
 */
export function getStepsByStage(stage: ThinkStage): ThinkingStepDefinition[] {
  return getAllSteps().filter(s => s.stage === stage);
}

/**
 * 判断是否应该进入下一步
 */
export function shouldProceed(
  confidence: number,
  thresholds: ConfidenceThresholds
): boolean {
  return confidence >= thresholds.high;
}

/**
 * 判断是否应该迭代
 */
export function shouldIterate(
  confidence: number,
  thresholds: ConfidenceThresholds
): boolean {
  return confidence >= thresholds.medium && confidence < thresholds.high;
}

/**
 * 判断是否应该警告
 */
export function shouldWarn(
  confidence: number,
  thresholds: ConfidenceThresholds
): boolean {
  return confidence >= thresholds.low && confidence < thresholds.medium;
}

/**
 * 获取决策建议
 */
export function getDecision(
  confidence: number,
  thresholds: ConfidenceThresholds,
  allowIteration: boolean,
  currentIterations: number,
  maxIterations: number
): StepDecision {
  if (shouldProceed(confidence, thresholds)) {
    return 'proceed';
  }

  if (shouldIterate(confidence, thresholds) && allowIteration && currentIterations < maxIterations) {
    return 'iterate';
  }

  if (shouldWarn(confidence, thresholds)) {
    return 'warn';
  }

  return 'skip';
}
