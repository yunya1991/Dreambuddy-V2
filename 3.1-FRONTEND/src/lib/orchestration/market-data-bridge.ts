/**
 * 市场数据桥接层
 *
 * 封装 fetchMarketData，提供统一的技能数据获取接口。
 */

import { fetchMarketData, type MarketData } from '@/lib/market-data-adapter';

export type { MarketData };

export interface MarketDataContext {
  /** 原始符号，如 BTC / GOLD / STOCK_US */
  symbol: string;
  /** OKX 合约代码（仅 crypto 用） */
  instId: string;
  /** 市场类别 */
  category: 'crypto' | 'macro';
  /** 显示名 */
  displayName: string;
  /** Tavily 搜索 query（macro 用） */
  tavilyQuery?: string;
  /** 语言 */
  lang?: 'zh' | 'en';
}

/**
 * 获取市场数据（统一入口）
 *
 * 复用 market-data-adapter 的 fetchMarketData，
 * crypto 走 OKX CLI，macro 走 Tavily。
 */
export async function getMarketData(ctx: MarketDataContext): Promise<MarketData> {
  return fetchMarketData(
    ctx.symbol,
    ctx.instId,
    ctx.category,
    ctx.displayName,
    ctx.tavilyQuery,
    ctx.lang || 'zh',
  );
}

/**
 * 从符号提取市场数据上下文
 * 辅助函数：从用户消息中提取符号信息并构建上下文
 */
export function buildMarketDataContext(
  symbol: string,
  instId: string,
  category: 'crypto' | 'macro',
  displayName: string,
  tavilyQuery?: string,
): MarketDataContext {
  return { symbol, instId, category, displayName, tavilyQuery };
}
