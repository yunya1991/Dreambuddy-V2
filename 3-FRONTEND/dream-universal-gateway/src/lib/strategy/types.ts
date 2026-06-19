/**
 * 策略思维链 - 核心类型定义
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 * 职责: S系列策略思维链的类型系统
 */

import type { IntentType } from "@/types";

// ============================================================
// 步骤状态
// ============================================================

export type StrategyStepStatus = "pending" | "active" | "done" | "skipped";

// ============================================================
// 步骤定义
// ============================================================

/**
 * S系列策略思维链 - 5步定义
 */
export const STRATEGY_STEPS = [
  { number: 1 as const, id: "S1_RESEARCH", name: "调研", nameEn: "Research", icon: "🔍" },
  { number: 2 as const, id: "S2_ANALYSIS", name: "分析", nameEn: "Analysis", icon: "🧠" },
  { number: 3 as const, id: "S3_DESIGN", name: "设计", nameEn: "Design", icon: "🎯" },
  { number: 4 as const, id: "S4_VALIDATE", name: "验证", nameEn: "Validate", icon: "✅" },
  { number: 5 as const, id: "S5_EXECUTE", name: "执行", nameEn: "Execute", icon: "⚡" },
] as const;

export type StrategyStepId = typeof STRATEGY_STEPS[number]["id"];

// ============================================================
// 步骤记录
// ============================================================

export interface StrategyStep {
  id: StrategyStepId;
  number: 1 | 2 | 3 | 4 | 5;
  name: string;
  nameEn: string;
  icon: string;
  status: StrategyStepStatus;
  output: string;
  artifacts: string[];
  notes: string;
  startedAt?: string;
  completedAt?: string;
  skippedReason?: string;
}

// ============================================================
// 策略链状态
// ============================================================

export interface StrategyChainState {
  scope: string;
  currentStep: StrategyStepId | null;
  steps: StrategyStep[];
  complexity: StrategyComplexity;
  createdAt: string;
  modifiedAt: string;
}

// ============================================================
// 复杂度模式
// ============================================================

/**
 * 复杂度分级：
 * - quick: 快速模式（1-2步），简单查询/信号判断
 * - standard: 标准模式（3步），常规策略分析
 * - deep: 深度模式（5步），复杂研究/重大决策
 */
export type StrategyComplexity = "quick" | "standard" | "deep";

// ============================================================
// 策略任务
// ============================================================

export interface StrategyTask {
  id: string;
  sessionId: string;
  title: string;
  intent: IntentType | string;
  userInput: string;
  complexity: StrategyComplexity;
  chainState: StrategyChainState;
  entities: Record<string, string>; // BTC / ETH / XAU 等
  credits: {
    estimated: number;
    used: number;
  };
}

// ============================================================
// 用户决策动作
// ============================================================

export type StrategyStepAction =
  | "continue"    // 继续下一步
  | "skip"        // 跳过当前步
  | "jump"        // 跳到指定步
  | "finalize"    // 直接执行全部
  | "pause";      // 暂停/修改

export interface StrategyActionRequest {
  action: StrategyStepAction;
  taskId: string;
  stepId?: StrategyStepId;
  targetStep?: number;  // 用于 jump
  reason?: string;
}

// ============================================================
// 路由配置
// ============================================================

export interface StrategyRouteConfig {
  complexity: StrategyComplexity;
  steps: StrategyStepId[];
  requiresConfirmation: boolean;
  description: string;
}

// ============================================================
// 步骤输入输出类型
// ============================================================

/**
 * S1_调研 输入
 */
export interface S1ResearchInput {
  symbol: string;
  displayName: string;
  userIntent?: string;
}

/**
 * S1_调研 输出
 */
export interface S1ResearchOutput {
  symbol: string;
  displayName: string;
  price: number;
  priceChange24h: number;
  support: string;
  resistance: string;
  indicators: {
    rsi: number;
    macd: { value: number; signal: number; histogram: number };
    trend: "bullish" | "bearish" | "neutral";
  };
  sentiment?: {
    fearGreedIndex?: number;
    fundingRate?: number;
  };
  summary: string;
}

