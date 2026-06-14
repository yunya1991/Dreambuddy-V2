// ============================================================================
// 推荐策略引擎: 类型定义
// ============================================================================
// 推荐策略引擎专用类型，与 strategy-standard-objects.ts 完全隔离
// ============================================================================

import type { Direction, TradeType, StrategyStatus } from "@prisma/client";

// ----------------------------------------------------------------------------
// 研报数据类型
// ----------------------------------------------------------------------------

export interface ResearchReport {
  file: string;
  title: string;
  date: string;
  type: string;
  chain_phase: string;
  tags: string;
  department: string;
  status: string;
  regime?: string;
  confidence?: number;
  direction?: string;
  position_modifier?: number;
  leverage_cap?: number;
  // 扩展字段（来自研报内容解析）
  keySignals?: string[];
  marketContext?: string;
  riskFactors?: string[];
}

// ----------------------------------------------------------------------------
// 候选策略（由 D-Z-E 思维链生成）
// ----------------------------------------------------------------------------

export interface CandidateStrategy {
  id: string; // 临时 ID，生成后变为真实 strategyId
  name: string;
  description: string;
  direction: Direction;
  symbol: string;
  tradeType: TradeType;
  leverage: number;
  positionSize: number;
  stopLoss?: number;
  takeProfit?: number;
  confidence: number;
  regime: string; // 市场状态
  sourceEngine: "dze-chain";
  sourceReportIds: string[]; // 关联的研报 ID

  // D-Z-E 思维链元数据
  dzeChain?: {
    d: string; // Decision: 决策依据
    z: string; // Zero: 清零旧认知
    e: string; // Entry: 入场决策
  };
}

// ----------------------------------------------------------------------------
// 回测结果
// ----------------------------------------------------------------------------

export interface BacktestResult {
  strategyId: string;
  backtestPeriod: "7D" | "30D" | "180D";
  symbol: string;
  baselineVersion: "v9" | "v15";

  // 策略性能
  sharpeRatio: number;
  maxDrawdown: number; // %
  winRate: number; // %
  profitFactor: number;
  totalReturn: number; // %
  tradeCount: number;

  // 基线性能（同时段）
  baselineSharpe: number;
  baselineMaxDrawdown: number;
  baselineTotalReturn: number;

  // 对比判定
  isBetterThanBaseline: boolean;
  betterCount: number; // 优于基线的指标数量

  // 回测详情 JSON（完整报告路径）
  reportPath?: string;
  rawMetrics?: Record<string, unknown>;
}

// ----------------------------------------------------------------------------
// 贝叶斯优化结果
// ----------------------------------------------------------------------------

export interface BayesianOptimizedParams {
  strategyId: string;
  originalParams: CandidateStrategy;
  optimizedParams: OptimizedParamValues;
  optimizationRounds: number;
  improvement: {
    sharpeImprovement: number;
    ddImprovement: number; // 负数表示回撤减少
  };
  confidence: number; // 优化置信度
}

export interface OptimizedParamValues {
  entryThreshold: number;       // [50, 80]
  levelSpacingK: number;      // [0.3, 0.8]
  stopLossMult: number;        // [1.5, 3.0] ATR倍数
  tpLevel1: number;            // [2.0, 4.0] ATR倍数
  tpLevel2: number;            // [3.0, 6.0] ATR倍数
  tpLevel3: number;            // [5.0, 8.0] ATR倍数
  weakPosPct: number;          // [10, 40] %
  strongPosPct: number;         // [60, 100] %
}

// ----------------------------------------------------------------------------
// 引擎运行状态
// ----------------------------------------------------------------------------

export type EngineTriggerType = "scheduled" | "manual" | "forced";
export type EngineStatus = "idle" | "running" | "success" | "partial" | "failed" | "skipped";

export interface EngineRunStatus {
  runId: string;
  status: EngineStatus;
  currentStep: EngineStep | null;
  startedAt: string | null;
  estimatedDurationMs: number | null;
  errorMessage?: string;
}

export type EngineStep =
  | "fetching_reports"
  | "generating_candidates"
  | "running_backtests"
  | "optimizing_params"
  | "making_decision"
  | "writing_to_prisma"
  | "updating_library"
  | "completed";

// ----------------------------------------------------------------------------
// 推荐策略（最终写入 Prisma 的格式）
// ----------------------------------------------------------------------------

export interface RecommendedStrategyWrite {
  // 基本信息
  type: "RECOMMENDED";
  name: string;
  description: string;
  direction: Direction;
  symbol: string;
  tradeType: TradeType;
  leverage: number;
  positionSize: number;
  stopLoss?: number;
  takeProfit?: number;
  confidence: number;

  // 策略状态
  status: StrategyStatus;

