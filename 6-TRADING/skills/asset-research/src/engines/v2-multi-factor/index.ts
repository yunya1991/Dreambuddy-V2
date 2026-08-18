/**
 * v2 多因子增强版引擎
 * Multi-Factor Enhanced Engine
 *
 * 在美林时钟基础上增加：
 * - 动量因子（趋势强弱）
 * - 估值因子（价值高低）
 * - 情绪因子（资金/舆情）
 *
 * 因子权重：周期40% + 动量25% + 估值20% + 情绪15%
 */

import {
  ResearchOptions,
  ResearchResult,
  AssetCategory,
  AssetSubCategory,
  SubCategoryAsset,
  AssetAllocation,
  Region
} from '../../types';
import { V1MerrillClockEngine } from '../v1-merrill-clock';
import { MultiFactorCalculator, CategoryFactorResult, SubCategoryFactorResult, FactorWeights } from './factor-calculator';
import { FactorDataFetcher } from './factor-data-fetcher';

export class V2MultiFactorEngine extends V1MerrillClockEngine {
  readonly version = '2.0.0';
  readonly name = 'Multi-Factor v2';
  readonly description = '多因子增强版 - 美林时钟 + 动量 + 估值 + 情绪';

  private factorCalculator: MultiFactorCalculator;
  private factorDataFetcher: FactorDataFetcher;
  private useRealFactorData: boolean;

  constructor(apiKey?: string, options?: {
    useRealFactorData?: boolean;
    factorWeights?: FactorWeights;
  }) {
    super(apiKey);
    this.factorCalculator = new MultiFactorCalculator(options?.factorWeights);
    this.factorDataFetcher = new FactorDataFetcher(this.tavilyFetcher);
    this.useRealFactorData = options?.useRealFactorData ?? false;
  }

  /**
   * 运行研究
   */
  async run(options?: ResearchOptions): Promise<ResearchResult> {
    const region = options?.region || 'global';
    console.log(`[V2] 启动多因子资产研究，区域: ${region}`);

    // 1. 获取宏观经济指标（复用v1逻辑）
    const indicators = await this.fetchIndicators(options);

    // 2. 判定经济周期（复用v1逻辑）
    const cycleDetermination = this.determineCycle(indicators);
    console.log(`[V2] 周期判定: ${cycleDetermination.phase}, 置信度: ${(cycleDetermination.confidence * 100).toFixed(0)}%`);

    // 3. 多因子计算（v2新增）
    const categoryResults = await this.calculateMultiFactorScores(cycleDetermination.phase);

    // 4. 生成资产配置
    const allocations = this.generateFactorBasedAllocations(categoryResults);

    // 5. 获取子类优先级
    const topSubCategories = this.getTopSubCategoriesFromResults(categoryResults);

    // 6. 生成结果
    const result: ResearchResult = {
      version: this.version,
      engineName: this.name,
      timestamp: new Date().toISOString(),
      region,
      cycle: {
        currentPhase: cycleDetermination.phase,
        confidence: cycleDetermination.confidence,
        indicators: cycleDetermination.supportingIndicators,
        rationale: cycleDetermination.rationale,
      },
      assetAllocation: allocations,
      topSubCategories,
      report: '',
      dataSources: this.getDataSources(indicators),
      confidence: cycleDetermination.confidence,
      metadata: {
        factorScores: categoryResults,
        indicatorScores: cycleDetermination.indicatorScores,
        isMultiFactor: true,
      },
    };

    // 生成Markdown报告（v2增强版）
    result.report = this.generateV2Report(result, categoryResults);

    console.log(`[V2] 研究完成，置信度: ${(result.confidence * 100).toFixed(0)}%`);

    return result;
  }

  /**
   * 计算多因子得分
   */
  private async calculateMultiFactorScores(phase: string): Promise<CategoryFactorResult[]> {
    const subCategoriesByCategory: Record<string, string[]> = {
      stock: ['tech', 'financial', 'energy', 'consumer', 'cyclical'],
      bond: ['treasury', 'credit', 'convertible', 'high_yield'],
      commodity: ['precious_metal', 'energy_commodity', 'industrial_metal', 'agricultural'],
      cash: ['usd', 'cny', 'eur', 'jpy'],
      crypto: ['mainstream_crypto', 'exchange_token', 'layer2', 'defi', 'infrastructure'],
    };

    const allSubCats: string[] = [];
    for (const cats of Object.values(subCategoriesByCategory)) {
      allSubCats.push.apply(allSubCats, cats);
    }

    // 获取各因子数据
    let momentumData: Record<string, number> = {};
    let valuationData: Record<string, number> = {};
    let sentimentData: Record<string, number> = {};

    if (this.useRealFactorData) {
      console.log('[V2] 正在获取真实因子数据...');
      const [momentumMap, valuationMap, sentimentMap] = await Promise.all([
        this.factorDataFetcher.getMomentumData(allSubCats as any[]),
        this.factorDataFetcher.getValuationData(allSubCats as any[]),
        this.factorDataFetcher.getSentimentData(allSubCats as any[]),
      ]);

      momentumMap.forEach(function(value, key) { momentumData[key] = value.score; });
      valuationMap.forEach(function(value, key) { valuationData[key] = value.score; });
      sentimentMap.forEach(function(value, key) { sentimentData[key] = value.score; });
      console.log('[V2] 因子数据获取完成');
    }

    const categoryResults: CategoryFactorResult[] = [];

    for (const entry of Object.entries(subCategoriesByCategory)) {
      const category = entry[0];
      const subCats = entry[1];
      const subResults: SubCategoryFactorResult[] = [];

      for (let i = 0; i < subCats.length; i++) {
        const subCat = subCats[i];
        subResults.push(
          this.factorCalculator.calculateSubCategoryScore(
            subCat as any,
            phase as any,
            momentumData,
            valuationData,
            sentimentData
          )
        );
      }

      const categoryResult = this.factorCalculator.calculateCategoryScore(
        category as any,
        phase as any,
        subResults
      );

      categoryResults.push(categoryResult);
    }

    return this.normalizeWeights(categoryResults);
  }

