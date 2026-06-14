// ============================================================================
// 业务数据沉淀枢纽 (Business Data Hub)
// 连接主前端门户的 Prisma SQLite 数据库，为 ui-map 提供业务数据聚合
// 两个核心数据源：
//   1. artifacts 文件系统 (研究内容沉淀) — 通过 content.server.ts 访问
//   2. Prisma SQLite 数据库 (业务数据沉淀) — 通过此模块访问
// ============================================================================

import { PrismaClient } from "@prisma/client";

let prismaInstance: PrismaClient | null = null;

export function getPrisma(): PrismaClient {
  if (!prismaInstance) {
    prismaInstance = new PrismaClient({
      log: [],
    });
  }
  return prismaInstance;
}

// ============================================================================
// 策略业务数据 (User Strategy Precipitation)
// ============================================================================

export interface StrategyBusinessStats {
  totalStrategies: number;
  byStatus: Record<string, number>;
  byType: Record<string, number>;
  activeTasks: number;
  totalExecutions: number;
  completedExecutions: number;
  lastExecutionAt: string | null;
}

export async function getStrategyBusinessStats(): Promise<StrategyBusinessStats> {
  const db = getPrisma();

  const [totalStrategies, byStatus, byType, activeTasks, totalExecutions, completedExecutions, lastExecution] =
    await Promise.all([
      db.strategy.count(),
      db.strategy.groupBy({
        by: ["status"],
        _count: { status: true },
      }),
      db.strategy.groupBy({
        by: ["type"],
        _count: { type: true },
      }),
      db.strategyTask.count({ where: { status: "ACTIVE" } }),
      db.strategyExecutionRun.count(),
      db.strategyExecutionRun.count({ where: { status: "completed" } }),
      db.strategyExecutionRun.findFirst({
        where: { status: "completed" },
        orderBy: { startedAt: "desc" },
        select: { startedAt: true },
      }),
    ]).catch(() => {
      // 如果数据库中没有数据或表不存在，返回空统计
      return [0, [], [], 0, 0, 0, null] as const;
    });

  return {
    totalStrategies,
    byStatus: Object.fromEntries(
      (byStatus as Array<{ status: string; _count: { status: number } }>).map((g) => [
        g.status,
        g._count.status,
      ]),
    ),
    byType: Object.fromEntries(
      (byType as Array<{ type: string; _count: { type: number } }>).map((g) => [g.type, g._count.type]),
    ),
    activeTasks,
    totalExecutions,
    completedExecutions,
    lastExecutionAt: lastExecution && "startedAt" in lastExecution && lastExecution.startedAt
      ? new Date(lastExecution.startedAt as unknown as string | Date).toISOString()
      : null,
  };
}

// ============================================================================
// 用户上下文业务数据 (User Profile & Connectivity Precipitation)
// ============================================================================

export interface UserContextBusinessStats {
  totalUsers: number;
  verifiedUsers: number;
  usersWithStrategies: number;
  usersWithApiConfigs: number;
  verifiedApiConfigs: number;
  totalApiConfigs: number;
  totalChannelConfigs: number;
  activeTradingUsers: number;
  creditsTotalBalance: number;
  totalOrders: number;
}

export async function getUserContextBusinessStats(): Promise<UserContextBusinessStats> {
  const db = getPrisma();

  const [
    totalUsers,
    verifiedUsers,
    usersWithStrategies,
    usersWithApiConfigs,
    verifiedApiConfigs,
    totalApiConfigs,
    totalChannelConfigs,
    activeTradingUsers,
    creditsAccounts,
    totalOrders,
  ] = await Promise.all([
    db.user.count(),
    db.user.count({ where: { emailVerified: true } }),
    db.user.count({ where: { strategies: { some: {} } } }),
    db.user.count({ where: { apiConfigs: { some: {} } } }),
    db.apiConfig.count({ where: { isVerified: true } }),
    db.apiConfig.count(),
    db.channelConfig.count(),
    db.tradingParams.count({ where: { status: "ACTIVE" } }),
    db.creditsAccount.aggregate({ _sum: { balance: true } }),
    db.order.count(),
  ]).catch(() => {
    return [0, 0, 0, 0, 0, 0, 0, 0, { _sum: { balance: 0 } }, 0] as const;
  });

  return {
    totalUsers,
    verifiedUsers,
    usersWithStrategies,
    usersWithApiConfigs,
    verifiedApiConfigs,
    totalApiConfigs,
    totalChannelConfigs,
    activeTradingUsers,
    creditsTotalBalance: creditsAccounts && "_sum" in creditsAccounts && creditsAccounts._sum.balance
      ? Number(creditsAccounts._sum.balance)
      : 0,
    totalOrders,
  };
}

// ============================================================================
// 交易链路业务数据 (Trading Pipeline Precipitation)
// ============================================================================

export interface TradingBusinessStats {
  todayLoss: number;
  totalLoss: number;
  totalTradeCount: number;
  todayTradeCount: number;
  activeTradingParams: number;
}

export async function getTradingBusinessStats(): Promise<TradingBusinessStats> {
  const db = getPrisma();

  const tradingParamsList = await db.tradingParams.findMany({
    select: {
      todayLoss: true,
      totalLoss: true,
      totalTradeCount: true,
      todayTradeCount: true,
      status: true,
    },
  }).catch(() => []);

  let todayLoss = 0;
  let totalLoss = 0;
  let totalTradeCount = 0;
  let todayTradeCount = 0;
  let activeTradingParams = 0;

  for (const tp of tradingParamsList) {
    todayLoss += Number(tp.todayLoss) || 0;
    totalLoss += Number(tp.totalLoss) || 0;
    totalTradeCount += Number(tp.totalTradeCount) || 0;
    todayTradeCount += Number(tp.todayTradeCount) || 0;
    if (tp.status === "ACTIVE") activeTradingParams++;
  }

  return {
    todayLoss,
    totalLoss,
    totalTradeCount,
    todayTradeCount,
    activeTradingParams,
  };
}

// ============================================================================
// 综合业务数据沉淀视图 (Combined View for UI)
// ============================================================================

export interface BusinessDataPrecipitationView {
  strategies: StrategyBusinessStats | null;
  userContext: UserContextBusinessStats | null;
  trading: TradingBusinessStats | null;
  aggregatedAt: string;
}

export async function getBusinessDataView(): Promise<BusinessDataPrecipitationView> {
  try {
    const [strategies, userContext, trading] = await Promise.all([
      getStrategyBusinessStats(),
      getUserContextBusinessStats(),
      getTradingBusinessStats(),
    ]);

    return {
      strategies,
      userContext,
      trading,
      aggregatedAt: new Date().toISOString(),
    };
  } catch (error) {
    console.warn("[BusinessDataHub] 数据库访问失败 (可能未部署):", error instanceof Error ? error.message : String(error));
    return {
      strategies: null,
      userContext: null,
      trading: null,
      aggregatedAt: new Date().toISOString(),
    };
  }
}