/**
 * S2_分析 输入
 */
export interface S2AnalysisInput extends S1ResearchOutput {
  userNotes?: string;
}

/**
 * S2_分析 输出
 */
export interface S2AnalysisOutput {
  trend: {
    shortTerm: "bullish" | "bearish" | "neutral";
    mediumTerm: "bullish" | "bearish" | "neutral";
    longTerm: "bullish" | "bearish" | "neutral";
  };
  keyLevels: {
    entryRange: string;
    stopLoss: string;
    takeProfit: string;
  };
  risks: string[];
  confidence: number;
  conclusion: string;
}

/**
 * S3_设计 输入
 */
export interface S3DesignInput extends S2AnalysisOutput {
  userPreferences?: {
    riskTolerance?: "low" | "medium" | "high";
    positionSize?: number;
  };
}

/**
 * S3_设计 输出
 */
export interface S3DesignOutput {
  strategyName: string;
  entryPlan: {
    entryPoint: string;
    positionSize: number;
    addRules?: string;
  };
  riskManagement: {
    stopLoss: string;
    takeProfit: string;
    riskRewardRatio: string;
  };
  scenarios: Array<{
    scenario: string;
    probability: number;
    outcome: string;
  }>;
  confidence: number;
}

/**
 * S4_验证 输入
 */
export interface S4ValidateInput extends S3DesignOutput {
  historicalPeriod?: string;
}

/**
 * S4_验证 输出
 */
export interface S4ValidateOutput {
  backtest: {
    period: string;
    winRate: number;
    profitFactor: number;
    maxDrawdown: number;
    sharpeRatio: number;
  };
  riskAssessment: {
    var95: number;
    maxDailyLoss: number;
    consecutiveLosses: number;
  };
  verdict: string;
  recommend: boolean;
}

/**
 * S5_执行 输入
 */
export interface S5ExecuteInput extends S4ValidateOutput {
  confirmExecution?: boolean;
}

/**
 * S5_执行 输出
 */
export interface S5ExecuteOutput {
  checklist: string[];
  alerts: Array<{
    price: string;
    action: string;
  }>;
  warnings: string[];
  trackingPlan: string;
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 根据步骤ID获取步骤定义
 */
export function getStepDefinition(stepId: StrategyStepId) {
  return STRATEGY_STEPS.find(s => s.id === stepId);
}

/**
 * 根据步骤序号获取步骤ID
 */
export function getStepIdByNumber(number: 1 | 2 | 3 | 4 | 5): StrategyStepId {
  return STRATEGY_STEPS[number - 1].id;
}

/**
 * 创建默认策略链状态
 */
export function createDefaultChainState(scope: string, complexity: StrategyComplexity = "standard"): StrategyChainState {
  const now = new Date().toISOString();
  const steps: StrategyStep[] = STRATEGY_STEPS.map((s, idx) => {
    // 根据复杂度模式确定初始状态
    let status: StrategyStepStatus = "pending";
    if (complexity === "quick") {
      status = idx >= 1 ? "skipped" : (idx === 0 ? "active" : "pending");
    } else if (complexity === "standard") {
      status = idx >= 3 ? "skipped" : (idx === 0 ? "active" : "pending");
    } else {
      status = idx === 0 ? "active" : "pending";
    }

    return {
      id: s.id,
      number: s.number,
      name: s.name,
      nameEn: s.nameEn,
      icon: s.icon,
      status,
      output: "",
      artifacts: [],
      notes: "",
    };
  });

  return {
    scope,
    currentStep: "S1_RESEARCH",
    steps,
    complexity,
    createdAt: now,
    modifiedAt: now,
  };
}

/**
 * 获取下一步骤ID
 */
export function getNextStepId(currentStepId: StrategyStepId): StrategyStepId | null {
  const currentIdx = STRATEGY_STEPS.findIndex(s => s.id === currentStepId);
  if (currentIdx === -1 || currentIdx >= STRATEGY_STEPS.length - 1) {
    return null;
  }
  return STRATEGY_STEPS[currentIdx + 1].id;
}
