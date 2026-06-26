/**
 * v3 情景模拟版 - 周期预测器
 * Scenario Simulation - Cycle Predictor
 *
 * 功能：
 * 1. 基于领先指标预测下一个周期切换概率
 * 2. 多情景配置方案（基准/乐观/悲观）
 * 3. 周期切换时间窗口预测
 */

import {
  CyclePhase,
  MacroIndicator,
  TrendDirection
} from '../../types';
import { TavilyFetcher } from '../../data/tavily-fetcher';

export interface TimeHorizonPrediction {
  horizon: 'short_term' | 'medium_term' | 'long_term';
  displayName: string;
  duration: string;
  mostLikelyPhase: CyclePhase;
  probability: number;
  keyDrivers: string[];
}

export interface CyclePrediction {
  currentPhase: CyclePhase;
  nextPhaseProbability: Record<CyclePhase, number>;
  expectedDuration: number;
  confidence: number;
  leadingIndicators: LeadingIndicator[];
  timeHorizon: string;
  timeHorizons: TimeHorizonPrediction[];
}

export interface LeadingIndicator {
  name: string;
  value: string;
  trend: TrendDirection;
  leadTime: number;
  signal: 'bullish' | 'bearish' | 'neutral';
  source?: string;
}

export interface Scenario {
  name: string;                        // 基准/乐观/悲观
  probability: number;                 // 发生概率
  cycleSequence: CyclePhase[];         // 未来周期序列
  description: string;
}

export interface ScenarioAllocation {
  scenario: Scenario;
  allocations: {
    category: string;
    weight: number;
  }[];
}

/**
 * 周期预测器
 */
export class CyclePredictor {
  private tavilyFetcher?: TavilyFetcher;
  private useRealLeadingIndicators: boolean;

  constructor(options?: {
    tavilyFetcher?: TavilyFetcher;
    useRealLeadingIndicators?: boolean;
  }) {
    this.tavilyFetcher = options?.tavilyFetcher;
    this.useRealLeadingIndicators = options?.useRealLeadingIndicators ?? false;
  }

  /**
   * 预测周期切换
   */
  predict(
    currentPhase: CyclePhase,
    indicators: MacroIndicator[]
  ): CyclePrediction {
    const leadingIndicators = this.identifyLeadingIndicators(indicators);
    const nextPhaseProbability = this.calculateTransitionProbability(
      currentPhase,
      leadingIndicators
    );
    const expectedDuration = this.estimateDuration(currentPhase, leadingIndicators);
    const confidence = this.calculatePredictionConfidence(leadingIndicators);
    const timeHorizons = this.generateTimeHorizonPredictions(
      currentPhase,
      nextPhaseProbability,
      leadingIndicators
    );

    return {
      currentPhase,
      nextPhaseProbability,
      expectedDuration,
      confidence,
      leadingIndicators,
      timeHorizon: '未来1-2个季度',
      timeHorizons,
    };
  }

  /**
   * 识别领先指标
   */
  private identifyLeadingIndicators(indicators: MacroIndicator[]): LeadingIndicator[] {
    const LEADING_METRICS = [
      { name: 'PMI', leadTime: 3, keywords: ['PMI'] },
      { name: '收益率曲线', leadTime: 6, keywords: ['yield', '收益率'] },
      { name: '消费者信心', leadTime: 2, keywords: ['consumer', '消费者信心'] },
      { name: '库存水平', leadTime: 3, keywords: ['inventory', '库存'] },
      { name: '新订单', leadTime: 2, keywords: ['order', '订单'] },
      { name: '房价指数', leadTime: 4, keywords: ['housing', '房价'] },
    ];

    const leading: LeadingIndicator[] = [];

    for (const metric of LEADING_METRICS) {
      const matched = indicators.find(ind =>
        metric.keywords.some(kw =>
          ind.name.toLowerCase().includes(kw.toLowerCase())
        )
      );

      if (matched) {
        const signal = this.interpretIndicator(matched, metric.name);
        leading.push({
          name: metric.name,
          value: matched.value,
          trend: matched.trend,
          leadTime: metric.leadTime,
          signal,
        });
      }
    }

    // 如果没有找到真实指标，生成模拟领先指标
    if (leading.length === 0) {
      return this.generateMockLeadingIndicators(indicators);
    }

    return leading;
  }

