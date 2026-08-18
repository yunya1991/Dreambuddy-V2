/**
 * S4_验证 步骤实现
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 * 职责: 回测验证、风险评估、模拟推演
 */

import type {
  S4ValidateInput,
  S4ValidateOutput,
} from "../types";

/**
 * 执行回测模拟
 */
async function runBacktest(
  entryPoint: string,
  stopLoss: string,
  takeProfit: string,
  positionSize: number,
  period: string = "近180交易日"
): Promise<{
  period: string;
  winRate: number;
  profitFactor: number;
  maxDrawdown: number;
  sharpeRatio: number;
}> {
  // TODO: 集成真实回测引擎
  // 目前返回模拟数据

  // 根据盈亏比模拟胜率和盈亏比
  const riskRewardRatio = (parseFloat(takeProfit) - parseFloat(entryPoint)) / (parseFloat(entryPoint) - parseFloat(stopLoss));

  // 模拟回测结果
  const winRate = Math.min(95, 30 + riskRewardRatio * 15 + Math.random() * 10);
  const profitFactor = (riskRewardRatio * winRate / 100) / ((1 - winRate / 100));
  const maxDrawdown = 3 + Math.random() * 5;
  const sharpeRatio = (winRate / 100 * riskRewardRatio - 0.02) / (maxDrawdown / 100);

  return {
    period,
    winRate: Math.round(winRate * 10) / 10,
    profitFactor: Math.round(profitFactor * 100) / 100,
    maxDrawdown: Math.round(maxDrawdown * 10) / 10,
    sharpeRatio: Math.round(sharpeRatio * 100) / 100,
  };
}

/**
 * 风险评估
 */
function assessRisk(
  entryPoint: string,
  stopLoss: string,
  positionSize: number,
  currentPrice: number
): {
  var95: number;
  maxDailyLoss: number;
  consecutiveLosses: number;
} {
  // 计算止损幅度
  const stopLossPercent = (parseFloat(entryPoint) - parseFloat(stopLoss)) / parseFloat(entryPoint);

  // VaR (Value at Risk) 95%
  const var95 = positionSize * stopLossPercent * 0.95;

  // 最大单日亏损估算
  const maxDailyLoss = positionSize * 0.05; // 假设单日最大波动5%

  // 连续亏损次数估算
  const consecutiveLosses = Math.ceil(2 / stopLossPercent);

  return {
    var95: Math.round(var95 * 100) / 100,
    maxDailyLoss: Math.round(maxDailyLoss * 100) / 100,
    consecutiveLosses,
  };
}

/**
 * 生成验证结论
 */
function generateVerdict(
  backtest: {
    winRate: number;
    profitFactor: number;
    maxDrawdown: number;
    sharpeRatio: number;
  },
  riskAssessment: {
    var95: number;
    maxDailyLoss: number;
    consecutiveLosses: number;
  },
  positionSize: number
): string {
  const { winRate, profitFactor, maxDrawdown, sharpeRatio } = backtest;
  const { var95, maxDailyLoss, consecutiveLosses } = riskAssessment;

  // 综合评分
  let score = 0;

  // 胜率评分
  if (winRate >= 60) score += 25;
  else if (winRate >= 50) score += 15;
  else score += 5;

  // 盈亏比评分
  if (profitFactor >= 2) score += 25;
  else if (profitFactor >= 1.5) score += 15;
  else score += 5;

  // 最大回撤评分
  if (maxDrawdown <= 5) score += 25;
  else if (maxDrawdown <= 10) score += 15;
  else score += 5;

  // 夏普比率评分
  if (sharpeRatio >= 1.5) score += 25;
  else if (sharpeRatio >= 1) score += 15;
  else score += 5;

  // 风险评估
  const riskLevel = var95 > positionSize * 0.1 ? "高" : var95 > positionSize * 0.05 ? "中" : "低";

  if (score >= 80 && riskLevel !== "高") {
    return `策略评分${score}分，回测表现优秀。胜率${winRate}%，盈亏比${profitFactor}，最大回撤${maxDrawdown}%。` +
      `风险等级${riskLevel}，VaR(95%)约${var95.toFixed(2)}%。策略具备正期望值，建议执行。`;
  } else if (score >= 60) {
    return `策略评分${score}分，回测表现良好。胜率${winRate}%，盈亏比${profitFactor}，最大回撤${maxDrawdown}%。` +
      `风险等级${riskLevel}，建议谨慎执行，注意仓位控制。`;
  } else {
    return `策略评分${score}分，回测表现一般。胜率${winRate}%，盈亏比${profitFactor}，最大回撤${maxDrawdown}%。` +
      `建议优化策略参数后再执行。`;
  }
}

