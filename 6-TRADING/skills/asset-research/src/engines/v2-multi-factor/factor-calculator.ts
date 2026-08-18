/**
 * v2 多因子增强版 - 因子计算器
 * Multi-Factor Enhanced - Factor Calculator
 *
 * 因子体系：
 * 1. 周期因子（美林时钟）- 权重40%
 * 2. 动量因子（趋势强弱）- 权重25%
 * 3. 估值因子（价值高低）- 权重20%
 * 4. 情绪因子（资金/舆情）- 权重15%
 */

import {
  CyclePhase,
  AssetCategory,
  AssetSubCategory,
  AllocationDirection
} from '../../types';

export interface FactorScores {
  cycle: number;           // 周期因子 0-100
  momentum: number;        // 动量因子 0-100
  valuation: number;       // 估值因子 0-100
  sentiment: number;       // 情绪因子 0-100
  total: number;           // 综合得分 0-100
}

export interface FactorWeights {
  cycle: number;
  momentum: number;
  valuation: number;
  sentiment: number;
}

export interface SubCategoryFactorResult {
  subCategory: AssetSubCategory;
  displayName: string;
  category: AssetCategory;
  scores: FactorScores;
  priority: number;
  direction: AllocationDirection;
  rationale: string;
}

export interface CategoryFactorResult {
  category: AssetCategory;
  displayName: string;
  weight: number;
  direction: AllocationDirection;
  scores: FactorScores;
  subCategories: SubCategoryFactorResult[];
}

/**
 * 多因子计算器
 */
export class MultiFactorCalculator {
  private weights: FactorWeights;

  constructor(customWeights?: Partial<FactorWeights>) {
    this.weights = {
      cycle: 0.40,
      momentum: 0.25,
      valuation: 0.20,
      sentiment: 0.15,
      ...customWeights,
    };
  }

  /**
   * 计算子类综合得分
   */
  calculateSubCategoryScore(
    subCategory: AssetSubCategory,
    phase: CyclePhase,
    momentumData?: Record<string, number>,
    valuationData?: Record<string, number>,
    sentimentData?: Record<string, number>
  ): SubCategoryFactorResult {
    const cycleScore = this.calculateCycleScore(subCategory, phase);
    const momentumScore = momentumData?.[subCategory] ?? this.getDefaultMomentumScore(subCategory, phase);
    const valuationScore = valuationData?.[subCategory] ?? this.getDefaultValuationScore(subCategory);
    const sentimentScore = sentimentData?.[subCategory] ?? this.getDefaultSentimentScore(subCategory, phase);

    const total = this.calculateWeightedTotal({
      cycle: cycleScore,
      momentum: momentumScore,
      valuation: valuationScore,
      sentiment: sentimentScore,
    });

    const priority = this.scoreToPriority(total);
    const direction = this.scoreToDirection(total);
    const rationale = this.buildRationale(subCategory, {
      cycle: cycleScore,
      momentum: momentumScore,
      valuation: valuationScore,
      sentiment: sentimentScore,
      total,
    });

    return {
      subCategory,
      displayName: this.getDisplayName(subCategory),
      category: this.getCategory(subCategory),
      scores: {
        cycle: cycleScore,
        momentum: momentumScore,
        valuation: valuationScore,
        sentiment: sentimentScore,
        total,
      },
      priority,
      direction,
      rationale,
    };
  }

  /**
   * 计算大类综合得分
   */
  calculateCategoryScore(
    category: AssetCategory,
    phase: CyclePhase,
    subResults: SubCategoryFactorResult[]
  ): CategoryFactorResult {
    const avgTotal = subResults.length > 0
      ? subResults.reduce((sum, s) => sum + s.scores.total, 0) / subResults.length
      : 50;

    const avgCycle = subResults.length > 0
      ? subResults.reduce((sum, s) => sum + s.scores.cycle, 0) / subResults.length
      : 50;

    const avgMomentum = subResults.length > 0
      ? subResults.reduce((sum, s) => sum + s.scores.momentum, 0) / subResults.length
      : 50;

    const avgValuation = subResults.length > 0
      ? subResults.reduce((sum, s) => sum + s.scores.valuation, 0) / subResults.length
      : 50;

    const avgSentiment = subResults.length > 0
      ? subResults.reduce((sum, s) => sum + s.scores.sentiment, 0) / subResults.length
      : 50;

    const weight = this.scoreToWeight(avgTotal);
    const direction = this.scoreToDirection(avgTotal);

    return {
      category,
      displayName: this.getCategoryDisplayName(category),
      weight,
      direction,
      scores: {
        cycle: avgCycle,
        momentum: avgMomentum,
        valuation: avgValuation,
        sentiment: avgSentiment,
        total: avgTotal,
      },
      subCategories: subResults.sort((a, b) => a.priority - b.priority),
    };
  }

