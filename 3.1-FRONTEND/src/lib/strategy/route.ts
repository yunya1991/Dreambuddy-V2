/**
 * 策略思维链 - 路由引擎
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 * 职责: 策略意图识别和路由选择
 */

import type { IntentType } from "@/types";
import {
  StrategyStepId,
  StrategyComplexity,
  StrategyRouteConfig,
  STRATEGY_STEPS,
} from "./types";

// ============================================================
// 步骤定义
// ============================================================

/**
 * S系列步骤配置
 */
export const STRATEGY_STEP_DEFINITIONS: Record<StrategyStepId, {
  label: string;
  icon: string;
  credits: number;
  time_ms: number;
  description: string;
}> = {
  S1_RESEARCH: {
    label: "S1_调研",
    icon: "🔍",
    credits: 30,
    time_ms: 15000,
    description: "市场数据、行情、技术指标、新闻收集",
  },
  S2_ANALYSIS: {
    label: "S2_分析",
    icon: "🧠",
    credits: 50,
    time_ms: 30000,
    description: "多维度分析（技术面、基本面、情绪面）",
  },
  S3_DESIGN: {
    label: "S3_设计",
    icon: "🎯",
    credits: 60,
    time_ms: 45000,
    description: "制定具体策略（入场点、止损、止盈、仓位）",
  },
  S4_VALIDATE: {
    label: "S4_验证",
    icon: "✅",
    credits: 80,
    time_ms: 60000,
    description: "回测验证、风险评估、模拟推演",
  },
  S5_EXECUTE: {
    label: "S5_执行",
    icon: "⚡",
    credits: 20,
    time_ms: 10000,
    description: "生成执行计划、跟踪调整",
  },
};

// ============================================================
// 意图路由映射
// ============================================================

/**
 * 策略意图 → 路由配置
 */
export const STRATEGY_ROUTE_MAP: Record<Exclude<IntentType, 'command'>, StrategyRouteConfig> = {
  // 简单查询 → 快速模式
  market_query: {
    complexity: "quick",
    steps: ["S1_RESEARCH"],
    requiresConfirmation: false,
    description: "快速行情查询",
  },

  // 深度分析 → 标准模式
  deep_analysis: {
    complexity: "standard",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN"],
    requiresConfirmation: true,
    description: "深度市场分析",
  },

  // 情景模拟 → 深度模式
  scenario_sim: {
    complexity: "deep",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"],
    requiresConfirmation: true,
    description: "情景模拟推演",
  },

  // 策略验证 → 标准模式
  strategy_verify: {
    complexity: "standard",
    steps: ["S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"],
    requiresConfirmation: true,
    description: "策略验证评估",
  },

  // 执行交易 → 深度模式
  execute_trade: {
    complexity: "deep",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE", "S5_EXECUTE"],
    requiresConfirmation: true,
    description: "完整策略执行",
  },

  // 其他意图 → 快速模式
  system_config: {
    complexity: "quick",
    steps: [],
    requiresConfirmation: false,
    description: "系统配置",
  },

  credits_query: {
    complexity: "quick",
    steps: [],
    requiresConfirmation: false,
    description: "积分查询",
  },

  artifact_query: {
    complexity: "quick",
    steps: ["S1_RESEARCH"],
    requiresConfirmation: false,
    description: "知识查询",
  },

  risk_alert_response: {
    complexity: "quick",
    steps: ["S2_ANALYSIS"],
    requiresConfirmation: false,
    description: "风险响应",
  },

  simple_qa: {
    complexity: "quick",
    steps: [],
    requiresConfirmation: false,
    description: "简单问答",
  },
};

// ============================================================
// 命令路由映射
// ============================================================

/**
 * 命令 → 路由配置
 */
export const STRATEGY_COMMAND_ROUTE_MAP: Record<string, {
  intent: IntentType;
  steps: StrategyStepId[];
  complexity: StrategyComplexity;
}> = {
  "/行情": {
    intent: "market_query",
    steps: ["S1_RESEARCH"],
    complexity: "quick",
  },
  "/hq": {
    intent: "market_query",
    steps: ["S1_RESEARCH"],
    complexity: "quick",
  },
  "/分析": {
    intent: "deep_analysis",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN"],
    complexity: "standard",
  },
  "/fx": {
    intent: "deep_analysis",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN"],
    complexity: "standard",
  },
  "/推演": {
    intent: "scenario_sim",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"],
    complexity: "deep",
  },
  "/验证": {
    intent: "strategy_verify",
    steps: ["S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"],
    complexity: "standard",
  },
  "/开仓": {
    intent: "execute_trade",
    steps: ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE", "S5_EXECUTE"],
    complexity: "deep",
  },
};

// ============================================================
// 复杂度评估
// ============================================================

/**
 * 评估问题复杂度
 */
