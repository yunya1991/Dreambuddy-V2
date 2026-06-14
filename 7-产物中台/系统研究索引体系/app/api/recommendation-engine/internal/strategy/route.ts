// ============================================================================
// 推荐策略引擎: Python 引擎写入内部 API
// ============================================================================
// Python 引擎通过此 API 将推荐策略写入 Prisma 数据库
// 路径: /api/recommendation-engine/internal/strategy
// 方法: POST
// 认证: X-Internal-Api-Key header
// ============================================================================

import { NextRequest, NextResponse } from "next/server";
import { PrismaClient } from "@prisma/client";
import type { RecommendedStrategyWrite, BacktestResult, EngineRunLog } from "@/lib/recommendation-engine/types";

const prisma = new PrismaClient();

// 系统用户 UID（推荐策略的默认 owner）
const SYSTEM_UID = "SYSTEM_ENGINE";

/**
 * 确保系统用户存在
 */
async function ensureSystemUser(): Promise<string> {
  const existing = await prisma.user.findUnique({
    where: { uid: SYSTEM_UID },
  });

  if (existing) return SYSTEM_UID;

  // 创建系统用户（只读，没有密码）
  await prisma.user.upsert({
    where: { uid: SYSTEM_UID },
    update: {},
    create: {
      uid: SYSTEM_UID,
      email: "system@recommendation-engine.internal",
      emailVerified: true,
      passwordHash: "$2a$10$internal.system.no.password", // 占位符，不用于登录
      displayName: "推荐策略引擎",
    },
  });

  return SYSTEM_UID;
}

/**
 * 认证校验
 */
function validateApiKey(request: NextRequest): NextResponse | null {
  const apiKey = request.headers.get("X-Internal-Api-Key");
  const expectedKey = process.env.RECOMMENDATION_ENGINE_API_KEY;

  if (!expectedKey) {
    console.warn(
      "[recommendation-engine] RECOMMENDATION_ENGINE_API_KEY not set, allowing request"
    );
    return null; // 开发环境无 key 也放行
  }

  if (!apiKey || apiKey !== expectedKey) {
    return NextResponse.json(
      { success: false, error: "Unauthorized" },
      { status: 401 }
    );
  }

  return null;
}

// ----------------------------------------------------------------------------
// POST /api/recommendation-engine/internal/strategy
// 创建推荐策略
// ----------------------------------------------------------------------------

export async function POST(request: NextRequest) {
  const authError = validateApiKey(request);
  if (authError) return authError;

  try {
    const body = await request.json();
    const { action, strategy, backtestResult, backtestRecord } = body;

    await ensureSystemUser();

    if (action === "create_strategy") {
      return await handleCreateStrategy(strategy as RecommendedStrategyWrite);
    } else if (action === "create_backtest_record") {
      return await handleCreateBacktestRecord(backtestRecord);
    } else if (action === "log_engine_run") {
      return await handleLogEngineRun(body.log as EngineRunLog);
    } else if (action === "update_strategy_counters") {
      return await handleUpdateStrategyCounters(body.strategyId, body.updates);
    } else if (action === "update_current_recommended") {
      return await handleUpdateCurrentRecommended(strategy as RecommendedStrategyWrite);
    } else {
      return NextResponse.json(
        { success: false, error: `Unknown action: ${action}` },
        { status: 400 }
      );
    }
  } catch (error) {
    console.error("[recommendation-engine/internal] Error:", error);
    return NextResponse.json(
      { success: false, error: String(error) },
      { status: 500 }
    );
  }
}

// ----------------------------------------------------------------------------
// GET /api/recommendation-engine/internal/strategy
// 查询推荐策略（供 Python 引擎读取当前状态）
// ----------------------------------------------------------------------------