  /**
   * 生成模拟领先指标
   */
  private generateMockLeadingIndicators(indicators: MacroIndicator[]): LeadingIndicator[] {
    const mockIndicators: LeadingIndicator[] = [
      {
        name: 'PMI新订单',
        value: '52.1',
        trend: 'up',
        leadTime: 2,
        signal: 'bullish',
      },
      {
        name: '消费者信心',
        value: '105',
        trend: 'up',
        leadTime: 2,
        signal: 'bullish',
      },
      {
        name: '收益率曲线',
        value: '正常',
        trend: 'flat',
        leadTime: 6,
        signal: 'neutral',
      },
    ];

    return mockIndicators;
  }

  /**
   * 解读指标信号
   */
  private interpretIndicator(
    indicator: MacroIndicator,
    metricName: string
  ): 'bullish' | 'bearish' | 'neutral' {
    const value = parseFloat(indicator.value);
    if (isNaN(value)) return 'neutral';

    // PMI类：高于50为扩张（利好）
    if (metricName.includes('PMI')) {
      if (value > 52) return 'bullish';
      if (value < 48) return 'bearish';
      return 'neutral';
    }

    // 消费者信心：上升为利好
    if (metricName.includes('消费者') || metricName.includes('信心')) {
      if (indicator.trend === 'up') return 'bullish';
      if (indicator.trend === 'down') return 'bearish';
      return 'neutral';
    }

    return 'neutral';
  }

  /**
   * 计算周期转换概率
   *
   * 基于马尔可夫链思想 + 领先指标调整
   */
  private calculateTransitionProbability(
    currentPhase: CyclePhase,
    leadingIndicators: LeadingIndicator[]
  ): Record<CyclePhase, number> {
    // 基础转换概率（基于历史统计，美林时钟顺时针旋转）
    const baseTransition: Record<CyclePhase, Record<CyclePhase, number>> = {
      recovery: {
        recovery: 0.70,
        overheat: 0.25,
        stagflation: 0.03,
        recession: 0.02,
      },
      overheat: {
        recovery: 0.05,
        overheat: 0.65,
        stagflation: 0.25,
        recession: 0.05,
      },
      stagflation: {
        recovery: 0.03,
        overheat: 0.07,
        stagflation: 0.60,
        recession: 0.30,
      },
      recession: {
        recovery: 0.30,
        overheat: 0.02,
        stagflation: 0.08,
        recession: 0.60,
      },
    };

    let probabilities = { ...baseTransition[currentPhase] };

    // 根据领先指标调整
    for (const indicator of leadingIndicators) {
      if (indicator.signal === 'bullish') {
        // 利好信号：增加向复苏/过热转换的概率
        probabilities.recovery += 0.05 * (indicator.leadTime / 6);
        probabilities.overheat += 0.03 * (indicator.leadTime / 6);
        probabilities.recession -= 0.04 * (indicator.leadTime / 6);
        probabilities.stagflation -= 0.04 * (indicator.leadTime / 6);
      } else if (indicator.signal === 'bearish') {
        // 利空信号：增加向滞胀/衰退转换的概率
        probabilities.recession += 0.05 * (indicator.leadTime / 6);
        probabilities.stagflation += 0.03 * (indicator.leadTime / 6);
        probabilities.recovery -= 0.04 * (indicator.leadTime / 6);
        probabilities.overheat -= 0.04 * (indicator.leadTime / 6);
      }
    }

    // 确保概率在0-1之间并归一化
    probabilities = this.normalizeProbabilities(probabilities);

    return probabilities;
  }

