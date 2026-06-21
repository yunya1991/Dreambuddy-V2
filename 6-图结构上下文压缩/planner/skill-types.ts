/**
 * 技能能力接口 - 所有技能必须实现的统一契约
 *
 * 位置: 6-图结构上下文压缩/planner/skill-types.ts
 *
 * 核心理念: 每个技能都是一个独立的、可被调用的能力单元
 * 有统一契约: 输入 → 处理 → 输出 + 置信度评分
 */

import { z } from 'zod';

// ============================================================
// 基础类型
// ============================================================

/** 技能所属链 */
export type SkillChain = 'A' | 'C' | 'F';

/** 技能分类 */
export type SkillCategory =
  | 'execution'      // 执行闭环
  | 'intelligence'   // 情报闭环
  | 'governance'     // 治理闭环
  | 'research'       // 研究工具
  | 'classic-indicators'   // 经典技术指标
  | 'classic-strategy'      // 经典策略库
  | 'classic-backtest'      // 经典回测
  | 'classic-execution'     // 经典执行
  | 'fundamental-news'      // 基本面新闻
  | 'fundamental-flow'      // 基本面资金
  | 'fundamental-sentiment' // 基本面情绪
  | 'fundamental-onchain'   // 基本面链上
  | 'fundamental-macro';    // 基本面宏观

/** 思维阶段 */
export type ThinkStage = 'research' | 'analysis' | 'design' | 'validate' | 'execute';

/** 交易方向 */
export type TradeDirection = 'long' | 'short' | 'neutral' | 'wait';

// ============================================================
// 技能元信息
// ============================================================

/** 技能的输入定义 */
export interface SkillInput {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  required: boolean;
  description: string;
  example?: unknown;
  schema?: z.ZodType;  // 可选的 Zod schema 用于验证
}

/** 技能的输出定义 */
export interface SkillOutput {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  description: string;
}

/** 技能触发器定义 */
export interface SkillTrigger {
  keywords: string[];       // 触发关键词
  intents: string[];        // 适用的意图类型
  confidence?: number;      // 匹配的最小置信度
}

// ============================================================
// 技能元信息
// ============================================================

/**
 * 技能的元信息
 * 包含技能的标识、分类、成本、性能等元数据
 */
export interface SkillMetadata {
  /** 唯一标识符，如 'dream-regime-detector' */
  id: string;

  /** 可读名称 */
  name: string;

  /** 简短描述 */
  description: string;

  /** 所属链: A=AI技能, C=经典量化, F=基本面 */
  chain: SkillChain;

  /** 技能分类 */
  category: SkillCategory;

  /** 版本号 */
  version: string;

  /** 标签列表，用于检索和分类 */
  tags: string[];

  /** 触发器配置 */
  triggers?: SkillTrigger[];

  // ---- 成本与性能 ----

  /** 预估 token 消耗 */
  estimatedTokens: number;

  /** 预估执行延迟（毫秒） */
  estimatedLatencyMs: number;

  /** 典型置信度范围 [min, max] */
  confidenceRange: [number, number];

  // ---- 适用场景 ----

  /** 适用的用户意图 */
  applicableIntents: string[];

  /** 适用的思维阶段 */
  applicableStages: ThinkStage[];

  /** 最佳市场条件 */
  marketConditions?: string[];

  // ---- 历史表现 ----

  /** 历史准确率 (0-100) */
  historicalAccuracy?: number;

  /** 总调用次数 */
  historicalCalls?: number;

  /** 最后更新时间 */
  updatedAt?: number;

  /** 文档链接 */
  documentationUrl?: string;
}

// ============================================================
// 技能能力接口
// ============================================================

/**
 * 执行上下文
 * 传递给技能的运行时上下文信息
 */
export interface ExecutionContext {
  /** 会话 ID */
  sessionId: string;

  /** 当前意图 */
  intent: string;

  /** 交易标的，如 'BTC' */
  symbol?: string;

  /** 用户角色 */
  userRole: 'FREE' | 'PRO' | 'ADMIN';

  /** 交易模式 */
  tradingMode: 'ai_skill' | 'classic' | 'hybrid';

  /** Token 预算 */
  budgetTokens?: number;

  /** 最大延迟容忍（毫秒） */
  maxLatencyMs?: number;

  /** 链权重配置 */
  chainWeights?: ChainWeights;

  /** 前序技能的产出 */
  priorOutputs?: Record<string, SkillResult>;

  /** 市场状态 */
  marketCondition?: 'trending' | 'ranging' | 'volatile' | 'unknown';

  /** 用户偏好 */
  userPreferences?: UserPreferences;

  /** 扩展字段 */
  [key: string]: unknown;
}

/** 链权重配置 */
export interface ChainWeights {
  s_chain: number;  // AI 技能权重
  c_chain: number;  // 经典指标权重
  f_chain: number;  // 基本面权重
}

/** 用户偏好 */
export interface UserPreferences {
  riskTolerance: 'low' | 'medium' | 'high';
  preferredChains?: SkillChain[];
  maxCostPerRequest?: number;
  preferredTradingStyle?: string;
}

/**
 * 技能执行结果
 * 所有技能执行后必须返回此格式
 */
export interface SkillResult {
  /** 是否成功 */
  success: boolean;

  /** 技能 ID */
  capabilityId: string;

  /** 结构化输出 */
  outputs: SkillOutputs;

  /** 本次执行的置信度 (0-100) */
  confidence: number;

  /** 置信度分项评分 */
  confidenceDimensions?: ConfidenceDimensions;

