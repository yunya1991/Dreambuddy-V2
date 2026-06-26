/**
 * 周期判定模块
 * 根据宏观经济指标判定当前经济周期
 */

import {
  MacroIndicator,
  CyclePhase,
  CYCLE_CONFIG
} from '../../types';

export interface CycleDetermination {
  phase: CyclePhase;
  confidence: number;
  rationale: string;
  indicatorScores: {
    growthScore: number;    // 增长得分 (0-100)
    inflationScore: number; // 通胀得分 (0-100)
  };
  supportingIndicators: MacroIndicator[];
}

/**
 * 周期判定器
 */
export class CycleDetector {
  private readonly GROWTH_INDICATORS = [
    'GDP增长率',
    'GDP增长',
    '工业增加值',
    'PMI指数',
    '制造业PMI',
    '非制造业PMI',
    '工业PMI',
  ];

  private readonly INFLATION_INDICATORS = [
    'CPI通胀率',
    'CPI',
    'PPI',
    '核心CPI',
    '通货膨胀',
    '通胀率',
  ];

  /**
   * 判定经济周期
   */
  determine(indicators: MacroIndicator[]): CycleDetermination {
    // 分离增长和通胀指标
    const growthIndicators = this.filterIndicators(indicators, this.GROWTH_INDICATORS);
    const inflationIndicators = this.filterIndicators(indicators, this.INFLATION_INDICATORS);

    // 计算得分
    const growthScore = this.calculateGrowthScore(growthIndicators);
    const inflationScore = this.calculateInflationScore(inflationIndicators);

    // 判定周期
    const phase = this.determinePhase(growthScore, inflationScore);
    const confidence = this.calculateConfidence(growthIndicators, inflationIndicators);
    const rationale = this.buildRationale(phase, growthScore, inflationScore);

    return {
      phase,
      confidence,
      rationale,
      indicatorScores: { growthScore, inflationScore },
      supportingIndicators: [...growthIndicators, ...inflationIndicators],
    };
  }

  /**
   * 过滤相关指标
   */
  private filterIndicators(indicators: MacroIndicator[], keywords: string[]): MacroIndicator[] {
    return indicators.filter(ind =>
      keywords.some(kw =>
        ind.name.toLowerCase().includes(kw.toLowerCase())
      )
    );
  }

  /**
   * 计算增长得分
   * 0-30: 下行
   * 30-70: 平稳
   * 70-100: 上行
   */
  private calculateGrowthScore(indicators: MacroIndicator[]): number {
    if (indicators.length === 0) return 50; // 无数据时返回中性

    let totalScore = 0;
    let totalWeight = 0;

    for (const ind of indicators) {
      const value = parseFloat(ind.value);
      if (isNaN(value)) continue;

      let baseScore: number;
      let weight = 1;

      // 根据指标类型计算基础分
      if (ind.name.includes('PMI')) {
        // PMI: 50为荣枯线，40以下差，60以上强
        baseScore = Math.min(Math.max((value - 40) * 5, 0), 100);
      } else if (ind.name.includes('GDP') || ind.name.includes('增长') || ind.name.includes('工业增加值')) {
        // GDP: 2%为潜在增速基准，0%以下差，4%以上强
        baseScore = Math.min(Math.max((value - 0) * 20, 0), 100);
      } else if (ind.name.includes('失业率')) {
        // 失业率：5%为自然失业率基准，越低越好
        baseScore = Math.min(Math.max((5 - value) * 20 + 50, 0), 100);
        weight = 0.8;
      } else {
        baseScore = 50;
      }

      // 根据趋势调整
      let trendAdjust = 0;
      if (ind.trend === 'up') trendAdjust = 10;
      if (ind.trend === 'down') trendAdjust = -10;

      // 根据新鲜度调整
      let freshnessAdjust = 0;
      if (ind.freshness === 'fresh') freshnessAdjust = 5;
      if (ind.freshness === 'stale') freshnessAdjust = -10;

      const adjustedScore = Math.max(0, Math.min(100, baseScore + trendAdjust + freshnessAdjust));

      totalScore += adjustedScore * weight;
      totalWeight += weight;
    }

    return totalWeight > 0 ? totalScore / totalWeight : 50;
  }