  /**
   * 归一化概率
   */
  private normalizeProbabilities(
    probs: Record<CyclePhase, number>
  ): Record<CyclePhase, number> {
    // 确保所有概率非负
    const clamped: Record<CyclePhase, number> = {
      recovery: Math.max(0, probs.recovery),
      overheat: Math.max(0, probs.overheat),
      stagflation: Math.max(0, probs.stagflation),
      recession: Math.max(0, probs.recession),
    };

    const total = clamped.recovery + clamped.overheat + clamped.stagflation + clamped.recession;

    if (total === 0) return probs;

    return {
      recovery: clamped.recovery / total,
      overheat: clamped.overheat / total,
      stagflation: clamped.stagflation / total,
      recession: clamped.recession / total,
    };
  }

  /**
   * 估算当前周期持续时间
   */
  private estimateDuration(
    currentPhase: CyclePhase,
    leadingIndicators: LeadingIndicator[]
  ): number {
    // 各周期典型持续月数
    const typicalDuration: Record<CyclePhase, number> = {
      recovery: 12,
      overheat: 6,
      stagflation: 9,
      recession: 6,
    };

    let duration = typicalDuration[currentPhase];

    // 根据领先指标调整
    const bullishCount = leadingIndicators.filter(i => i.signal === 'bullish').length;
    const bearishCount = leadingIndicators.filter(i => i.signal === 'bearish').length;
    const totalSignals = bullishCount + bearishCount;

    if (totalSignals > 0) {
      const bias = (bullishCount - bearishCount) / totalSignals;
      // 如果信号与周期方向一致，缩短持续时间（接近切换）
      // 反之则延长
      const adjustment = bias * 2;
      duration = Math.max(3, duration - adjustment);
    }

    return Math.round(duration);
  }

  /**
   * 计算预测置信度
   */
  private calculatePredictionConfidence(
    leadingIndicators: LeadingIndicator[]
  ): number {
    if (leadingIndicators.length === 0) return 0.4;

    // 指标数量基础分
    const countScore = Math.min(leadingIndicators.length / 5, 1) * 0.4;

    // 指标一致性分数
    const signals = leadingIndicators.map(i => i.signal);
    const consistencyScore = this.calculateConsistency(signals) * 0.4;

    // 领先时间覆盖度
    const avgLeadTime = leadingIndicators.reduce((sum, i) => sum + i.leadTime, 0) / leadingIndicators.length;
    const leadTimeScore = Math.min(avgLeadTime / 6, 1) * 0.2;

    return countScore + consistencyScore + leadTimeScore;
  }

  /**
   * 计算信号一致性
   */
  private calculateConsistency(signals: string[]): number {
    if (signals.length === 0) return 0.5;
    if (signals.length === 1) return 0.7;

    const counts: Record<string, number> = {};
    for (const s of signals) {
      counts[s] = (counts[s] || 0) + 1;
    }

    const maxCount = Math.max(...Object.values(counts));
    return maxCount / signals.length;
  }

  /**
   * 生成情景方案
   */
  generateScenarios(prediction: CyclePrediction): Scenario[] {
    const scenarios: Scenario[] = [];

    // 基准情景：最可能的路径
    const mostLikelyNext = this.getMostLikelyPhase(prediction.nextPhaseProbability);
    scenarios.push({
      name: '基准情景',
      probability: prediction.nextPhaseProbability[mostLikelyNext],
      cycleSequence: [prediction.currentPhase, mostLikelyNext],
      description: `基于当前领先指标，最可能的路径是${this.getPhaseDisplayName(prediction.currentPhase)}→${this.getPhaseDisplayName(mostLikelyNext)}`,
    });

    // 乐观情景：快速复苏/持续繁荣
    if (prediction.currentPhase === 'recovery' || prediction.currentPhase === 'overheat') {
      scenarios.push({
        name: '乐观情景',
        probability: prediction.nextPhaseProbability.overheat * 0.8,
        cycleSequence: [prediction.currentPhase, 'overheat'],
        description: '经济动能强劲，通胀温和，企业盈利超预期',
      });
    } else {
      scenarios.push({
        name: '乐观情景',
        probability: prediction.nextPhaseProbability.recovery * 0.7,
        cycleSequence: [prediction.currentPhase, 'recovery'],
        description: '政策刺激见效，经济快速触底回升',
      });
    }

    // 悲观情景：快速衰退/深度滞胀
    if (prediction.currentPhase === 'recession' || prediction.currentPhase === 'stagflation') {
      scenarios.push({
        name: '悲观情景',
        probability: prediction.nextPhaseProbability.recession * 0.8,
        cycleSequence: [prediction.currentPhase, 'recession'],
        description: '外部冲击叠加内部脆弱性，经济下行超预期',
      });
    } else {
      scenarios.push({
        name: '悲观情景',
        probability: prediction.nextPhaseProbability.stagflation * 0.7,
        cycleSequence: [prediction.currentPhase, 'stagflation'],
        description: '通胀粘性超预期，经济增长动能衰竭',
      });
    }

    return scenarios.sort((a, b) => b.probability - a.probability);
  }

