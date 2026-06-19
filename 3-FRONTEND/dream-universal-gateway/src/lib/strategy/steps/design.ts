/**
 * S3_设计 步骤实现
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 * 职责: 制定具体策略（入场点、止损、止盈、仓位）
 */

import type {
  S3DesignInput,
  S3DesignOutput,
} from "../types";

/**
 * 生成策略名称
 */
function generateStrategyName(
  trend: { shortTerm: string; mediumTerm: string },
  symbol: string
): string {
  const baseName = symbol.includes("BTC")
    ? "BTC"
    : symbol.includes("ETH")
      ? "ETH"
      : symbol;

  const trendDirection = trend.shortTerm === "bullish" ? "顺势做多" : trend.shortTerm === "bearish" ? "顺势做空" : "区间震荡";

  return `${baseName} ${trendDirection}策略`;
}

/**
 * 规划入场计划
 */
function planEntry(
  entryRange: string,
  riskTolerance: "low" | "medium" | "high",
  currentPrice: number
): {
  entryPoint: string;
  positionSize: number;
  addRules: string;
} {
  // 根据风险承受能力确定仓位
  const positionSizes = {
    low: 15,      // 低风险：15%仓位
    medium: 30,   // 中风险：30%仓位
    high: 50,     // 高风险：50%仓位
  };

  // 计算入场点（取区间中间偏下）
  const [minEntry] = entryRange.split(" - ").map(v => parseFloat(v));
  const entryPoint = (minEntry * 1.002).toFixed(2);

  // 加仓规则
  const addRules = riskTolerance === "high"
    ? "首次买入30%，回调2%加仓20%，再回调2%加仓最后10%"
    : riskTolerance === "medium"
      ? "首次买入50%，回调2%加仓30%，剩余留作备用"
      : "一次性买入60%，不追加仓位";

  return {
    entryPoint,
    positionSize: positionSizes[riskTolerance],
    addRules,
  };
}

/**
 * 制定风险管理
 */
function planRiskManagement(
  stopLoss: string,
  takeProfit: string,
  entryPrice: number
): {
  stopLoss: string;
  takeProfit: string;
  riskRewardRatio: string;
} {
  const sl = parseFloat(stopLoss);
  const tp = parseFloat(takeProfit);
  const risk = entryPrice - sl;
  const reward = tp - entryPrice;
  const ratio = (reward / risk).toFixed(2);

  return {
    stopLoss: stopLoss,
    takeProfit: takeProfit,
    riskRewardRatio: `1:${ratio}`,
  };
}

/**
 * 生成情景推演
 */
function generateScenarios(
  trend: { shortTerm: string; mediumTerm: string },
  entryPoint: string,
  stopLoss: string,
  takeProfit: string
): Array<{
  scenario: string;
  probability: number;
  outcome: string;
}> {
  const scenarios: Array<{
    scenario: string;
    probability: number;
    outcome: string;
  }> = [];

  if (trend.shortTerm === "bullish") {
    scenarios.push(
      {
        scenario: "乐观情景",
        probability: 0.4,
        outcome: `价格突破${takeProfit}，达到止盈位，收益约${((parseFloat(takeProfit) - parseFloat(entryPoint)) / parseFloat(entryPoint) * 100).toFixed(1)}%`,
      },
      {
        scenario: "中性情景",
        probability: 0.35,
        outcome: `价格在${stopLoss}-${takeProfit}区间震荡，小幅盈利或保本`,
      },
      {
        scenario: "悲观情景",
        probability: 0.25,
        outcome: `价格跌破${stopLoss}止损离场，损失约${((parseFloat(entryPoint) - parseFloat(stopLoss)) / parseFloat(entryPoint) * 100).toFixed(1)}%`,
      }
    );
  } else if (trend.shortTerm === "bearish") {
    scenarios.push(
      {
        scenario: "乐观情景",
        probability: 0.3,
        outcome: `价格继续下跌至更低，收益超过预期止盈`,
      },
      {
        scenario: "中性情景",
        probability: 0.4,
        outcome: `价格在区间内震荡，选择合适点位平仓`,
      },
      {
        scenario: "悲观情景",
        probability: 0.3,
        outcome: `价格反弹至止损位离场，损失控制在预期内`,
      }
    );
  } else {
    scenarios.push(
      {
        scenario: "区间突破",
        probability: 0.3,
        outcome: `价格向上突破${takeProfit}，顺势跟进`,
      },
      {
        scenario: "区间震荡",
        probability: 0.4,
        outcome: `在${stopLoss}-${takeProfit}区间高抛低吸`,
      },
      {
        scenario: "区间破位",
        probability: 0.3,
        outcome: `价格向下突破${stopLoss}，止损离场`,
      }
    );
  }

  return scenarios;
}