  /**
   * 计算通胀得分
   * 0-30: 通胀下行
   * 30-70: 通胀平稳
   * 70-100: 通胀上行
   */
  private calculateInflationScore(indicators: MacroIndicator[]): number {
    if (indicators.length === 0) return 50;

    let totalScore = 0;
    let totalWeight = 0;

    for (const ind of indicators) {
      const value = parseFloat(ind.value);
      if (isNaN(value)) continue;

      let baseScore: number;
      let weight = 1;

      if (ind.name.includes('PPI') || ind.name.includes('生产者')) {
        // PPI对通胀有领先性，给予更高权重
        // 以2%为基准，0%以下通缩，5%以上高通胀
        weight = 1.2;
        baseScore = Math.min(Math.max((value - 1) * 15 + 35, 0), 100);
      } else if (ind.name.includes('核心CPI')) {
        // 核心CPI：以2%为目标基准
        weight = 1.1;
        baseScore = Math.min(Math.max((value - 2) * 25 + 50, 0), 100);
      } else {
        // CPI等：以2%为央行目标基准
        baseScore = Math.min(Math.max((value - 2) * 25 + 50, 0), 100);
      }

      // 趋势调整
      let trendAdjust = 0;
      if (ind.trend === 'up') trendAdjust = 10;
      if (ind.trend === 'down') trendAdjust = -10;

      // 新鲜度调整
      let freshnessAdjust = 0;
      if (ind.freshness === 'fresh') freshnessAdjust = 5;
      if (ind.freshness === 'stale') freshnessAdjust = -10;

      const adjustedScore = Math.max(0, Math.min(100, baseScore + trendAdjust + freshnessAdjust));

      totalScore += adjustedScore * weight;
      totalWeight += weight;
    }

    return totalWeight > 0 ? totalScore / totalWeight : 50;
  }

  /**
   * 根据得分判定周期
   *
   *        通胀↑
   *         │
   *   滞胀  │  过热
   *         │
   *  ───────┼─────── 增长↑
   *         │
   *   衰退  │  复苏
   *         │
   *        通胀↓
   */
  private determinePhase(growthScore: number, inflationScore: number): CyclePhase {
    // 使用中位数作为分界线
    const growthMidpoint = 50;
    const inflationMidpoint = 50;

    if (growthScore >= growthMidpoint && inflationScore < inflationMidpoint) {
      return 'recovery';
    }
    if (growthScore >= growthMidpoint && inflationScore >= inflationMidpoint) {
      return 'overheat';
    }
    if (growthScore < growthMidpoint && inflationScore >= inflationMidpoint) {
      return 'stagflation';
    }
    // growthScore < growthMidpoint && inflationScore < inflationMidpoint
    return 'recession';
  }

  /**
   * 计算置信度
   */
  private calculateConfidence(
    growthIndicators: MacroIndicator[],
    inflationIndicators: MacroIndicator[]
  ): number {
    // 指标数量基础分
    const indicatorCount = growthIndicators.length + inflationIndicators.length;
    const countScore = Math.min(indicatorCount / 6, 1) * 0.5;

    // 数据新鲜度分数
    const freshnessScores = [
      ...growthIndicators,
      ...inflationIndicators,
    ].map(ind => {
      if (ind.freshness === 'fresh') return 1;
      if (ind.freshness === 'acceptable') return 0.7;
      return 0.4;
    });
    const avgFreshness = freshnessScores.length > 0
      ? freshnessScores.reduce((a, b) => a + b, 0) / freshnessScores.length
      : 0.5;
    const freshnessScore = avgFreshness * 0.3;

    // 指标一致性分数（使用方差）
    const consistencyScore = this.calculateConsistencyScore(
      growthIndicators,
      inflationIndicators
    ) * 0.2;

    return Math.min(countScore + freshnessScore + consistencyScore, 1);
  }

  /**
   * 计算指标一致性
   */
  private calculateConsistencyScore(
    growthIndicators: MacroIndicator[],
    inflationIndicators: MacroIndicator[]
  ): number {
    // 检查增长指标趋势是否一致
    const growthTrends = growthIndicators.map(ind => ind.trend);
    const growthConsistency = this.trendConsistency(growthTrends);

    // 检查通胀指标趋势是否一致
    const inflationTrends = inflationIndicators.map(ind => ind.trend);
    const inflationConsistency = this.trendConsistency(inflationTrends);

    return (growthConsistency + inflationConsistency) / 2;
  }

  /**
   * 计算趋势一致性
   */
  private trendConsistency(trends: ('up' | 'down' | 'flat')[]): number {
    if (trends.length === 0) return 0.5;
    if (trends.length === 1) return 0.8;

    const counts = { up: 0, down: 0, flat: 0 };
    for (const t of trends) {
      counts[t]++;
    }

    const maxCount = Math.max(counts.up, counts.down, counts.flat);
    return maxCount / trends.length;
  }

  /**
   * 构建判定理由
   */
  private buildRationale(
    phase: CyclePhase,
    growthScore: number,
    inflationScore: number
  ): string {
    const config = CYCLE_CONFIG[phase];
    const growthTrend = growthScore >= 50 ? '上行' : '下行';
    const inflationTrend = inflationScore >= 50 ? '上行' : '下行';

    return `根据宏观指标分析，当前经济增长${growthTrend}，通胀${inflationTrend}。` +
      `符合${config.displayName}特征：${config.description}`;
  }
}
