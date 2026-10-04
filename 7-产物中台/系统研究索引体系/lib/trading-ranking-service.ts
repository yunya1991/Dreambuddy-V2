// ============================================================================
// 交易榜单服务 (Trading Ranking Service)
// 每日 Top10 交易机会榜单的业务逻辑层
// 数据源：Prisma SQLite（trading_rankings / ranking_monitors 表）
// 降级策略：数据库不可用时返回空数组/零值指标（遵循产物中台容错原则）
// ============================================================================

import { PrismaClient } from "@prisma/client";

let prismaInstance: PrismaClient | null = null;

function getPrisma(): PrismaClient {
  if (!prismaInstance) {
    prismaInstance = new PrismaClient({ log: [] });
  }
  return prismaInstance;
}

// ============================================================================
// 类型定义
// ============================================================================

export interface DecisionCard {
  entry: {
    price: number;
    range: [number, number];
    batches: { price: number; ratio: number }[];
  };
  stopLoss: number;
  takeProfit: number[];
  events: { date: string; name: string; impact: string }[];
  riskLevel: "novice" | "intermediate" | "expert";
  historicalAnalogy: string;
  logic: {
    bullish: string[];
    bearish: string[];
    confidence: number;
  };
}

export interface TradingRankingItem {
  rank: number;
  symbol: string;
  category: "crypto" | "commodity" | "index";
  score: number;
  signal: "STRONG_BUY" | "BUY" | "WEAK_BUY" | "NEUTRAL" | "WEAK_SELL" | "SELL" | "STRONG_SELL";
  confidence: number;
  decisionCard: DecisionCard;
  date: string;
}

export interface RankingMonitorMetrics {
  date: string;
  satisfaction: number | null;
  conversionRate: number | null;
  abandonRate: number | null;
  pushReachRate: number | null;
  unsubscribeRate: number | null;
  matu: number | null;
  kFactor: number | null;
}

// ============================================================================
// 查询函数
// ============================================================================

/**
 * 获取今日 Top10 交易榜单
 * 降级策略：
 *   1. 今日有数据 → 返回今日 Top10
 *   2. 今日无数据 → 回退到最近一个有数据的日期（FAIL-OPEN，避免页面降级到 mock）
 *   3. 数据库不可用 → 返回空数组
 */
export async function getTodayRanking(): Promise<TradingRankingItem[]> {
  const db = getPrisma();
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  try {
    // 1. 先查今日
    let records = await db.tradingRanking.findMany({
      where: {
        date: { gte: today },
      },
      orderBy: { rank: "asc" },
      take: 10,
    });

    // 2. 今日无数据 → 回退到最近一个有数据的日期
    if (records.length === 0) {
      const latest = await db.tradingRanking.findFirst({
        orderBy: { date: "desc" },
        select: { date: true },
      });
      if (latest) {
        const latestDate = new Date(latest.date);
        latestDate.setHours(0, 0, 0, 0);
        const nextDay = new Date(latestDate);
        nextDay.setDate(nextDay.getDate() + 1);
        records = await db.tradingRanking.findMany({
          where: {
            date: { gte: latestDate, lt: nextDay },
          },
          orderBy: { rank: "asc" },
          take: 10,
        });
      }
    }

    return records.map(toTradingRankingItem);
  } catch {
    return [];
  }
}

/**
 * 按日期查询历史榜单
 * @param dateStr 日期字符串 YYYY-MM-DD
 */
export async function getHistoryRanking(dateStr: string): Promise<TradingRankingItem[]> {
  const db = getPrisma();
  const targetDate = new Date(dateStr);
  targetDate.setHours(0, 0, 0, 0);
  const nextDay = new Date(targetDate);
  nextDay.setDate(nextDay.getDate() + 1);

  try {
    const records = await db.tradingRanking.findMany({
      where: {
        date: { gte: targetDate, lt: nextDay },
      },
      orderBy: { rank: "asc" },
      take: 10,
    });

    return records.map(toTradingRankingItem);
  } catch {
    return [];
  }
}

/**
 * 获取监控指标（默认今日，可指定日期）
 */
export async function getMonitorMetrics(dateStr?: string): Promise<RankingMonitorMetrics> {
  const db = getPrisma();
  const targetDate = dateStr ? new Date(dateStr) : new Date();
  targetDate.setHours(0, 0, 0, 0);
  const nextDay = new Date(targetDate);
  nextDay.setDate(nextDay.getDate() + 1);

  try {
    const record = await db.rankingMonitor.findFirst({
      where: {
        date: { gte: targetDate, lt: nextDay },
      },
      orderBy: { date: "desc" },
    });

    if (!record) {
      return emptyMetrics(targetDate);
    }

    return {
      date: record.date.toISOString().slice(0, 10),
      satisfaction: record.satisfaction,
      conversionRate: record.conversionRate,
      abandonRate: record.abandonRate,
      pushReachRate: record.pushReachRate,
      unsubscribeRate: record.unsubscribeRate,
      matu: record.matu,
      kFactor: record.kFactor,
    };
  } catch {
    return emptyMetrics(targetDate);
  }
}

// ============================================================================
// 写入函数
// ============================================================================

/**
 * 持久化榜单（用于 trigger 路由调用）
 * 先删除当日旧数据，再写入新数据
 */
export async function saveRanking(items: TradingRankingItem[]): Promise<{ success: boolean; count: number }> {
  if (!items || items.length === 0) {
    return { success: false, count: 0 };
  }

  const db = getPrisma();
  const dateStr = items[0].date;
  const targetDate = new Date(dateStr);
  targetDate.setHours(0, 0, 0, 0);
  const nextDay = new Date(targetDate);
  nextDay.setDate(nextDay.getDate() + 1);

  try {
    // 先删除当日旧数据
    await db.tradingRanking.deleteMany({
      where: { date: { gte: targetDate, lt: nextDay } },
    });

    // 批量写入新数据
    await db.tradingRanking.createMany({
      data: items.map((item) => ({
        date: new Date(item.date),
        rank: item.rank,
        symbol: item.symbol,
        category: item.category,
        score: item.score,
        signal: item.signal,
        confidence: item.confidence,
        decisionCard: item.decisionCard as object,
      })),
    });

    return { success: true, count: items.length };
  } catch (error) {
    console.error("[trading-ranking-service] saveRanking failed:", error);
    return { success: false, count: 0 };
  }
}

// ============================================================================
// 辅助函数
// ============================================================================

function toTradingRankingItem(record: {
  rank: number;
  symbol: string;
  category: string;
  score: number;
  signal: string;
  confidence: number;
  decisionCard: unknown;
  date: Date;
}): TradingRankingItem {
  return {
    rank: record.rank,
    symbol: record.symbol,
    category: record.category as TradingRankingItem["category"],
    score: record.score,
    signal: record.signal as TradingRankingItem["signal"],
    confidence: record.confidence,
    decisionCard: record.decisionCard as DecisionCard,
    date: record.date.toISOString().slice(0, 10),
  };
}

function emptyMetrics(date: Date): RankingMonitorMetrics {
  return {
    date: date.toISOString().slice(0, 10),
    satisfaction: null,
    conversionRate: null,
    abandonRate: null,
    pushReachRate: null,
    unsubscribeRate: null,
    matu: null,
    kFactor: null,
  };
}