/**
 * 情景类型
 */
interface Scenario {
  scenario: string;
  probability: number;
  outcome: string;
}

/**
 * 计算策略置信度
 */
function calculateStrategyConfidence(
  analysisConfidence: number,
  scenarios: Scenario[]
): number {
  // 策略置信度基于分析置信度和情景概率分布
  const optimisticProb = scenarios.find(s => s.scenario.includes("乐观") || s.scenario.includes("突破"))?.probability ?? 0.3;
  const baseConfidence = analysisConfidence * 0.7 + optimisticProb * 30;

  return Math.min(Math.round(baseConfidence), 95);
}

/**
 * 执行S3设计
 */
export async function executeS3Design(
  input: S3DesignInput
): Promise<S3DesignOutput> {
  const {
    keyLevels,
    trend,
    confidence: analysisConfidence,
    userPreferences,
  } = input;

  const {
    symbol,
    displayName,
    price,
    support,
    resistance,
  } = input as any;

  // 风险承受能力
  const riskTolerance = userPreferences?.riskTolerance ?? "medium";

  // 生成策略名称
  const strategyName = generateStrategyName(trend, symbol);

  // 入场计划
  const entryPlan = planEntry(keyLevels.entryRange, riskTolerance, price);

  // 风险管理
  const riskManagement = planRiskManagement(
    keyLevels.stopLoss,
    keyLevels.takeProfit,
    parseFloat(entryPlan.entryPoint)
  );

  // 情景推演
  const scenarios = generateScenarios(
    trend,
    entryPlan.entryPoint,
    keyLevels.stopLoss,
    keyLevels.takeProfit
  );

  // 策略置信度
  const confidence = calculateStrategyConfidence(analysisConfidence, scenarios);

  return {
    strategyName,
    entryPlan,
    riskManagement,
    scenarios,
    confidence,
  };
}

/**
 * 格式化策略设计结果为Markdown
 */
export function formatS3DesignResult(
  output: S3DesignOutput,
  context?: { symbol: string; displayName: string }
): string {
  return `## 🎯 S3_策略方案

### 策略名称
**${output.strategyName}**

### 入场计划
- **入场点**: $${output.entryPlan.entryPoint}
- **仓位**: ${output.entryPlan.positionSize}%
- **加仓规则**: ${output.entryPlan.addRules}

### 风险管理
| 参数 | 值 |
|------|-----|
| 止损位 | $${output.riskManagement.stopLoss} |
| 止盈位 | $${output.riskManagement.takeProfit} |
| 盈亏比 | ${output.riskManagement.riskRewardRatio} |

### 情景推演
${output.scenarios.map(s => {
  const emoji = s.scenario.includes("乐观") ? "🌟" : s.scenario.includes("中性") ? "➡️" : "⚠️";
  return `**${emoji} ${s.scenario} (${(s.probability * 100).toFixed(0)}%)**: ${s.outcome}`;
}).join("\n")}

### 策略置信度
**${output.confidence}%**

---

**建议**: 请确认策略方案是否符合您的预期，确认后可进入验证阶段。`;
}
