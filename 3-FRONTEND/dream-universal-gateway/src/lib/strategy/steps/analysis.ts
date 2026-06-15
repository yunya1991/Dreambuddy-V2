/**
 * S2_分析 步骤实现
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 * 职责: 多维度分析（技术面、基本面、情绪面）
 */

import type {
  S2AnalysisInput,
  S2AnalysisOutput,
} from "../types";

/**
 * 分析短期趋势
 */
function analyzeShortTermTrend(
  rsi: number,
  macdHistogram: number,
  priceChange24h: number
): "bullish" | "bearish" | "neutral" {
  let score = 0;

  // RSI分析
  if (rsi > 60) score += 1;
  else if (rsi < 40) score -= 1;

  // MACD分析
  if (macdHistogram > 0) score += 1;
  else if (macdHistogram < 0) score -= 1;

  // 24h变化分析
  if (priceChange24h > 2) score += 1;
  else if (priceChange24h < -2) score -= 1;

  if (score > 0) return "bullish";
  if (score < 0) return "bearish";
  return "neutral";
}

/**
 * 分析中期趋势
 */
function analyzeMediumTermTrend(
  indicators: { rsi: number; macd: { value: number; signal: number } }
): "bullish" | "bearish" | "neutral" {
  let score = 0;

  // RSI分析（中期看50基准线）
  if (indicators.rsi > 55) score += 1;
  else if (indicators.rsi < 45) score -= 1;

  // MACD分析
  if (indicators.macd.value > indicators.macd.signal) score += 1;
  else if (indicators.macd.value < indicators.macd.signal) score -= 1;

  if (score > 0) return "bullish";
  if (score < 0) return "bearish";
  return "neutral";
}

/**
 * 分析长期趋势
 */
function analyzeLongTermTrend(
  indicators: { rsi: number }
): "bullish" | "bearish" | "neutral" {
  // 长期趋势基于RSI的移动平均
  const rsi = indicators.rsi;

  if (rsi > 55) return "bullish";
  if (rsi < 45) return "bearish";
  return "neutral";
}

/**
 * 计算关键价位
 */
function calculateKeyLevels(
  support: string,
  resistance: string,
  price: number
): {
  entryRange: string;
  stopLoss: string;
  takeProfit: string;
} {
  const supportNum = parseFloat(support);
  const resistanceNum = parseFloat(resistance);
  const midPoint = (supportNum + resistanceNum) / 2;

  // 入场区间：支撑位上方到中间价位
  const entryRange = `${(supportNum * 1.005).toFixed(2)} - ${midPoint.toFixed(2)}`;

  // 止损位：支撑位下方1-2%
  const stopLoss = (supportNum * 0.98).toFixed(2);

  // 止盈位：阻力位上方
  const takeProfit = (resistanceNum * 1.02).toFixed(2);

  return {
    entryRange,
    stopLoss,
    takeProfit,
  };
}

/**
 * 识别风险因素
 */
function identifyRisks(
  rsi: number,
  sentiment?: { fearGreedIndex?: number; fundingRate?: number }
): string[] {
  const risks: string[] = [];

  // RSI风险
  if (rsi > 70) {
    risks.push("RSI超买，可能面临回调风险");
  } else if (rsi < 30) {
    risks.push("RSI超卖，可能存在反弹机会但也可能是下跌趋势");
  }

  // 情绪风险
  if (sentiment?.fearGreedIndex && sentiment.fearGreedIndex > 75) {
    risks.push("市场极度贪婪，回调风险较高");
  } else if (sentiment?.fearGreedIndex && sentiment.fearGreedIndex < 25) {
    risks.push("市场极度恐慌，可能存在恐慌性抛售");
  }

  // 资金费率风险
  if (sentiment?.fundingRate && sentiment.fundingRate > 0.05) {
    risks.push("资金费率偏高，多头成本较大");
  } else if (sentiment?.fundingRate && sentiment.fundingRate < -0.05) {
    risks.push("资金费率为负，空头成本较大");
  }

  // 如果没有明显风险
  if (risks.length === 0) {
    risks.push("市场未显示明显风险信号");
  }

  return risks;
}

/**
 * 计算分析置信度
 */
function calculateConfidence(
  indicators: { rsi: number; trend: "bullish" | "bearish" | "neutral" },
  sentiment?: { fearGreedIndex?: number }
): number {
  let confidence = 50; // 基础置信度

  // RSI信号强度
  const rsiDistance = Math.abs(indicators.rsi - 50);
  if (rsiDistance > 20) confidence += 15;
  else if (rsiDistance > 10) confidence += 8;

  // 情绪数据完整性
  if (sentiment?.fearGreedIndex) {
    confidence += 10;
  }

  // 趋势一致性
  if (
    (indicators.trend === "bullish" && indicators.rsi > 55) ||
    (indicators.trend === "bearish" && indicators.rsi < 45)
  ) {
    confidence += 15;
  }

  return Math.min(confidence, 95);
}

