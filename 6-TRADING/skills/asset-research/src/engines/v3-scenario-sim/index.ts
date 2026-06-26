/**
 * v3 情景模拟版引擎
 * Scenario Simulation Engine
 *
 * 在v2多因子基础上增加：
 * - 周期切换概率预测
 * - 多情景配置方案（基准/乐观/悲观）
 * - 动态调整建议
 */

import {
  ResearchOptions,
  ResearchResult,
  CyclePhase,
  MacroIndicator,
  SubCategoryAsset,
  AssetAllocation,
  Region,
  CYCLE_CONFIG
} from '../../types';
import { V2MultiFactorEngine } from '../v2-multi-factor';
import { CyclePredictor, CyclePrediction, Scenario } from './cycle-predictor';

export interface ScenarioAllocation {
  scenario: Scenario;
  allocations: AssetAllocation[];
  topSubCategories: SubCategoryAsset[];
}

export class V3ScenarioSimEngine extends V2MultiFactorEngine {
  readonly version = '3.0.0';
  readonly name = 'Scenario Sim v3';
  readonly description = '情景模拟版 - 多因子 + 周期预测 + 多情景配置';

  private cyclePredictor: CyclePredictor;

  constructor(apiKey?: string, options?: {
    useRealFactorData?: boolean;
    useRealLeadingIndicators?: boolean;
    factorWeights?: any;
  }) {
    super(apiKey, {
      useRealFactorData: options?.useRealFactorData,
      factorWeights: options?.factorWeights,
    });
    this.cyclePredictor = new CyclePredictor({
      tavilyFetcher: this.tavilyFetcher,
      useRealLeadingIndicators: options?.useRealLeadingIndicators,
    });
  }