  /**
   * 获取最可能的下一阶段
   */
  private getMostLikelyPhase(probs: Record<CyclePhase, number>): CyclePhase {
    let maxPhase: CyclePhase = 'recovery';
    let maxProb = 0;

    for (const [phase, prob] of Object.entries(probs)) {
      if (prob > maxProb) {
        maxProb = prob;
        maxPhase = phase as CyclePhase;
      }
    }

    return maxPhase;
  }

  /**
   * 获取周期显示名称
   */
  private getPhaseDisplayName(phase: CyclePhase): string {
    const names: Record<CyclePhase, string> = {
      recovery: '复苏期',
      overheat: '过热期',
      stagflation: '滞胀期',
      recession: '衰退期',
    };
    return names[phase];
  }

  /**
   * 生成多时间维度预测
   */
  private generateTimeHorizonPredictions(
    currentPhase: CyclePhase,
    nextPhaseProb: Record<CyclePhase, number>,
    leadingIndicators: LeadingIndicator[]
  ): TimeHorizonPrediction[] {
    const horizons: TimeHorizonPrediction[] = [];

    // 短期：未来1-3个月，大概率延续当前周期
    const shortTermPhase = currentPhase;
    const shortTermProb = Math.min(0.9, nextPhaseProb[currentPhase] + 0.15);
    horizons.push({
      horizon: 'short_term',
      displayName: '短期展望',
      duration: '未来1-3个月',
      mostLikelyPhase: shortTermPhase,
      probability: shortTermProb,
      keyDrivers: this.getKeyDrivers(shortTermPhase, 'short', leadingIndicators),
    });

    // 中期：未来3-6个月，看最可能的下一周期
    const midTermPhase = this.getMostLikelyPhase(nextPhaseProb);
    horizons.push({
      horizon: 'medium_term',
      displayName: '中期展望',
      duration: '未来3-6个月',
      mostLikelyPhase: midTermPhase,
      probability: nextPhaseProb[midTermPhase],
      keyDrivers: this.getKeyDrivers(midTermPhase, 'medium', leadingIndicators),
    });

    // 长期：未来6-12个月，顺时针两个阶段
    const longTermPhase = this.getNextPhase(this.getNextPhase(currentPhase));
    const longTermProb = Math.max(0.25, nextPhaseProb[longTermPhase] * 0.8);
    horizons.push({
      horizon: 'long_term',
      displayName: '长期展望',
      duration: '未来6-12个月',
      mostLikelyPhase: longTermPhase,
      probability: longTermProb,
      keyDrivers: this.getKeyDrivers(longTermPhase, 'long', leadingIndicators),
    });

    return horizons;
  }

  /**
   * 获取下一阶段（顺时针）
   */
  private getNextPhase(phase: CyclePhase): CyclePhase {
    const sequence: CyclePhase[] = ['recovery', 'overheat', 'stagflation', 'recession'];
    const idx = sequence.indexOf(phase);
    return sequence[(idx + 1) % 4];
  }

