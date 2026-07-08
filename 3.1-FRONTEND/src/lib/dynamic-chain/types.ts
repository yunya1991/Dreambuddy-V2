/**
 * Dynamic Chain - 类型定义
 *
 * 统一规范：动态计划 (Planner) → 步骤执行 (Executor) → 反思闭环 (Reflect)
 * 与 graph-reflection-bridge.ts 的 GraphReflectionState 天然融合
 * - Planner 读 graph 节点状态 → 产出下一步
 * - Executor 执行步骤 → 更新 graph 节点 metadata
 * - Reflect 读 graph + compressionSignal → 5 种决策
 */

import type { GraphReflectionState } from '../graph-reflection-bridge';

// =========================
// Intent & Context
// =========================

export type DynamicChainIntent =
  | 'deep_analysis'
  | 'scenario_sim'
  | 'strategy_verify'
  | 'execute_trade';

export type ThinkingMode = 'quick' | 'standard' | 'deep';

export interface DynamicChainContext {
  intent: DynamicChainIntent;
  message: string;
  sessionId: string;
  symbol: string;
  category: string;
  displayName: string;
  instId: string;
  thinkingMode: ThinkingMode;
  lang: 'zh' | 'en';
  // 可选：已解析的实体
  entities?: {
    timeframe?: string;
    side?: 'long' | 'short';
    risk_level?: string;
  };
  // 可选：已获取的市场数据（若为 null，Executor 会自行生成快照描述）
  marketData?: {
    price?: number;
    high_24h?: number;
    low_24h?: number;
    vol_24h?: number;
    change_pct?: number;
    trend?: 'bullish' | 'bearish' | 'range';
  };
}

// =========================
// Plan
// =========================

export interface PlanStep {
  id: string;              // S1_RESEARCH / S2_ANALYSIS / S3_DESIGN / S4_VALIDATE / S5_EXECUTE
                           // 或子步骤 id: S2.5_DATA_AUGMENT 等
  name: string;            // 人类可读名（"S2 深度分析"）
  description: string;     // 该步需产出什么（传给 Executor 作为 prompt）
  estimatedMs: number;
  credits: number;
  requiresConfirmation?: boolean;
  tools?: ('market' | 'backtest' | 'none')[];
  inputs?: string[];       // 依赖的前序步骤 id（用于构造 prompt 时拼接）
}

export interface DynamicPlan {
  steps: PlanStep[];
  rationale: string;       // "为什么这样分步骤"（用于 debug/audit）
  totalEstimatedMs: number;
  totalCredits: number;
  chainId: string;
  dynamic: true;
}

// =========================
// Step Execution Result
// =========================

export interface StepExecutionResult {
  stepId: string;
  content: string;         // 步骤产出（Markdown）
  confidence: number;      // 0-1
  riskScore: number;       // 0-1
  issuesFound: string[];
  corrections: string[];
  latencyMs: number;
  tokenCost: number;
}

// =========================
// Reflection - 5 种决策
// =========================

export type ReflectDecisionType =
  | 'CONTINUE'
  | 'REDO'
  | 'INSERT_BEFORE'
  | 'JUMP_TO'
  | 'EARLY_TERMINATE';

export interface ReflectDecision {
  type: ReflectDecisionType;
  reason: string;
  /** REDO/JUMP_TO/INSERT_BEFORE 的目标步骤 id（CONTINUE/EARLY_TERMINATE 为空） */
  targetStepId?: string;
  /** INSERT_BEFORE 时：新增的子步骤 plan（动态补全） */
  newStep?: PlanStep;
}

// =========================
// Runner 循环结果
// =========================

export interface DynamicChainResult {
  success: boolean;
  chainId: string;
  steps: PlanStep[];
  stepResults: StepExecutionResult[];
  avgConfidence: number;
  maxRisk: number;
  totalLatencyMs: number;
  totalTokens: number;
  iterations: number;
  summaryMarkdown: string;       // 完整输出（Markdown）
  graphState: GraphReflectionState;
  metadata: {
    reflectionTrace: { stepId: string; decision: string; reason: string }[];
    skippedSteps: string[];
    planRationale: string;
    isDynamic: true;
  };
}
