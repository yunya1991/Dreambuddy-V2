/**
 * S1_调研 步骤实现
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 * 职责: 市场数据、行情、技术指标、新闻收集
 */

import type {
  S1ResearchInput,
  S1ResearchOutput,
} from "../types";

/**
 * 获取市场基础数据
 */
async function fetchMarketData(symbol: string): Promise<{
  price: number;
  change24h: number;
  high24h: number;
  low24h: number;
  volume: number;
}> {
  // TODO: 集成真实市场数据API
  // 目前返回模拟数据
  return {
    price: symbol.includes("BTC") ? 67500 : symbol.includes("ETH") ? 3450 : 100,
    change24h: 2.35,
    high24h: 68000,
    low24h: 66000,
    volume: 28500000000,
  };
}

/**
 * 获取技术指标
 */
async function fetchTechnicalIndicators(symbol: string): Promise<{
  rsi: number;
  macd: { value: number; signal: number; histogram: number };
  trend: "bullish" | "bearish" | "neutral";
}> {
  // TODO: 集成技术分析API
  // 目前返回模拟数据
  const rsi = 58.5;
  const macdValue = 125.3;
  const signal = 118.7;
  const histogram = macdValue - signal;

  let trend: "bullish" | "bearish" | "neutral" = "neutral";
  if (rsi > 60 && macdValue > signal) {
    trend = "bullish";
  } else if (rsi < 40 && macdValue < signal) {
    trend = "bearish";
  }

  return {
    rsi,
    macd: {
      value: macdValue,
      signal,
      histogram,
    },
    trend,
  };
}

/**
 * 获取支撑阻力位
 */
async function fetchSupportResistance(symbol: string): Promise<{
  support: string;
  resistance: string;
}> {
  // TODO: 集成支撑阻力计算
  // 目前返回模拟数据
  const price = symbol.includes("BTC") ? 67500 : symbol.includes("ETH") ? 3450 : 100;

  return {
    support: `${(price * 0.97).toFixed(2)}`,
    resistance: `${(price * 1.03).toFixed(2)}`,
  };
}

/**
 * 获取情绪数据
 */
async function fetchSentimentData(symbol: string): Promise<{
  fearGreedIndex?: number;
  fundingRate?: number;
}> {
  // TODO: 集成情绪数据API
  return {
    fearGreedIndex: 62,
    fundingRate: 0.01,
  };
}

/**
 * 生成调研摘要
 */
function generateSummary(
  data: {
    symbol: string;
    displayName: string;
    price: number;
    change24h: number;
    support: string;
    resistance: string;
    indicators: {
      rsi: number;
      trend: "bullish" | "bearish" | "neutral";
    };
    sentiment?: {
      fearGreedIndex?: number;
    };
  }
): string {
  const trendText = {
    bullish: "多头趋势",
    bearish: "空头趋势",
    neutral: "震荡整理",
  }[data.indicators.trend];

  const sentimentText = data.sentiment?.fearGreedIndex
    ? data.sentiment.fearGreedIndex > 60
      ? "市场情绪偏贪婪"
      : data.sentiment.fearGreedIndex < 40
        ? "市场情绪偏恐慌"
        : "市场情绪中性"
    : "";

  return `${data.displayName}当前价格$${data.price.toFixed(2)}，24h${data.change24h > 0 ? "上涨" : "下跌"}${Math.abs(data.change24h).toFixed(2)}%。` +
    `技术面呈现${trendText}，RSI指标${data.indicators.rsi.toFixed(1)}处于中性区域。` +
    `当前支撑位${data.support}，阻力位${data.resistance}。${sentimentText}`;
}

/**
 * 执行S1调研
 */
export async function executeS1Research(
  input: S1ResearchInput
): Promise<S1ResearchOutput> {
  const { symbol, displayName } = input;

  // 并行获取所有数据
  const [marketData, indicators, supportResistance, sentiment] = await Promise.all([
    fetchMarketData(symbol),
    fetchTechnicalIndicators(symbol),
    fetchSupportResistance(symbol),
    fetchSentimentData(symbol),
  ]);

  // 生成摘要
  const summary = generateSummary({
    symbol,
    displayName,
    price: marketData.price,
    change24h: marketData.change24h,
    support: supportResistance.support,
    resistance: supportResistance.resistance,
    indicators,
    sentiment,
  });

  return {
    symbol,
    displayName,
    price: marketData.price,
    priceChange24h: marketData.change24h,
    support: supportResistance.support,
    resistance: supportResistance.resistance,
    indicators,
    sentiment,
    summary,
  };
}

/**
 * 格式化调研结果为Markdown
 */
export function formatS1ResearchResult(
  output: S1ResearchOutput
): string {
  const trendEmoji = {
    bullish: "📈",
    bearish: "📉",
    neutral: "➡️",
  }[output.indicators.trend];

  const trendText = {
    bullish: "多头",
    bearish: "空头",
    neutral: "中性",
  }[output.indicators.trend];

  const sentimentText = output.sentiment?.fearGreedIndex
    ? output.sentiment.fearGreedIndex > 60
      ? "🟢 贪婪"
      : output.sentiment.fearGreedIndex < 40
        ? "🔴 恐慌"
        : "🟡 中性"
    : "暂无数据";

  return `## 🔍 S1_调研结果

### 市场现状
- **标的**: ${output.displayName} (${output.symbol})
- **当前价格**: $${output.price.toFixed(2)}
- **24h变化**: ${output.priceChange24h > 0 ? "+" : ""}${output.priceChange24h.toFixed(2)}%

### 技术指标
- **趋势**: ${trendEmoji} ${trendText}
- **RSI**: ${output.indicators.rsi.toFixed(1)} (${output.indicators.rsi > 70 ? "超买" : output.indicators.rsi < 30 ? "超卖" : "中性"})
- **MACD**: ${output.indicators.macd.value.toFixed(2)} (信号: ${output.indicators.macd.signal.toFixed(2)}, 直方图: ${output.indicators.macd.histogram.toFixed(2)})

### 关键价位
- **支撑位**: $${output.support}
- **阻力位**: $${output.resistance}

### 情绪指标
- **恐慌贪婪指数**: ${sentimentText}${output.sentiment?.fearGreedIndex ? ` (${output.sentiment.fearGreedIndex})` : ""}
${output.sentiment?.fundingRate ? `- **资金费率**: ${(output.sentiment.fundingRate * 100).toFixed(3)}%` : ""}

---

**调研摘要**: ${output.summary}`;
}