  /**
   * 计算周期因子得分
   * 基于美林时钟的子类在当前周期的偏好度
   */
  private calculateCycleScore(
    subCategory: AssetSubCategory,
    phase: CyclePhase
  ): number {
    const PREFERENCE_MAP: Record<AssetSubCategory, Record<CyclePhase, number>> = {
      // 股票
      tech: { recovery: 90, overheat: 40, stagflation: 20, recession: 20 },
      financial: { recovery: 80, overheat: 40, stagflation: 20, recession: 30 },
      energy: { recovery: 30, overheat: 90, stagflation: 80, recession: 20 },
      consumer: { recovery: 40, overheat: 40, stagflation: 50, recession: 70 },
      cyclical: { recovery: 90, overheat: 80, stagflation: 20, recession: 20 },
      // 债券
      treasury: { recovery: 20, overheat: 20, stagflation: 40, recession: 90 },
      credit: { recovery: 80, overheat: 40, stagflation: 20, recession: 30 },
      convertible: { recovery: 80, overheat: 80, stagflation: 20, recession: 20 },
      high_yield: { recovery: 40, overheat: 80, stagflation: 10, recession: 10 },
      // 商品
      precious_metal: { recovery: 20, overheat: 40, stagflation: 90, recession: 40 },
      energy_commodity: { recovery: 30, overheat: 80, stagflation: 80, recession: 20 },
      industrial_metal: { recovery: 80, overheat: 90, stagflation: 20, recession: 20 },
      agricultural: { recovery: 40, overheat: 40, stagflation: 80, recession: 40 },
      // 现金
      usd: { recovery: 20, overheat: 30, stagflation: 80, recession: 70 },
      cny: { recovery: 80, overheat: 40, stagflation: 20, recession: 20 },
      eur: { recovery: 30, overheat: 30, stagflation: 40, recession: 40 },
      jpy: { recovery: 20, overheat: 20, stagflation: 40, recession: 80 },
      // 加密
      mainstream_crypto: { recovery: 80, overheat: 90, stagflation: 20, recession: 20 },
      exchange_token: { recovery: 40, overheat: 80, stagflation: 20, recession: 20 },
      layer2: { recovery: 40, overheat: 80, stagflation: 20, recession: 20 },
      defi: { recovery: 80, overheat: 40, stagflation: 20, recession: 20 },
      infrastructure: { recovery: 40, overheat: 80, stagflation: 20, recession: 20 },
    };

    return PREFERENCE_MAP[subCategory]?.[phase] ?? 50;
  }

  /**
   * 获取默认动量得分
   * 当无实际数据时，基于周期推断
   */
  private getDefaultMomentumScore(
    subCategory: AssetSubCategory,
    phase: CyclePhase
  ): number {
    // 动量与周期正相关，周期偏好高的动量也高
    const cycleScore = this.calculateCycleScore(subCategory, phase);
    // 加入一些随机性模拟真实市场波动
    const noise = (Math.random() - 0.5) * 20;
    return Math.max(0, Math.min(100, cycleScore * 0.7 + noise + 15));
  }

  /**
   * 获取默认估值得分
   * 价值投资逻辑：涨多了估值高（低分），跌多了估值低（高分）
   */
  private getDefaultValuationScore(subCategory: AssetSubCategory): number {
    // 默认中值，实际应基于PE/PB等数据
    const BASE_VALUATION: Record<AssetSubCategory, number> = {
      tech: 40, financial: 60, energy: 55, consumer: 50, cyclical: 45,
      treasury: 65, credit: 55, convertible: 45, high_yield: 50,
      precious_metal: 55, energy_commodity: 50, industrial_metal: 45, agricultural: 55,
      usd: 50, cny: 55, eur: 50, jpy: 55,
      mainstream_crypto: 35, exchange_token: 40, layer2: 30, defi: 35, infrastructure: 40,
    };
    return BASE_VALUATION[subCategory] ?? 50;
  }