  /**
   * 归一化大类权重
   */
  private normalizeWeights(results: CategoryFactorResult[]): CategoryFactorResult[] {
    const totalWeight = results.reduce((sum, r) => sum + r.weight, 0);

    return results.map(r => ({
      ...r,
      weight: Math.round((r.weight / totalWeight) * 100),
    }));
  }

  /**
   * 生成基于多因子的资产配置
   */
  private generateFactorBasedAllocations(
    categoryResults: CategoryFactorResult[]
  ): AssetAllocation[] {
    return categoryResults
      .sort((a, b) => b.weight - a.weight)
      .map(cr => ({
        category: cr.category,
        displayName: cr.displayName,
        weight: cr.weight,
        direction: cr.direction,
        subCategories: cr.subCategories.map(sc => ({
          name: sc.subCategory,
          displayName: sc.displayName,
          priority: sc.priority,
          direction: sc.direction,
          rationale: sc.rationale,
          cyclePreference: [],
        })),
      }));
  }

  /**
   * 从因子结果获取Top子类
   */
  private getTopSubCategoriesFromResults(
    categoryResults: CategoryFactorResult[],
    topN: number = 10
  ): SubCategoryAsset[] {
    const allSubs: SubCategoryAsset[] = [];

    for (const cr of categoryResults) {
      for (const sc of cr.subCategories) {
        allSubs.push({
          name: sc.subCategory,
          displayName: sc.displayName,
          priority: sc.priority,
          direction: sc.direction,
          rationale: sc.rationale,
          cyclePreference: [],
        });
      }
    }

    return allSubs
      .sort((a, b) => a.priority - b.priority)
      .slice(0, topN);
  }

  /**
   * 生成v2增强版报告
   */
  private generateV2Report(
    result: ResearchResult,
    categoryResults: CategoryFactorResult[]
  ): string {
    // 先复用基础报告生成器
    const { MarkdownGenerator } = require('../../report/markdown-generator');
    const generator = new MarkdownGenerator();
    const baseReport = generator.generate(result);

    // 替换或增强相关章节
    const factorSection = this.generateFactorSection(categoryResults);

    // 在"子类资产优先级"后插入因子分析
    const sections = baseReport.split('## 四、数据来源');
    return sections[0] + factorSection + '\n\n## 四、数据来源' + sections[1];
  }

  /**
   * 生成因子分析章节
   */
  private generateFactorSection(categoryResults: CategoryFactorResult[]): string {
    let section = `\n## 三、多因子分析\n\n`;

    section += `> 因子权重：周期40% / 动量25% / 估值20% / 情绪15%\n\n`;

    section += `### 大类资产因子得分\n\n`;
    section += `| 资产类别 | 权重 | 周期因子 | 动量因子 | 估值因子 | 情绪因子 | 综合得分 |\n`;
    section += `|---------|------|---------|---------|---------|---------|----------|\n`;

    for (const cr of categoryResults.sort((a, b) => b.weight - a.weight)) {
      section += `| ${cr.displayName} | ${cr.weight}% | ${cr.scores.cycle.toFixed(0)} | ${cr.scores.momentum.toFixed(0)} | ${cr.scores.valuation.toFixed(0)} | ${cr.scores.sentiment.toFixed(0)} | **${cr.scores.total.toFixed(0)}** |\n`;
    }

    section += `\n### 子类因子详情（Top 10）\n\n`;

    const allSubs = categoryResults.flatMap(cr => cr.subCategories)
      .sort((a, b) => b.scores.total - a.scores.total)
      .slice(0, 10);

    section += `| 排名 | 子类 | 大类 | 周期 | 动量 | 估值 | 情绪 | 综合 | 配置方向 |\n`;
    section += `|------|------|------|------|------|------|------|------|---------|\n`;

    allSubs.forEach((sc, idx) => {
      const directionEmoji = sc.direction === 'overweight' ? '⬆️ 超配' :
                             sc.direction === 'underweight' ? '⬇️ 低配' : '➡️ 标配';
      section += `| ${idx + 1} | ${sc.displayName} | ${sc.category} | ${sc.scores.cycle.toFixed(0)} | ${sc.scores.momentum.toFixed(0)} | ${sc.scores.valuation.toFixed(0)} | ${sc.scores.sentiment.toFixed(0)} | **${sc.scores.total.toFixed(0)}** | ${directionEmoji} |\n`;
    });

    section += `\n**说明**：\n`;
    section += `- 周期因子：基于美林投资时钟的宏观周期适配度\n`;
    section += `- 动量因子：基于价格趋势的强弱度\n`;
    section += `- 估值因子：基于基本面的价值吸引力（分数越高越便宜）\n`;
    section += `- 情绪因子：基于资金流和舆情的市场热度\n`;

    return section;
  }

  /**
   * 设置因子权重
   */
  setFactorWeights(weights: {
    cycle?: number;
    momentum?: number;
    valuation?: number;
    sentiment?: number;
  }): void {
    this.factorCalculator = new MultiFactorCalculator(weights as any);
  }

  /**
   * 启用/禁用真实因子数据
   */
  setUseRealFactorData(enabled: boolean): void {
    this.useRealFactorData = enabled;
  }

  /**
   * 清除因子数据缓存
   */
  clearFactorCache(): void {
    this.factorDataFetcher.clearCache();
  }
}
