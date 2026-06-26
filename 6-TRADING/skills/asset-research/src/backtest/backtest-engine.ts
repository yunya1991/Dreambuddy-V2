/**
 * 回测引擎
 * 用历史数据验证各版本的表现
 */

import {
  ResearchResult,
  CyclePhase,
  AssetAllocation,
  BacktestConfig,
  BacktestResult,
  BacktestTrade,
  BacktestMetrics,
  PeriodPerformance
} from '../types';

export interface HistoricalPeriod {
  startDate: string;
  endDate: string;
  phase: CyclePhase;
  actualReturn?: Record<string, number>;  // 各资产的实际情况
}

export interface BacktestTradeRecord {
  date: string;
  action: 'buy' | 'sell';
  asset: string;
  amount: number;
  price: number;
  value: number;
}

/**
 * 回测引擎
 */
export class BacktestEngine {
  private config: Required<BacktestConfig>;
  private trades: BacktestTradeRecord[] = [];
  private portfolio: Map<string, number> = new Map();  // 资产 -> 数量
  private cash: number;

  constructor(config?: BacktestConfig) {
    this.config = {
      initialCapital: config?.initialCapital || 100000,
      commission: config?.commission || 0.001,
      slippage: config?.slippage || 0.0005,
      rebalanceThreshold: config?.rebalanceThreshold || 0.1,
      minTradeAmount: config?.minTradeAmount || 100,
    };
    this.cash = this.config.initialCapital;
  }

  /**
   * 运行回测
   */
  run(
    researchResults: ResearchResult[],
    historicalPeriods: HistoricalPeriod[]
  ): BacktestResult {
    console.log(`[Backtest] 开始回测，初始资金: ${this.config.initialCapital}`);
    console.log(`[Backtest] 回测周期: ${historicalPeriods.length} 个阶段`);

    this.trades = [];
    this.portfolio.clear();
    this.cash = this.config.initialCapital;

    const periodPerformances: PeriodPerformance[] = [];
    let currentAllocations: Record<string, number> = {};
    let totalValue = this.config.initialCapital;

    for (let i = 0; i < historicalPeriods.length; i++) {
      const period = historicalPeriods[i];
      const researchResult = researchResults[i % researchResults.length];

      console.log(`[Backtest] 阶段 ${i + 1}: ${period.phase} (${period.startDate} ~ ${period.endDate})`);

      // 获取目标配置
      const targetAllocation = this.getTargetAllocation(researchResult);

      // 计算当前配置偏差
      const drift = this.calculateDrift(currentAllocations, targetAllocation);

      // 如果偏差超过阈值，执行再平衡
      if (drift > this.config.rebalanceThreshold) {
        this.rebalance(targetAllocation, researchResult);
      }

      // 计算期间收益
      const periodReturn = this.calculatePeriodReturn(
        currentAllocations,
        period.actualReturn || {}
      );

      // 记录期间表现
      periodPerformances.push({
        period: i + 1,
        startDate: period.startDate,
        endDate: period.endDate,
        cyclePhase: period.phase,
        return: periodReturn,
        startValue: totalValue,
        endValue: totalValue * (1 + periodReturn),
        tradesCount: this.trades.filter(t => t.date >= period.startDate && t.date <= period.endDate).length,
      });

      totalValue *= (1 + periodReturn);

      // 更新当前配置
      currentAllocations = targetAllocation;
    }

    // 计算总体指标
    const metrics = this.calculateMetrics(periodPerformances);

    // 生成版本对比（如果有多个版本）
    const versionComparison = this.compareVersions(researchResults, historicalPeriods);

    const result: BacktestResult = {
      config: this.config,
      startDate: historicalPeriods[0]?.startDate || '',
      endDate: historicalPeriods[historicalPeriods.length - 1]?.endDate || '',
      initialCapital: this.config.initialCapital,
      finalValue: totalValue,
      metrics,
      periodPerformances,
      trades: this.trades,
      versionComparison,
    };

    console.log(`[Backtest] 回测完成，最终价值: ${totalValue.toFixed(2)}`);
    console.log(`[Backtest] 总收益: ${((totalValue / this.config.initialCapital - 1) * 100).toFixed(2)}%`);

    return result;
  }

  /**
   * 获取目标配置
   */
  private getTargetAllocation(result: ResearchResult): Record<string, number> {
    const allocation: Record<string, number> = {};

    for (const item of result.assetAllocation) {
      allocation[item.category] = item.allocation;
    }

    return allocation;
  }