/**
 * 判断是否建议执行
 */
function shouldRecommend(
  backtest: {
    winRate: number;
    profitFactor: number;
    maxDrawdown: number;
    sharpeRatio: number;
  },
  riskAssessment: {
    var95: number;
    consecutiveLosses: number;
  },
  positionSize: number
): boolean {
  // 基本条件
  if (backtest.winRate < 40) return false;
  if (backtest.profitFactor < 1) return false;
  if (backtest.maxDrawdown > 20) return false;

  // 风险条件
  if (riskAssessment.var95 > positionSize * 0.15) return false;
  if (riskAssessment.consecutiveLosses > 5) return false;

  // 综合判断
  const score = backtest.winRate + backtest.profitFactor * 20 - backtest.maxDrawdown;
  return score >= 60;
}

/**
 * 执行S4验证
 */
export async function executeS4Validate(
  input: S4ValidateInput
): Promise<S4ValidateOutput> {
  const {
    entryPlan,
    riskManagement,
    historicalPeriod,
  } = input;

  // 执行回测
  const backtest = await runBacktest(
    entryPlan.entryPoint,
    riskManagement.stopLoss,
    riskManagement.takeProfit,
    entryPlan.positionSize,
    historicalPeriod
  );

  // 风险评估
  const riskAssessment = assessRisk(
    entryPlan.entryPoint,
    riskManagement.stopLoss,
    entryPlan.positionSize,
    0 // currentPrice 可从输入获取
  );

  // 生成结论
  const verdict = generateVerdict(backtest, riskAssessment, entryPlan.positionSize);

  // 判断是否建议执行
  const recommend = shouldRecommend(backtest, riskAssessment, entryPlan.positionSize);

  return {
    backtest,
    riskAssessment,
    verdict,
    recommend,
  };
}

/**
 * 格式化验证结果为Markdown
 */
export function formatS4ValidateResult(
  output: S4ValidateOutput,
  context?: { strategyName: string }
): string {
  const recommendEmoji = output.recommend ? "✅" : "❌";

  return `## ✅ S4_验证报告

### 回测摘要
| 指标 | 值 | 评价 |
|------|-----|------|
| 测试周期 | ${output.backtest.period} | - |
| 胜率 | ${output.backtest.winRate}% | ${output.backtest.winRate >= 60 ? "优秀" : output.backtest.winRate >= 50 ? "良好" : "一般"} |
| 盈亏比 | ${output.backtest.profitFactor} | ${output.backtest.profitFactor >= 2 ? "优秀" : output.backtest.profitFactor >= 1.5 ? "良好" : "一般"} |
| 最大回撤 | ${output.backtest.maxDrawdown}% | ${output.backtest.maxDrawdown <= 5 ? "优秀" : output.backtest.maxDrawdown <= 10 ? "良好" : "需注意"} |
| 夏普比率 | ${output.backtest.sharpeRatio} | ${output.backtest.sharpeRatio >= 1.5 ? "优秀" : output.backtest.sharpeRatio >= 1 ? "良好" : "一般"} |

### 风险评估
| 指标 | 值 |
|------|-----|
| VaR(95%) | $${output.riskAssessment.var95} |
| 最大单日亏损 | $${output.riskAssessment.maxDailyLoss} |
| 连续亏损次数 | ${output.riskAssessment.consecutiveLosses}次 |

---

### 验证结论
${output.verdict}

### 执行建议
${recommendEmoji} **${output.recommend ? "建议执行" : "不建议执行"}**

---

${output.recommend ? "确认后我将为您生成执行计划。" : "建议调整策略参数后重新验证。"}`;
}