export async function GET(request: NextRequest) {
  const authError = validateApiKey(request);
  if (authError) return authError;

  const { searchParams } = new URL(request.url);
  const action = searchParams.get("action");

  try {
    if (action === "current_recommended") {
      // 获取当前推荐的策略
      const current = await prisma.strategy.findFirst({
        where: {
          type: "RECOMMENDED",
          status: { in: ["APPROVED", "APPLIED"] },
        },
        orderBy: { createdAt: "desc" },
      });
      return NextResponse.json({ success: true, strategy: current });
    } else if (action === "library_strategies") {
      // 获取策略库中所有活跃策略
      const library = await prisma.strategy.findMany({
        where: { isInLibrary: true, libraryActive: true },
        orderBy: { libraryScore: "desc" },
      });
      return NextResponse.json({ success: true, strategies: library });
    } else if (action === "config") {
      // 获取引擎配置
      const configs = await prisma.recommendationEngineConfig.findMany();
      return NextResponse.json({ success: true, configs });
    } else {
      return NextResponse.json(
        { success: false, error: `Unknown action: ${action}` },
        { status: 400 }
      );
    }
  } catch (error) {
    console.error("[recommendation-engine/internal] GET Error:", error);
    return NextResponse.json(
      { success: false, error: String(error) },
      { status: 500 }
    );
  }
}

// ----------------------------------------------------------------------------
// 处理器：创建推荐策略
// ----------------------------------------------------------------------------

async function handleCreateStrategy(
  strategy: RecommendedStrategyWrite
): Promise<NextResponse> {
  const created = await prisma.strategy.create({
    data: {
      uid: SYSTEM_UID,
      type: "RECOMMENDED",
      name: strategy.name,
      description: strategy.description,
      direction: strategy.direction,
      symbol: strategy.symbol,
      tradeType: strategy.tradeType,
      leverage: strategy.leverage,
      positionSize: strategy.positionSize,
      stopLoss: strategy.stopLoss ?? null,
      takeProfit: strategy.takeProfit ?? null,
      confidence: strategy.confidence,
      status: strategy.status,
      regime: strategy.regime,
      source: "recommendation-engine",

      // 回测性能
      backtestSharpe: strategy.backtestSharpe,
      backtestMaxDrawdown: strategy.backtestMaxDrawdown,
      backtestWinRate: strategy.backtestWinRate,
      backtestProfitFactor: strategy.backtestProfitFactor,
      backtestTotalReturn: strategy.backtestTotalReturn,
      backtestPeriod: strategy.backtestPeriod,
      backtestDate: strategy.backtestDate,

      // 基线对比
      baselineVersion: strategy.baselineVersion,
      baselineSharpe: strategy.baselineSharpe,
      baselineMaxDrawdown: strategy.baselineMaxDrawdown,
      baselineTotalReturn: strategy.baselineTotalReturn,
      isBetterThanBaseline: strategy.isBetterThanBaseline,

      // 策略库
      isInLibrary: strategy.isInLibrary,
      libraryScore: strategy.libraryScore,
      libraryActive: strategy.libraryActive,

      // 来源
      sourceEngine: strategy.sourceEngine,
      sourceReportIds: strategy.sourceReportIds,

      // 迭代
      generation: strategy.generation,
      parentStrategyId: strategy.parentStrategyId ?? null,

      // 推荐天数
      recommendedDays: strategy.recommendedDays,
    },
  });

  return NextResponse.json({
    success: true,
    strategyId: created.id,
    createdAt: created.createdAt,
  });
}

// ----------------------------------------------------------------------------
// 处理器：创建回测记录
// ----------------------------------------------------------------------------

async function handleCreateBacktestRecord(
  record: BacktestResult & {
    runId?: string;
    engineVersion?: string;
    strategyBetterThanBaselineAfterThisRun?: number;
    strategyConsecutiveBelowBaseline?: number;
  }
): Promise<NextResponse> {
  const created = await prisma.strategyBacktestRecord.create({
    data: {
      strategyId: record.strategyId,
      backtestPeriod: record.backtestPeriod,
      baselineVersion: record.baselineVersion,
      symbol: record.symbol,
      sharpeRatio: record.sharpeRatio,
      maxDrawdown: record.maxDrawdown,
      winRate: record.winRate,
      profitFactor: record.profitFactor,
      totalReturn: record.totalReturn,
      tradeCount: record.tradeCount,
      baselineSharpe: record.baselineSharpe,
      baselineMaxDrawdown: record.baselineMaxDrawdown,
      baselineTotalReturn: record.baselineTotalReturn,
      isBetterThanBaseline: record.isBetterThanBaseline,
      strategyBetterThanBaselineAfterThisRun:
        record.strategyBetterThanBaselineAfterThisRun ?? 0,
      strategyConsecutiveBelowBaseline:
        record.strategyConsecutiveBelowBaseline ?? 0,
      runId: record.runId ?? null,
      engineVersion: record.engineVersion ?? null,
    },
  });

  return NextResponse.json({
    success: true,
    recordId: created.id,
  });
}