  /**
   * 计算配置偏差
   */
  private calculateDrift(
    current: Record<string, number>,
    target: Record<string, number>
  ): number {
    let totalDrift = 0;

    const allAssets = new Set([...Object.keys(current), ...Object.keys(target)]);

    for (const asset of allAssets) {
      const currentWeight = current[asset] || 0;
      const targetWeight = target[asset] || 0;
      totalDrift += Math.abs(currentWeight - targetWeight);
    }

    return totalDrift / 2;  // 除以2是因为权重差异会被计算两次
  }

  /**
   * 执行再平衡
   */
  private rebalance(
    targetAllocation: Record<string, number>,
    researchResult: ResearchResult
  ): void {
    const date = new Date().toISOString().split('T')[0];

    // 计算各类资产的预期收益（基于周期）
    const expectedReturns = this.getExpectedReturns(researchResult.cycle.currentPhase);

    // 执行交易
    for (const [asset, targetWeight] of Object.entries(targetAllocation)) {
      const currentWeight = this.portfolio.get(asset) || 0;
      const weightDiff = targetWeight - currentWeight;

      if (Math.abs(weightDiff) > 0.01) {  // 权重差异超过1%才交易
        const tradeValue = this.cash * weightDiff;
        const commission = Math.abs(tradeValue) * this.config.commission;
        const slippage = Math.abs(tradeValue) * this.config.slippage;
        const totalCost = tradeValue + commission + slippage;

        if (tradeValue > 0 && this.cash >= totalCost) {
          // 买入
          this.cash -= totalCost;
          const amount = tradeValue / this.getAssetPrice(asset);
          const currentAmount = this.portfolio.get(asset) || 0;
          this.portfolio.set(asset, currentAmount + amount);

          this.trades.push({
            date,
            action: 'buy',
            asset,
            amount,
            price: this.getAssetPrice(asset) * (1 + this.config.slippage),
            value: tradeValue,
          });
        } else if (tradeValue < 0) {
          // 卖出
          const currentAmount = this.portfolio.get(asset) || 0;
          const sellAmount = Math.min(currentAmount, Math.abs(tradeValue) / this.getAssetPrice(asset));
          const sellValue = sellAmount * this.getAssetPrice(asset) * (1 - this.config.slippage);
          const totalProceeds = sellValue - Math.abs(sellValue * this.config.commission);

          this.cash += totalProceeds;
          this.portfolio.set(asset, currentAmount - sellAmount);

          this.trades.push({
            date,
            action: 'sell',
            asset,
            amount: sellAmount,
            price: this.getAssetPrice(asset) * (1 - this.config.slippage),
            value: sellValue,
          });
        }
      }
    }
  }

  /**
   * 获取资产价格（模拟）
   */
  private getAssetPrice(asset: string): number {
    const prices: Record<string, number> = {
      stock: 100,
      bond: 100,
      commodity: 100,
      cash: 1,
      crypto: 100,
    };
    return prices[asset] || 100;
  }

  /**
   * 获取预期收益（基于周期）
   */
  private getExpectedReturns(phase: CyclePhase): Record<string, number> {
    const returns: Record<CyclePhase, Record<string, number>> = {
      recovery: { stock: 0.15, bond: 0.05, commodity: 0.08, cash: 0.02, crypto: 0.12 },
      overheat: { stock: 0.10, bond: -0.05, commodity: 0.15, cash: 0.02, crypto: 0.08 },
      stagflation: { stock: -0.05, bond: 0.03, commodity: 0.12, cash: 0.03, crypto: 0.05 },
      recession: { stock: -0.10, bond: 0.08, commodity: -0.05, cash: 0.03, crypto: -0.08 },
    };
    return returns[phase] || returns.recession;
  }

  /**
   * 计算期间收益
   */
  private calculatePeriodReturn(
    allocation: Record<string, number>,
    actualReturn: Record<string, number>
  ): number {
    let totalReturn = 0;

    for (const [asset, weight] of Object.entries(allocation)) {
      const expectedReturn = this.getExpectedReturns('recovery')[asset] || 0;
      const actual = actualReturn[asset] !== undefined ? actualReturn[asset] : expectedReturn;
      totalReturn += weight * actual;
    }

    return totalReturn;
  }