  /**
   * 获取默认情绪得分
   */
  private getDefaultSentimentScore(
    subCategory: AssetSubCategory,
    phase: CyclePhase
  ): number {
    // 情绪与周期正相关，但波动更大
    const cycleScore = this.calculateCycleScore(subCategory, phase);
    const noise = (Math.random() - 0.5) * 30;
    return Math.max(0, Math.min(100, cycleScore * 0.6 + noise + 20));
  }

  /**
   * 计算加权总分
   */
  private calculateWeightedTotal(scores: Omit<FactorScores, 'total'>): number {
    return (
      scores.cycle * this.weights.cycle +
      scores.momentum * this.weights.momentum +
      scores.valuation * this.weights.valuation +
      scores.sentiment * this.weights.sentiment
    );
  }

  /**
   * 分数转优先级
   */
  private scoreToPriority(score: number): number {
    // 100分 -> 优先级1，0分 -> 优先级10
    return Math.max(1, Math.ceil((100 - score) / 10));
  }

  /**
   * 分数转配置方向
   */
  private scoreToDirection(score: number): AllocationDirection {
    if (score >= 65) return 'overweight';
    if (score <= 35) return 'underweight';
    return 'neutral';
  }

  /**
   * 分数转权重
   */
  private scoreToWeight(score: number): number {
    // 基于得分计算大类权重，总和约100%
    // 这里返回相对权重，实际使用时需要归一化
    return Math.round(score * 0.8 + 10);
  }

  /**
   * 构建理由
   */
  private buildRationale(
    subCategory: AssetSubCategory,
    scores: FactorScores
  ): string {
    const displayName = this.getDisplayName(subCategory);
    const strengths: string[] = [];
    const weaknesses: string[] = [];

    if (scores.cycle >= 70) strengths.push('周期位置有利');
    else if (scores.cycle <= 30) weaknesses.push('周期位置不利');

    if (scores.momentum >= 70) strengths.push('动量强劲');
    else if (scores.momentum <= 30) weaknesses.push('动量疲软');

    if (scores.valuation >= 70) strengths.push('估值有吸引力');
    else if (scores.valuation <= 30) weaknesses.push('估值偏高');

    if (scores.sentiment >= 70) strengths.push('市场情绪积极');
    else if (scores.sentiment <= 30) weaknesses.push('市场情绪低迷');

    let rationale = `${displayName}综合得分${scores.total.toFixed(0)}分。`;
    if (strengths.length > 0) rationale += `优势：${strengths.join('、')}。`;
    if (weaknesses.length > 0) rationale += `风险：${weaknesses.join('、')}。`;

    return rationale;
  }

  /**
   * 获取子类显示名称
   */
  private getDisplayName(subCategory: AssetSubCategory): string {
    const NAMES: Record<AssetSubCategory, string> = {
      tech: '科技股', financial: '金融股', energy: '能源股',
      consumer: '消费股', cyclical: '周期股',
      treasury: '国债', credit: '信用债', convertible: '可转债', high_yield: '高收益债',
      precious_metal: '贵金属', energy_commodity: '能源',
      industrial_metal: '工业金属', agricultural: '农产品',
      usd: '美元', cny: '人民币', eur: '欧元', jpy: '日元',
      mainstream_crypto: '主流币(BTC/ETH)', exchange_token: '平台币',
      layer2: '二层网络', defi: 'DeFi', infrastructure: '基建公链',
    };
    return NAMES[subCategory] || subCategory;
  }

  /**
   * 获取大类
   */
  private getCategory(subCategory: AssetSubCategory): AssetCategory {
    const CATEGORY_MAP: Record<AssetSubCategory, AssetCategory> = {
      tech: 'stock', financial: 'stock', energy: 'stock',
      consumer: 'stock', cyclical: 'stock',
      treasury: 'bond', credit: 'bond', convertible: 'bond', high_yield: 'bond',
      precious_metal: 'commodity', energy_commodity: 'commodity',
      industrial_metal: 'commodity', agricultural: 'commodity',
      usd: 'cash', cny: 'cash', eur: 'cash', jpy: 'cash',
      mainstream_crypto: 'crypto', exchange_token: 'crypto',
      layer2: 'crypto', defi: 'crypto', infrastructure: 'crypto',
    };
    return CATEGORY_MAP[subCategory] || 'stock';
  }

  /**
   * 获取大类显示名称
   */
  private getCategoryDisplayName(category: AssetCategory): string {
    const NAMES: Record<AssetCategory, string> = {
      stock: '股票',
      bond: '债券',
      commodity: '商品',
      cash: '现金/货币',
      crypto: '加密货币',
    };
    return NAMES[category];
  }
}
