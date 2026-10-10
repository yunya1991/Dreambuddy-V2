/**
 * market-data-fetcher.ts — 大模型市场数据注入工具
 * 从 /api/data/market 获取实时价格+资金费率+恐惧贪婪+多空比
 * 注入到 LLM prompt，不依赖子系统输出
 */

export interface MarketMetrics {
  symbol: string;
  price?: number;
  change24h?: number;
  high24h?: number;
  low24h?: number;
  funding_rate?: number;
  funding_rate_annualized?: number;
  fear_greed?: number;
  fear_greed_classification?: string;
  long_short_ratio?: number;
  long_account_pct?: number;
  short_account_pct?: number;
  timestamp?: string;
  degraded?: boolean;
}

let cache: { data: MarketMetrics; ts: number } | null = null;
const CACHE_TTL = 10_000; // 10秒缓存

export async function fetchMarketMetrics(symbol: string = 'BTC'): Promise<MarketMetrics> {
  const now = Date.now();
  if (cache && now - cache.ts < CACHE_TTL && cache.data.symbol === symbol.toUpperCase()) {
    return cache.data;
  }

  try {
    const res = await fetch(`/api/data/market?symbol=${encodeURIComponent(symbol)}`, {
      next: { revalidate: 10 },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = (await res.json()) as MarketMetrics;
    cache = { data, ts: now };
    return data;
  } catch (e) {
    return { symbol: symbol.toUpperCase(), degraded: true };
  }
}

/**
 * 格式化为 LLM 注入文本
 */
export function formatMarketMetricsForLLM(m: MarketMetrics, lang: string = 'zh'): string {
  if (!m || m.degraded) {
    return lang === 'zh' ? '\n（市场指标数据暂不可用）\n' : '\n(Market metrics unavailable)\n';
  }

  const lines: string[] = [];

  if (lang === 'zh') {
    lines.push('--- 实时市场数据（直接注入，非子系统输出）---');
    if (m.price !== undefined) {
      lines.push(`当前价格: $${m.price.toLocaleString()}`);
    }
    if (m.change24h !== undefined) {
      lines.push(`24h涨跌: ${m.change24h >= 0 ? '+' : ''}${m.change24h.toFixed(2)}%`);
    }
    if (m.funding_rate !== undefined) {
      lines.push(`资金费率: ${m.funding_rate.toFixed(4)}% (年化 ${m.funding_rate_annualized?.toFixed(2) || 'N/A'}%)`);
    }
    if (m.fear_greed !== undefined) {
      lines.push(`恐惧贪婪指数: ${m.fear_greed.toFixed(0)} (${m.fear_greed_classification || 'N/A'})`);
    }
    if (m.long_short_ratio !== undefined) {
      lines.push(`多空比: ${m.long_short_ratio.toFixed(2)} (多${m.long_account_pct?.toFixed(1)}% / 空${m.short_account_pct?.toFixed(1)}%)`);
    }
    lines.push(`数据来源: OKX+DAL | 更新时间: ${m.timestamp || 'N/A'}`);
  } else {
    lines.push('--- Real-time Market Data (injected directly) ---');
    if (m.price !== undefined) {
      lines.push(`Current Price: $${m.price.toLocaleString()}`);
    }
    if (m.change24h !== undefined) {
      lines.push(`24h Change: ${m.change24h >= 0 ? '+' : ''}${m.change24h.toFixed(2)}%`);
    }
    if (m.funding_rate !== undefined) {
      lines.push(`Funding Rate: ${m.funding_rate.toFixed(4)}% (Annualized ${m.funding_rate_annualized?.toFixed(2) || 'N/A'}%)`);
    }
    if (m.fear_greed !== undefined) {
      lines.push(`Fear & Greed: ${m.fear_greed.toFixed(0)} (${m.fear_greed_classification || 'N/A'})`);
    }
    if (m.long_short_ratio !== undefined) {
      lines.push(`Long/Short Ratio: ${m.long_short_ratio.toFixed(2)} (Long ${m.long_account_pct?.toFixed(1)}% / Short ${m.short_account_pct?.toFixed(1)}%)`);
    }
    lines.push(`Source: OKX+DAL | Updated: ${m.timestamp || 'N/A'}`);
  }

  return lines.join('\n');
}