  /**
   * 计算回测指标
   */
  private calculateMetrics(periods: PeriodPerformance[]): BacktestMetrics {
    if (periods.length === 0) {
      return {
        totalReturn: 0,
        annualizedReturn: 0,
        sharpeRatio: 0,
        maxDrawdown: 0,
        winRate: 0,
        avgHoldingPeriod: 0,
        turnoverRate: 0,
      };
    }

    // 总收益
    const finalValue = periods[periods.length - 1].endValue;
    const totalReturn = (finalValue / this.config.initialCapital - 1);

    // 年化收益
    const years = periods.length / 4;  // 假设每季度一个阶段
    const annualizedReturn = Math.pow(1 + totalReturn, 1 / years) - 1;

    // 计算夏普比率
    const returns = periods.map(p => p.return);
    const avgReturn = returns.reduce((a, b) => a + b, 0) / returns.length;
    const stdReturn = Math.sqrt(
      returns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / returns.length
    );
    const sharpeRatio = stdReturn > 0 ? (avgReturn / stdReturn) * Math.sqrt(4) : 0;  // 年化夏普

    // 最大回撤
    let maxDrawdown = 0;
    let peak = this.config.initialCapital;
    for (const period of periods) {
      if (period.endValue > peak) peak = period.endValue;
      const drawdown = (peak - period.endValue) / peak;
      if (drawdown > maxDrawdown) maxDrawdown = drawdown;
    }

    // 胜率
    const winningPeriods = returns.filter(r => r > 0).length;
    const winRate = winningPeriods / returns.length;

    // 平均持仓期（模拟）
    const avgHoldingPeriod = 90;  // 默认90天

    // 换手率
    const totalTrades = this.trades.length;
    const turnoverRate = totalTrades / periods.length / 4;  // 年化换手

    return {
      totalReturn,
      annualizedReturn,
      sharpeRatio,
      maxDrawdown,
      winRate,
      avgHoldingPeriod,
      turnoverRate,
    };
  }

  /**
   * 对比各版本表现
   */
  private compareVersions(
    results: ResearchResult[],
    periods: HistoricalPeriod[]
  ): Record<string, BacktestResult> {
    const comparisons: Record<string, BacktestResult> = {};

    // 对每个版本单独回测
    const uniqueVersions = [...new Set(results.map(r => r.version))];

    for (const version of uniqueVersions) {
      const versionResults = results.filter(r => r.version === version);
      const versionPeriods = periods.slice(0, versionResults.length);

      if (versionPeriods.length > 0) {
        const engine = new BacktestEngine(this.config);
        comparisons[version] = engine.run(versionResults, versionPeriods);
      }
    }

    return comparisons;
  }

  /**
   * 生成回测报告
   */
  generateReport(result: BacktestResult): string {
    const lines: string[] = [];

    lines.push('# 回测报告\n');
    lines.push(`**回测时间**: ${result.startDate} ~ ${result.endDate}`);
    lines.push(`**初始资金**: ${result.initialCapital.toLocaleString()}`);
    lines.push(`**最终价值**: ${result.finalValue.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`);
    lines.push(`**总收益**: ${(result.metrics.totalReturn * 100).toFixed(2)}%`);
    lines.push(`**年化收益**: ${(result.metrics.annualizedReturn * 100).toFixed(2)}%`);
    lines.push('\n## 风险指标\n');
    lines.push(`| 指标 | 数值 |`);
    lines.push(`|------|------|`);
    lines.push(`| 夏普比率 | ${result.metrics.sharpeRatio.toFixed(2)} |`);
    lines.push(`| 最大回撤 | ${(result.metrics.maxDrawdown * 100).toFixed(2)}% |`);
    lines.push(`| 胜率 | ${(result.metrics.winRate * 100).toFixed(2)}% |`);
    lines.push(`| 年化换手率 | ${(result.metrics.turnoverRate * 100).toFixed(2)}% |`);
    lines.push('\n## 期间表现\n');
    lines.push(`| 期间 | 周期 | 收益率 | 期初价值 | 期末价值 | 交易次数 |`);
    lines.push(`|------|------|--------|---------|---------|----------|`);
    for (const p of result.periodPerformances) {
      lines.push(`| ${p.startDate}~${p.endDate} | ${p.cyclePhase} | ${(p.return * 100).toFixed(2)}% | ${p.startValue.toFixed(2)} | ${p.endValue.toFixed(2)} | ${p.tradesCount} |`);
    }

    return lines.join('\n');
  }
}