/**
 * 生成分析结论
 */
function generateConclusion(
  trend: {
    shortTerm: "bullish" | "bearish" | "neutral";
    mediumTerm: "bullish" | "bearish" | "neutral";
    longTerm: "bullish" | "bearish" | "neutral";
  },
  confidence: number,
  price: number,
  stopLoss: string,
  takeProfit: string
): string {
  const bullishCount = [trend.shortTerm, trend.mediumTerm, trend.longTerm]
    .filter(t => t === "bullish").length;
  const bearishCount = [trend.shortTerm, trend.mediumTerm, trend.longTerm]
    .filter(t => t === "bearish").length;

  const riskReward = ((parseFloat(takeProfit) - price) / (price - parseFloat(stopLoss))).toFixed(2);

  if (bullishCount >= 2) {
    return `综合分析显示${bullishCount}/3周期呈多头信号，置信度${confidence}%。` +
      `建议关注${stopLoss}-${takeProfit}区间，盈亏比约1:${riskReward}。`;
  } else if (bearishCount >= 2) {
    return `综合分析显示${bearishCount}/3周期呈空头信号，置信度${confidence}%。` +
      `当前观望为主，若跌破${stopLoss}则考虑顺势做空。`;
  } else {
    return `多空信号均衡，市场处于震荡格局，置信度${confidence}%。` +
      `建议区间操作，高抛低吸。`;
  }
}

/**
 * 执行S2分析
 */
export async function executeS2Analysis(
  input: S2AnalysisInput
): Promise<S2AnalysisOutput> {
  const {
    price,
    priceChange24h,
    support,
    resistance,
    indicators,
    sentiment,
    displayName,
  } = input;

  // 趋势分析
  const trend = {
    shortTerm: analyzeShortTermTrend(
      indicators.rsi,
      indicators.macd.histogram,
      priceChange24h
    ),
    mediumTerm: analyzeMediumTermTrend(indicators),
    longTerm: analyzeLongTermTrend(indicators),
  };

  // 关键价位
  const keyLevels = calculateKeyLevels(support, resistance, price);

  // 风险识别
  const risks = identifyRisks(indicators.rsi, sentiment);

  // 置信度
  const confidence = calculateConfidence(indicators, sentiment);

  // 结论
  const conclusion = generateConclusion(trend, confidence, price, keyLevels.stopLoss, keyLevels.takeProfit);

  return {
    trend,
    keyLevels,
    risks,
    confidence,
    conclusion,
  };
}

/**
 * 格式化分析结果为Markdown
 */
export function formatS2AnalysisResult(
  output: S2AnalysisOutput,
  context: {
    symbol: string;
    displayName: string;
    price: number;
    support: string;
    resistance: string;
  }
): string {
  const trendEmoji = {
    bullish: "📈",
    bearish: "📉",
    neutral: "➡️",
  };

  const trendText = {
    bullish: "多头",
    bearish: "空头",
    neutral: "中性",
  };

  return `## 🧠 S2_分析结论

### 趋势判断
| 周期 | 方向 | 信号 |
|------|------|------|
| 短期 | ${trendEmoji[output.trend.shortTerm]} ${trendText[output.trend.shortTerm]} | ${output.trend.shortTerm === "bullish" ? "买入信号" : output.trend.shortTerm === "bearish" ? "卖出信号" : "观望"} |
| 中期 | ${trendEmoji[output.trend.mediumTerm]} ${trendText[output.trend.mediumTerm]} | ${output.trend.mediumTerm === "bullish" ? "买入信号" : output.trend.mediumTerm === "bearish" ? "卖出信号" : "观望"} |
| 长期 | ${trendEmoji[output.trend.longTerm]} ${trendText[output.trend.longTerm]} | ${output.trend.longTerm === "bullish" ? "买入信号" : output.trend.longTerm === "bearish" ? "卖出信号" : "观望"} |

### 关键价位
- **入场区间**: $${output.keyLevels.entryRange}
- **止损位**: $${output.keyLevels.stopLoss} (跌破需离场)
- **止盈位**: $${output.keyLevels.takeProfit}

### 风险因素
${output.risks.map(r => `- ⚠️ ${r}`).join("\n")}

### 分析置信度
**${output.confidence}%**

---

**分析结论**: ${output.conclusion}`;
}