  // 回测性能
  backtestSharpe: number;
  backtestMaxDrawdown: number;
  backtestWinRate: number;
  backtestProfitFactor: number;
  backtestTotalReturn: number;
  backtestPeriod: "7D" | "30D" | "180D";
  backtestDate: Date;

  // 基线对比
  baselineVersion: "v9" | "v15";
  baselineSharpe: number;
  baselineMaxDrawdown: number;
  baselineTotalReturn: number;
  isBetterThanBaseline: boolean;

  // 来源
  sourceEngine: "dze-chain" | "bayesian" | "manual" | "baseline";
  sourceReportIds: string;
  regime: string;

  // 迭代
  generation: number;
  parentStrategyId?: string;

  // 策略库
  isInLibrary: boolean;
  libraryScore: number;
  libraryActive: boolean;

  // 推荐天数
  recommendedDays: number;
}

// ----------------------------------------------------------------------------
// 策略库
// ----------------------------------------------------------------------------

export interface LibraryStrategy {
  id: string;
  name: string;
  direction: Direction;
  symbol: string;
  regime: string;

  // 性能
  backtestSharpe: number;
  backtestMaxDrawdown: number;
  backtestTotalReturn: number;
  baselineVersion: string;
  isBetterThanBaseline: boolean;

  // 库状态
  libraryScore: number;
  libraryActive: boolean;
  libraryArchivedAt: string | null;

  // 历史
  generation: number;
  sourceEngine: string;
  createdAt: string;
  lastDailyBacktestDate: string | null;
  consecutiveBelowBaseline: number;

  // 最新回测记录
  latestRecord?: {
    backtestDate: string;
    isBetterThanBaseline: boolean;
    sharpeRatio: number;
  };
}

// ----------------------------------------------------------------------------
// 引擎配置
// ----------------------------------------------------------------------------

export interface EngineConfig {
  enabled: boolean;
  baselineVersion: "v9" | "v15";
  backtestPeriod: "7D" | "30D" | "180D";
  symbol: string;
  maxCandidates: number;      // 最大候选策略数量
  forcedRefreshDays: number;   // 强制刷新天数（默认5天）
  rollbackThreshold: number;   // 回退基线的连续失败次数（默认3次）
  bayesianRounds: number;      // 贝叶斯优化轮数（默认200）
  minBetterCount: number;       // 通过基线的最少指标数量（默认3个）
  // 基线对比容差（升版门槛）
  sharpeTolerance: number;     // Sharpe 容差：-0.05
  maxDDTolerance: number;       // MaxDD 容差：+0.5%（回撤越小越好）
  returnTolerance: number;      // 收益率容差：-1.0%
}

// 默认配置
export const DEFAULT_ENGINE_CONFIG: EngineConfig = {
  enabled: true,
  baselineVersion: "v9",
  backtestPeriod: "7D",
  symbol: "BTC-USDT-SWAP",
  maxCandidates: 5,
  forcedRefreshDays: 5,
  rollbackThreshold: 3,
  bayesianRounds: 200,
  minBetterCount: 3,
  sharpeTolerance: -0.05,
  maxDDTolerance: 0.5,
  returnTolerance: -1.0,
};

// ----------------------------------------------------------------------------
// 引擎运行日志（用于 UI 展示）
// ----------------------------------------------------------------------------

export interface EngineRunLog {
  runId: string;
  runDate: string;
  triggerType: EngineTriggerType;
  status: EngineStatus;
  reportsUsed: number;
  reportIds: string[];
  candidatesGenerated: number;
  strategiesBacktested: number;
  strategiesPassed: number;
  recommendedStrategyId: string | null;
  recommendedStrategyName?: string;
  isForcedRefresh: boolean;
  decisionReason: string;
  errorMessage?: string;
  durationMs: number | null;
  startedAt: string | null;
  endedAt: string | null;
}

// ----------------------------------------------------------------------------
// 回测历史记录（用于 UI 展示）
// ----------------------------------------------------------------------------

export interface BacktestHistoryItem {
  id: string;
  strategyId: string;
  strategyName: string;
  strategyDirection: Direction;

  backtestDate: string;
  backtestPeriod: string;
  baselineVersion: string;
  symbol: string;

  // 策略性能
  sharpeRatio: number;
  maxDrawdown: number;
  winRate: number;
  profitFactor: number;
  totalReturn: number;
  tradeCount: number;

  // 基线性能
  baselineSharpe: number;
  baselineMaxDrawdown: number;
  baselineTotalReturn: number;

  // 对比
  isBetterThanBaseline: boolean;
  runId?: string;

  // 差值
  sharpeDiff: number;
  ddDiff: number; // 负数表示回撤更小
  returnDiff: number;
}