export function evaluateComplexity(
  userInput: string,
  intent: IntentType
): StrategyComplexity {
  const input = userInput.toLowerCase();

  // 强制执行类 → 深度模式
  if (input.includes("开仓") || input.includes("买入") || input.includes("执行")) {
    return "deep";
  }

  // 验证/回测类 → 标准模式
  if (input.includes("验证") || input.includes("回测") || input.includes("测试")) {
    return "standard";
  }

  // 模拟/推演类 → 深度模式
  if (input.includes("模拟") || input.includes("推演") || input.includes("情景")) {
    return "deep";
  }

  // 根据意图确定
  const routeConfig = STRATEGY_ROUTE_MAP[intent as keyof typeof STRATEGY_ROUTE_MAP];
  return routeConfig?.complexity ?? "quick";
}

// ============================================================
// 主路由函数
// ============================================================

export interface StrategyRoutingDecision {
  intent: IntentType;
  complexity: StrategyComplexity;
  steps: StrategyStepId[];
  requiresConfirmation: boolean;
  estimatedTimeMs: number;
  creditsCost: number;
  description: string;
  reasoning: string;
}

/**
 * 策略意图路由
 */
export function routeToStrategyChain(
  intent: IntentType,
  userInput?: string,
  forceComplexity?: StrategyComplexity
): StrategyRoutingDecision {
  // 获取路由配置
  const validIntent = intent as keyof typeof STRATEGY_ROUTE_MAP;
  const routeConfig = STRATEGY_ROUTE_MAP[validIntent] ?? {
    complexity: "quick" as StrategyComplexity,
    steps: [],
    requiresConfirmation: false,
    description: "默认查询",
  };

  // 评估复杂度
  const complexity = forceComplexity ?? evaluateComplexity(userInput ?? "", intent);

  // 根据复杂度过滤步骤
  const baseSteps = routeConfig.steps;
  let filteredSteps: StrategyStepId[];

  switch (complexity) {
    case "quick":
      // 快速模式：只取第一步
      filteredSteps = baseSteps.slice(0, 1);
      break;
    case "standard":
      // 标准模式：取前3步
      filteredSteps = baseSteps.slice(0, 3);
      break;
    case "deep":
      // 深度模式：取全部步骤
      filteredSteps = baseSteps;
      break;
    default:
      filteredSteps = baseSteps;
  }

  // 计算预估时间和积分消耗
  const estimatedTimeMs = filteredSteps.reduce((sum, stepId) => {
    return sum + (STRATEGY_STEP_DEFINITIONS[stepId]?.time_ms ?? 0);
  }, 0);

  const creditsCost = filteredSteps.reduce((sum, stepId) => {
    return sum + (STRATEGY_STEP_DEFINITIONS[stepId]?.credits ?? 0);
  }, 0);

  return {
    intent,
    complexity,
    steps: filteredSteps,
    requiresConfirmation: routeConfig.requiresConfirmation,
    estimatedTimeMs,
    creditsCost,
    description: routeConfig.description,
    reasoning: `意图=${intent}, 复杂度=${complexity}, 步骤数=${filteredSteps.length}`,
  };
}

// ============================================================
// 命令路由函数
// ============================================================

/**
 * 命令路由解析
 */
export function routeByCommand(
  command: string
): StrategyRoutingDecision | null {
  const config = STRATEGY_COMMAND_ROUTE_MAP[command];
  if (!config) {
    return null;
  }

  return routeToStrategyChain(config.intent, command, config.complexity);
}

// ============================================================
// 步骤导航
// ============================================================

/**
 * 获取下一步骤
 */
export function getNextStep(currentStepId: StrategyStepId, allowedSteps: StrategyStepId[]): StrategyStepId | null {
  const currentIdx = allowedSteps.indexOf(currentStepId);
  if (currentIdx === -1 || currentIdx >= allowedSteps.length - 1) {
    return null;
  }
  return allowedSteps[currentIdx + 1];
}

/**
 * 获取上一步骤
 */
export function getPrevStep(currentStepId: StrategyStepId, allowedSteps: StrategyStepId[]): StrategyStepId | null {
  const currentIdx = allowedSteps.indexOf(currentStepId);
  if (currentIdx <= 0) {
    return null;
  }
  return allowedSteps[currentIdx - 1];
}

/**
 * 检查是否可以跳步
 */
export function canSkipStep(
  currentStepId: StrategyStepId,
  allowedSteps: StrategyStepId[],
  requiresConfirmation: boolean
): boolean {
  if (!requiresConfirmation) {
    return false; // 不需要确认的流程不允许跳过
  }

  const currentIdx = allowedSteps.indexOf(currentStepId);
  const remainingSteps = allowedSteps.slice(currentIdx + 1);

  // 至少保留1步
  return remainingSteps.length >= 1;
}

// ============================================================
// 导出
// ============================================================

export * from "./types";