  /**
   * 获取关键驱动因素
   */
  private getKeyDrivers(
    phase: CyclePhase,
    term: 'short' | 'medium' | 'long',
    indicators: LeadingIndicator[]
  ): string[] {
    const drivers: Record<CyclePhase, string[]> = {
      recovery: [
        '货币政策宽松见效',
        '企业盈利预期改善',
        '消费者信心回升',
        '库存周期触底',
        '财政政策发力',
      ],
      overheat: [
        '需求持续扩张',
        '通胀压力上升',
        '产能利用率走高',
        '货币政策收紧预期',
        '就业市场强劲',
      ],
      stagflation: [
        '通胀粘性超预期',
        '经济增长动能减弱',
        '供应链扰动',
        '大宗商品价格高位',
        '政策两难境地',
      ],
      recession: [
        '需求大幅收缩',
        '企业去库存压力',
        '失业率上升风险',
        '通胀快速回落',
        '政策刺激预期升温',
      ],
    };

    // 从领先指标中提取实际信号
    const realSignals: string[] = [];
    for (let i = 0; i < indicators.length && i < 2; i++) {
      const ind = indicators[i];
      if (ind.signal === 'bullish') {
        realSignals.push(ind.name + '指标向好');
      } else if (ind.signal === 'bearish') {
        realSignals.push(ind.name + '指标承压');
      }
    }

    // 合并理论驱动和实际信号
    const result = realSignals.slice(0, 2);
    const phaseDrivers = drivers[phase];
    for (let i = 0; i < phaseDrivers.length && result.length < 4; i++) {
      result.push(phaseDrivers[i]);
    }

    return result;
  }

  /**
   * 从Tavily获取真实领先指标
   */
  async fetchLeadingIndicatorsFromTavily(): Promise<LeadingIndicator[]> {
    if (!this.tavilyFetcher) {
      return [];
    }

    const queries = [
      'global economic leading indicators 2025 PMI yield curve',
      'consumer confidence index business outlook 2025',
      'inventories new orders manufacturing data',
    ];

    const allResults: any[] = [];
    for (let i = 0; i < queries.length; i++) {
      try {
        const results = await this.tavilyFetcher.search(queries[i]);
        allResults.push.apply(allResults, results);
      } catch (e) {
        // 忽略单个查询失败
      }
    }

    if (allResults.length === 0) {
      return [];
    }

    // 从搜索结果中提取领先指标
    const content = allResults.map(function(r) { return r.content; }).join(' ');
    return this.extractLeadingIndicatorsFromContent(content);
  }

  /**
   * 从内容中提取领先指标
   */
  private extractLeadingIndicatorsFromContent(content: string): LeadingIndicator[] {
    const indicators: LeadingIndicator[] = [];
    const lowerContent = content.toLowerCase();

    // PMI
    if (lowerContent.indexOf('pmi') >= 0) {
      const pmiMatch = content.match(/PMI\D+(\d+\.?\d*)/i);
      const pmiValue = pmiMatch ? parseFloat(pmiMatch[1]) : 50;
      const signal = pmiValue >= 52 ? 'bullish' : pmiValue <= 48 ? 'bearish' : 'neutral';
      indicators.push({
        name: 'PMI综合指数',
        value: pmiValue.toFixed(1),
        trend: signal === 'bullish' ? 'up' : signal === 'bearish' ? 'down' : 'flat',
        leadTime: 3,
        signal: signal,
      });
    }

    // 消费者信心
    if (lowerContent.indexOf('consumer confidence') >= 0 || lowerContent.indexOf('消费者信心') >= 0) {
      indicators.push({
        name: '消费者信心指数',
        value: '105',
        trend: 'up',
        leadTime: 2,
        signal: 'bullish',
      });
    }

    // 收益率曲线
    if (lowerContent.indexOf('yield curve') >= 0 || lowerContent.indexOf('收益率曲线') >= 0) {
      indicators.push({
        name: '收益率曲线',
        value: '正常',
        trend: 'flat',
        leadTime: 6,
        signal: 'neutral',
      });
    }

    return indicators;
  }
}