// ----------------------------------------------------------------------------
// 处理器：记录引擎运行日志
// ----------------------------------------------------------------------------

async function handleLogEngineRun(log: EngineRunLog): Promise<NextResponse> {
  const created = await prisma.recommendationEngineLog.create({
    data: {
      runId: log.runId,
      triggerType: log.triggerType,
      status: log.status,
      reportsUsed: log.reportsUsed,
      reportIds: log.reportIds?.join(",") || null,
      candidatesGenerated: log.candidatesGenerated,
      strategiesBacktested: log.strategiesBacktested,
      strategiesPassed: log.strategiesPassed,
      recommendedStrategyId: log.recommendedStrategyId ?? null,
      isForcedRefresh: log.isForcedRefresh,
      decisionReason: log.decisionReason || null,
      errorMessage: log.errorMessage || null,
      durationMs: log.durationMs ?? null,
      startedAt: log.startedAt ? new Date(log.startedAt) : null,
      endedAt: log.endedAt ? new Date(log.endedAt) : null,
    },
  });

  return NextResponse.json({
    success: true,
    logId: created.id,
  });
}

// ----------------------------------------------------------------------------
// 处理器：更新策略计数器
// ----------------------------------------------------------------------------

async function handleUpdateStrategyCounters(
  strategyId: string,
  updates: {
    consecutiveBelowBaseline?: number;
    recommendedDays?: number;
    lastDailyBacktestDate?: string;
    libraryActive?: boolean;
    libraryArchivedAt?: string;
    isBetterThanBaseline?: boolean;
  }
): Promise<NextResponse> {
  await prisma.strategy.update({
    where: { id: strategyId },
    data: {
      consecutiveBelowBaseline: updates.consecutiveBelowBaseline ?? undefined,
      recommendedDays: updates.recommendedDays ?? undefined,
      lastDailyBacktestDate: updates.lastDailyBacktestDate
        ? new Date(updates.lastDailyBacktestDate)
        : undefined,
      libraryActive: updates.libraryActive ?? undefined,
      libraryArchivedAt: updates.libraryArchivedAt
        ? new Date(updates.libraryArchivedAt)
        : undefined,
      isBetterThanBaseline: updates.isBetterThanBaseline ?? undefined,
    },
  });

  return NextResponse.json({ success: true });
}

// ----------------------------------------------------------------------------
// 处理器：更新当前推荐策略（增加推荐天数 or 回退到基线）
// ----------------------------------------------------------------------------

async function handleUpdateCurrentRecommended(
  strategy: RecommendedStrategyWrite
): Promise<NextResponse> {
  // 找到当前 APPROVED/APPLIED 的推荐策略
  const current = await prisma.strategy.findFirst({
    where: {
      type: "RECOMMENDED",
      status: { in: ["APPROVED", "APPLIED"] },
    },
    orderBy: { createdAt: "desc" },
  });

  if (!current) {
    return await handleCreateStrategy(strategy);
  }

  // 增加推荐天数
  await prisma.strategy.update({
    where: { id: current.id },
    data: {
      recommendedDays: (current.recommendedDays || 0) + 1,
    },
  });

  // 如果新策略优于基线，创建新策略
  if (strategy.isBetterThanBaseline) {
    return await handleCreateStrategy(strategy);
  }

  return NextResponse.json({
    success: true,
    strategyId: current.id,
    updated: true,
    newStrategyCreated: false,
  });
}