  /** 实际使用的 token 数 */
  tokensUsed?: number;

  /** 实际执行延迟（毫秒） */
  latencyMs?: number;

  /** 错误信息（如果失败） */
  error?: string;

  /** 警告信息 */
  warnings?: string[];

  /** 建议（如下一步可以做什么） */
  suggestions?: string[];

  /** 额外元信息 */
  metadata?: Record<string, unknown>;
}

/** 技能输出的联合类型 */
export type SkillOutputs = {
  // 基础输出
  direction?: TradeDirection;
  confidence?: number;

  // 分析输出
  analysis?: string;
  reasoning?: string;

  // 数值输出
  value?: number;
  values?: Record<string, number>;

  // 信号输出
  signal?: 'buy' | 'sell' | 'hold';
  signals?: Array<{ indicator: string; value: string | number; signal: 'bullish' | 'bearish' | 'neutral' }>;

  // 策略输出
  strategy?: string;
  strategies?: Array<{ name: string; score: number; description: string }>;

  // 回测输出
  backtest?: {
    winRate?: number;
    profitFactor?: number;
    maxDrawdown?: number;
    sharpeRatio?: number;
  };

  // 风险输出
  risk?: {
    level: 'low' | 'medium' | 'high' | 'critical';
    score: number;
    factors: string[];
  };

  // 通用扩展
  [key: string]: unknown;
};

/** 置信度分项评分 */
export interface ConfidenceDimensions {
  /** 数据完整性 (0-100) */
  dataCompleteness: number;

  /** 逻辑一致性 (0-100) */
  logicalConsistency: number;

  /** 跨源印证 (0-100) */
  crossValidation?: number;

  /** 历史准确率 (0-100) */
  historicalPerformance?: number;
}

/** 技能状态 */
export interface SkillStatus {
  /** 是否健康 */
  healthy: boolean;

  /** 最后执行时间 */
  lastExecutionMs?: number;

  /** 错误率 */
  errorRate?: number;

  /** 平均延迟 */
  avgLatencyMs?: number;

  /** 状态消息 */
  message?: string;
}

// ============================================================
// 技能能力接口
// ============================================================

/**
 * 技能能力接口
 * 所有技能必须实现此接口
 */
export interface SkillCapability {
  /** 技能元信息 */
  metadata: SkillMetadata;

  /** 输入定义 */
  inputSchema: SkillInput[];

  /** 输出定义 */
  outputSchema: SkillOutput[];

  /**
   * 执行技能
   * @param inputs 输入参数
   * @param context 执行上下文
   * @returns 技能执行结果
   */
  execute(inputs: Record<string, unknown>, context: ExecutionContext): Promise<SkillResult>;

  /**
   * 验证输入合法性
   * @param inputs 输入参数
   * @returns 验证结果
   */
  validate?(inputs: Record<string, unknown>): { valid: boolean; errors?: string[] };

  /**
   * 获取降级实现
   * @param inputs 输入参数
   * @returns 降级结果
   */
  getFallback?(inputs: Record<string, unknown>): Promise<SkillResult>;

  /**
   * 获取技能状态
   * @returns 技能状态
   */
  getStatus?(): Promise<SkillStatus>;
}

// ============================================================
// 技能注册表相关
// ============================================================

/** 技能推荐结果 */
export interface SkillRecommendation {
  skill: SkillCapability;
  score: number;         // 推荐得分
  reason: string;       // 推荐原因
  priority: number;     // 优先级 (1=最高)
}

/** 技能查询参数 */
export interface SkillQueryParams {
  /** 所属链 */
  chain?: SkillChain | SkillChain[];

  /** 技能分类 */
  category?: SkillCategory | SkillCategory[];

  /** 适用阶段 */
  stage?: ThinkStage | ThinkStage[];

  /** 适用意图 */
  intent?: string | string[];

  /** 标签 */
  tag?: string | string[];

  /** 最低历史准确率 */
  minAccuracy?: number;

  /** 最大 token 消耗 */
  maxTokens?: number;
}

/** 技能调用记录 */
export interface SkillInvocation {
  skillId: string;
  skillName: string;
  invocationIndex: number;
  result: SkillResult;
  timestamp: number;
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 创建默认的执行上下文
 */
export function createDefaultContext(sessionId: string): ExecutionContext {
  return {
    sessionId,
    intent: 'unknown',
    userRole: 'FREE',
    tradingMode: 'ai_skill',
    chainWeights: {
      s_chain: 0.35,
      c_chain: 0.45,
      f_chain: 0.20,
    },
  };
}

/**
 * 创建默认的成功结果
 */
export function createSuccessResult(
  capabilityId: string,
  outputs: SkillOutputs,
  confidence: number = 75
): SkillResult {
  return {
    success: true,
    capabilityId,
    outputs,
    confidence,
    confidenceDimensions: {
      dataCompleteness: confidence,
      logicalConsistency: confidence,
    },
  };
}

/**
 * 创建默认的失败结果
 */
export function createFailureResult(
  capabilityId: string,
  error: string
): SkillResult {
  return {
    success: false,
    capabilityId,
    outputs: {},
    confidence: 0,
    error,
  };
}

/**
 * 创建降级结果
 */
export function createFallbackResult(
  capabilityId: string,
  reason: string
): SkillResult {
  return {
    success: false,
    capabilityId,
    outputs: {},
    confidence: 30,
    error: `降级: ${reason}`,
    warnings: ['此为降级结果，置信度较低，建议人工确认'],
  };
}