  /**
   * 运行研究
   */
  async run(options?: ResearchOptions): Promise<ResearchResult> {
    const region = options?.region || 'global';
    console.log(`[V3] 启动情景模拟资产研究，区域: ${region}`);

    // 1. 获取宏观经济指标（复用v1逻辑）
    const indicators = await this.fetchIndicators(options);

    // 2. 判定当前周期（复用v1逻辑）
    const cycleDetermination = this.determineCycle(indicators);
    console.log(`[V3] 当前周期: ${cycleDetermination.phase}, 置信度: ${(cycleDetermination.confidence * 100).toFixed(0)}%`);

    // 3. 周期预测（v3新增）
    const cyclePrediction = this.cyclePredictor.predict(
      cycleDetermination.phase,
      cycleDetermination.supportingIndicators as MacroIndicator[]
    );
    console.log(`[V3] 周期预测置信度: ${(cyclePrediction.confidence * 100).toFixed(0)}%, 预期持续: ${cyclePrediction.expectedDuration}个月`);

    // 4. 生成情景方案（v3新增）
    const scenarios = this.cyclePredictor.generateScenarios(cyclePrediction);
    console.log(`[V3] 生成 ${scenarios.length} 个情景方案`);

    // 5. 多因子计算（复用v2逻辑）
    const categoryResults = await this.calculateMultiFactorScores(cycleDetermination.phase);

    // 6. 生成各情景配置（v3新增）
    const scenarioAllocations = this.generateScenarioAllocations(scenarios);

    // 7. 基准情景配置（作为主要输出）
    const baseScenario = scenarios.find(s => s.name === '基准情景') || scenarios[0];
    const baseAllocations = this.generateV3Allocations(
      categoryResults,
      cyclePrediction
    );
    const topSubCategories = this.getTopSubCategoriesFromResults(categoryResults);

    // 8. 生成结果
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
        phaseProbability: cyclePrediction.nextPhaseProbability,
      },
      assetAllocation: baseAllocations,
      topSubCategories,
      report: '',
      dataSources: this.getDataSources(indicators),
      confidence: Math.min(
        cycleDetermination.confidence * 0.7 + cyclePrediction.confidence * 0.3,
        1
      ),
      metadata: {
        factorScores: categoryResults,
        cyclePrediction,
        scenarios,
        scenarioAllocations,
        isScenarioBased: true,
      },
    };

    // 生成v3增强版报告
    result.report = this.generateV3Report(result, cyclePrediction, scenarios);

    console.log(`[V3] 研究完成，综合置信度: ${(result.confidence * 100).toFixed(0)}%`);

    return result;
  }

  /**
   * 生成v3版资产配置
   * 考虑周期切换概率，做前瞻性配置调整
   */
  private generateV3Allocations(
    categoryResults: any[],
    prediction: CyclePrediction
  ): AssetAllocation[] {
    const baseAllocations = this.generateFactorBasedAllocations(categoryResults);

    // 基于下一阶段预测进行前瞻性调整
    const nextPhase = this.getMostLikelyNextPhase(prediction.nextPhaseProbability);
    const nextPhaseProb = prediction.nextPhaseProbability[nextPhase];

    // 调整权重：如果下一阶段概率较高，提前布局
    if (nextPhaseProb > 0.25 && nextPhase !== prediction.currentPhase) {
      return this.adjustForNextPhase(baseAllocations, nextPhase, nextPhaseProb);
    }

    return baseAllocations;
  }

  /**
   * 为下一阶段调整配置
   */
  private adjustForNextPhase(
    allocations: AssetAllocation[],
    nextPhase: CyclePhase,
    probability: number
  ): AssetAllocation[] {
    // 获取下一阶段的标准配置
    const nextPhaseWeights = this.getPhaseWeights(nextPhase);

    // 按概率比例混合
    const adjustFactor = probability * 0.3; // 最多30%的前瞻调整

    return allocations.map(allocation => {
      const nextWeight = nextPhaseWeights[allocation.category as keyof typeof nextPhaseWeights] ?? allocation.weight;
      const adjustedWeight = Math.round(
        allocation.weight * (1 - adjustFactor) + nextWeight * adjustFactor
      );

      return {
        ...allocation,
        weight: adjustedWeight,
      };
    });
  }

  /**
   * 获取某阶段的标准权重
   */
  private getPhaseWeights(phase: CyclePhase): Record<string, number> {
    const WEIGHTS: Record<CyclePhase, Record<string, number>> = {
      recovery: { stock: 40, bond: 20, commodity: 15, cash: 10, crypto: 15 },
      overheat: { stock: 25, bond: 10, commodity: 35, cash: 10, crypto: 20 },
      stagflation: { stock: 10, bond: 20, commodity: 30, cash: 30, crypto: 10 },
      recession: { stock: 15, bond: 35, commodity: 10, cash: 30, crypto: 10 },
    };
    return WEIGHTS[phase];
  }

  /**
   * 获取最可能的下一阶段
   */
  private getMostLikelyNextPhase(probs: Record<CyclePhase, number>): CyclePhase {
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
   * 生成各情景配置（含子类细化）
   */
  private generateScenarioAllocations(scenarios: Scenario[]): ScenarioAllocation[] {
    var self = this;
    return scenarios.map(function(scenario) {
      const targetPhase = scenario.cycleSequence[1] || scenario.cycleSequence[0];
      const weights = self.getPhaseWeights(targetPhase);

      // 生成大类配置
      const allocations: AssetAllocation[] = [];
      const sortedCats = Object.entries(weights).sort(function(a, b) { return b[1] - a[1]; });

      for (let i = 0; i < sortedCats.length; i++) {
        const cat = sortedCats[i][0];
        const weight = sortedCats[i][1];
        const subs = self.getSubCategoriesForPhase(cat as any, targetPhase);
        allocations.push({
          category: cat as any,
          displayName: self.getCategoryDisplayName(cat),
          weight: weight,
          direction: weight >= 30 ? 'overweight' : weight <= 15 ? 'underweight' : 'neutral',
          subCategories: subs,
        });
      }

      // 获取Top子类
      const allSubs: SubCategoryAsset[] = [];
      for (let i = 0; i < allocations.length; i++) {
        for (let j = 0; j < allocations[i].subCategories.length; j++) {
          allSubs.push(allocations[i].subCategories[j]);
        }
      }
      const topSubs = allSubs.sort(function(a, b) { return a.priority - b.priority; }).slice(0, 10);

      return {
        scenario: scenario,
        allocations: allocations.sort(function(a, b) { return b.weight - a.weight; }),
        topSubCategories: topSubs,
      };
    });
  }

  /**
   * 获取某阶段某大类的子类配置
   */
  private getSubCategoriesForPhase(category: string, phase: CyclePhase): SubCategoryAsset[] {
    const SUB_CATEGORIES: Record<string, string[]> = {
      stock: ['tech', 'financial', 'energy', 'consumer', 'cyclical'],
      bond: ['treasury', 'credit', 'convertible', 'high_yield'],
      commodity: ['precious_metal', 'energy_commodity', 'industrial_metal', 'agricultural'],
      cash: ['usd', 'cny', 'eur', 'jpy'],
      crypto: ['mainstream_crypto', 'exchange_token', 'layer2', 'defi', 'infrastructure'],
    };

    // 各周期各子类的偏好度（简化版）
    const PREFERENCE: Record<string, Record<string, number>> = {
      recovery: {
        tech: 90, cyclical: 85, financial: 80, mainstream_crypto: 85, convertible: 80,
        credit: 75, defi: 75, industrial_metal: 80, layer2: 70, energy: 30,
        consumer: 40, treasury: 20, precious_metal: 20,
      },
      overheat: {
        energy: 90, energy_commodity: 85, mainstream_crypto: 90, industrial_metal: 85,
        cyclical: 80, convertible: 75, high_yield: 75, exchange_token: 80,
        layer2: 75, infrastructure: 70, tech: 40, treasury: 20,
      },
      stagflation: {
        precious_metal: 90, energy_commodity: 80, energy: 80, usd: 75,
        consumer: 50, high_yield: 20, tech: 20, mainstream_crypto: 25,
        industrial_metal: 25, cyclical: 20,
      },
      recession: {
        treasury: 90, jpy: 85, usd: 70, consumer: 70,
        precious_metal: 40, credit: 30, tech: 20, mainstream_crypto: 20,
        high_yield: 15, convertible: 20, cyclical: 20,
      },
    };

    const subCats = SUB_CATEGORIES[category] || [];
    const prefs = PREFERENCE[phase] || {};

    const results: SubCategoryAsset[] = subCats.map(function(subCat, idx) {
      const score = prefs[subCat] ?? 50;
      const priority = Math.max(1, Math.ceil((100 - score) / 10));
      const direction = score >= 65 ? 'overweight' : score <= 35 ? 'underweight' : 'neutral';
      const displayNames: Record<string, string> = {
        tech: '科技股', financial: '金融股', energy: '能源股',
        consumer: '消费股', cyclical: '周期股',
        treasury: '国债', credit: '信用债', convertible: '可转债', high_yield: '高收益债',
        precious_metal: '贵金属', energy_commodity: '能源',
        industrial_metal: '工业金属', agricultural: '农产品',
        usd: '美元', cny: '人民币', eur: '欧元', jpy: '日元',
        mainstream_crypto: '主流币', exchange_token: '平台币',
        layer2: '二层网络', defi: 'DeFi', infrastructure: '基建公链',
      };

      return {
        name: subCat,
        displayName: displayNames[subCat] || subCat,
        priority: priority,
        direction: direction as any,
        rationale: '基于' + (phase === 'recovery' ? '复苏期' : phase === 'overheat' ? '过热期' : phase === 'stagflation' ? '滞胀期' : '衰退期') + '周期偏好',
        cyclePreference: [],
      };
    });

    return results.sort(function(a, b) { return a.priority - b.priority; });
  }

  /**
   * 生成v3版报告
   */
  private generateV3Report(
    result: ResearchResult,
    prediction: CyclePrediction,
    scenarios: Scenario[]
  ): string {
    // 先复用v2报告生成逻辑
    const baseReport = this.generateV2BaseReport(result);

    // 插入周期预测和情景模拟章节
    const predictionSection = this.generatePredictionSection(prediction);
    const scenarioSection = this.generateScenarioSection(scenarios);

    const parts = baseReport.split('## 三、');
    if (parts.length < 2) return baseReport;

    const beforeThird = parts[0];
    const afterThird = '## 三、' + parts[1];

    return beforeThird + predictionSection + '\n\n' + scenarioSection + '\n\n' + afterThird;
  }

  /**
   * 生成v2基础报告（简化版）
   */
  private generateV2BaseReport(result: ResearchResult): string {
    const { MarkdownGenerator } = require('../../report/markdown-generator');
    const generator = new MarkdownGenerator();
    return generator.generate(result);
  }

  /**
   * 生成周期预测章节
   */
  private generatePredictionSection(prediction: CyclePrediction): string {
    const nextPhase = this.getMostLikelyNextPhase(prediction.nextPhaseProbability);
    const nextPhaseName = CYCLE_CONFIG[nextPhase].displayName;

    let section = `## 二、周期展望与预测\n\n`;

    section += `### 当前周期：${CYCLE_CONFIG[prediction.currentPhase].displayName}\n\n`;
    section += `- **预期持续时间**：约 ${prediction.expectedDuration} 个月\n`;
    section += `- **预测置信度**：${(prediction.confidence * 100).toFixed(0)}%\n`;
    section += `- **时间范围**：${prediction.timeHorizon}\n\n`;

    section += `### 下一周期概率分布\n\n`;
    section += `| 周期 | 概率 | 说明 |\n`;
    section += `|------|------|------|\n`;

    for (const entry of Object.entries(prediction.nextPhaseProbability).sort(function(a, b) { return b[1] - a[1]; })) {
      const phase = entry[0] as CyclePhase;
      const prob = entry[1];
      const bar = this.generateProgressBar(prob, 20);
      section += `| ${CYCLE_CONFIG[phase].displayName} | ${(prob * 100).toFixed(1)}% | ${bar} |\n`;
    }

    section += `\n**最可能路径**：${CYCLE_CONFIG[prediction.currentPhase].displayName} → ${nextPhaseName}（概率 ${(prediction.nextPhaseProbability[nextPhase] * 100).toFixed(1)}%）\n`;

    // 多时间维度展望
    if (prediction.timeHorizons && prediction.timeHorizons.length > 0) {
      section += `\n### 多时间维度展望\n\n`;
      section += `| 时间维度 | 展望周期 | 概率 | 关键驱动因素 |\n`;
      section += `|---------|---------|------|-------------|\n`;

      for (let i = 0; i < prediction.timeHorizons.length; i++) {
        const h = prediction.timeHorizons[i];
        const drivers = h.keyDrivers.slice(0, 3).join('、');
        section += `| ${h.displayName}（${h.duration}） | ${CYCLE_CONFIG[h.mostLikelyPhase].displayName} | ${(h.probability * 100).toFixed(0)}% | ${drivers} |\n`;
      }
    }

    section += `\n### 领先指标观察\n\n`;
    for (let i = 0; i < prediction.leadingIndicators.length; i++) {
      const ind = prediction.leadingIndicators[i];
      const signalEmoji = ind.signal === 'bullish' ? '🟢' :
                         ind.signal === 'bearish' ? '🔴' : '🟡';
      section += `- ${signalEmoji} **${ind.name}**：${ind.value}（领先 ${ind.leadTime} 个月）\n`;
    }

    return section;
  }

  /**
   * 生成情景模拟章节
   */
  private generateScenarioSection(scenarios: Scenario[]): string {
    let section = `## 三、多情景配置方案\n\n`;

    for (let i = 0; i < scenarios.length; i++) {
      const scenario = scenarios[i];
      const emoji = i === 0 ? '🎯' : i === 1 ? '🟢' : '🔴';

      section += `### ${emoji} ${scenario.name}（概率 ${(scenario.probability * 100).toFixed(1)}%）\n\n`;
      section += `${scenario.description}\n\n`;
      section += `**周期路径**：${scenario.cycleSequence.map(p => CYCLE_CONFIG[p].displayName).join(' → ')}\n\n`;

      // 生成简化版配置建议
      const allocations = this.getScenarioAllocationsList(scenario);
      section += `**配置建议**：${allocations}\n\n`;
    }

    section += `> **策略建议**：以基准情景为核心配置，适度考虑乐观/悲观情景的对冲。建议定期（季度）重新评估情景概率，动态调整配置。\n`;

    return section;
  }

  /**
   * 获取情景配置列表
   */
  private getScenarioAllocationsList(scenario: Scenario): string {
    const targetPhase = scenario.cycleSequence[1] || scenario.cycleSequence[0];
    const weights = this.getPhaseWeights(targetPhase);
    const sorted = Object.entries(weights).sort((a, b) => b[1] - a[1]);

    return sorted.slice(0, 3).map(([cat, weight]) =>
      `${this.getCategoryDisplayName(cat)}${weight}%`
    ).join('、');
  }

  /**
   * 生成进度条
   */
  private generateProgressBar(value: number, width: number): string {
    const filled = Math.round(value * width);
    const empty = width - filled;
    return '█'.repeat(filled) + '░'.repeat(empty);
  }

  /**
   * 获取大类显示名称
   */
  private getCategoryDisplayName(category: string): string {
    const names: Record<string, string> = {
      stock: '股票',
      bond: '债券',
      commodity: '商品',
      cash: '现金/货币',
      crypto: '加密货币',
    };
    return names[category] || category;
  }
}
