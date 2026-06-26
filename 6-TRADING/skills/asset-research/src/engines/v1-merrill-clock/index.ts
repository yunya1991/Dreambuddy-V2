/**
 * v1 美林时钟引擎
 * Merrill Lynch Investment Clock - Classic Framework
 */

import {
  ResearchOptions,
  ResearchResult,
  MacroIndicator,
  Region,
  DataSourceRef
} from '../../types';
import { BaseMerrillClockEngine } from '../base-engine';
import { CycleDetector } from './cycle-detector';
import { AssetAllocator } from './asset-allocation';
import { TavilyFetcher } from '../../data/tavily-fetcher';
import { MarkdownGenerator } from '../../report/markdown-generator';
import { JsonSerializer } from '../../report/json-serializer';

/**
 * v1美林时钟引擎实现
 */
export class V1MerrillClockEngine extends BaseMerrillClockEngine {
  readonly version = '1.0.0';
  readonly name = 'Merrill Clock v1';
  readonly description = '美林投资时钟经典框架 - 基于经济周期四象限的资产配置';

  private cycleDetector: CycleDetector;
  private assetAllocator: AssetAllocator;
  private tavilyFetcher: TavilyFetcher;
  private markdownGenerator: MarkdownGenerator;
  private jsonSerializer: JsonSerializer;

  constructor(apiKey?: string) {
    super();

    this.cycleDetector = new CycleDetector();
    this.assetAllocator = new AssetAllocator();
    this.tavilyFetcher = new TavilyFetcher(apiKey);
    this.markdownGenerator = new MarkdownGenerator();
    this.jsonSerializer = new JsonSerializer();
  }

  /**
   * 执行研究
   */
  async run(options?: ResearchOptions): Promise<ResearchResult> {
    const region = options?.region || 'global';
    console.log(`[V1] 启动资产标的调研，区域: ${region}`);

    // 1. 获取宏观经济指标
    const indicators = await this.fetchIndicators(options);

    // 2. 判定经济周期
    const cycleDetermination = this.cycleDetector.determine(indicators);
    console.log(`[V1] 周期判定: ${cycleDetermination.phase}, 置信度: ${(cycleDetermination.confidence * 100).toFixed(0)}%`);

    // 3. 生成资产配置
    const allocations = this.assetAllocator.generateAllocation(cycleDetermination.phase);

    // 4. 获取子类优先级
    const topSubCategories = this.assetAllocator.getTopSubCategories(allocations);

    // 5. 生成报告
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
      dataSources: [],
      confidence: cycleDetermination.confidence,
      metadata: {
        indicatorScores: cycleDetermination.indicatorScores,
      },
    };

    // 生成Markdown报告
    result.report = this.markdownGenerator.generate(result);

    // 设置数据来源
    result.dataSources = this.getDataSources(indicators);

    console.log(`[V1] 研究完成，置信度: ${(result.confidence * 100).toFixed(0)}%`);

    return result;
  }

  /**
   * 获取宏观经济指标
   */
  private async fetchIndicators(options?: ResearchOptions): Promise<MacroIndicator[]> {
    // 如果有自定义指标，优先使用
    if (options?.customIndicators && options.customIndicators.length > 0) {
      console.log(`[V1] 使用 ${options.customIndicators.length} 个自定义指标`);
      return options.customIndicators;
    }

    // 尝试从Tavily获取
    try {
      console.log('[V1] 从Tavily获取宏观经济数据...');
      const searchResults = await this.tavilyFetcher.searchMacroIndicators(options?.region || 'global');
      const extractions = this.tavilyFetcher.extractIndicators(searchResults);

      const indicators: MacroIndicator[] = extractions.map(ext => ext.indicator);
      console.log(`[V1] 提取到 ${indicators.length} 个指标`);

      return indicators;
    } catch (error) {
      console.warn('[V1] Tavily获取失败，使用默认指标:', error);
      return this.getDefaultIndicators();
    }
  }

  /**
   * 获取默认指标（当API不可用时）
   */
  private getDefaultIndicators(): MacroIndicator[] {
    return [
      {
        name: 'GDP增长率',
        value: '2.8',
        trend: 'up',
        source: '模拟数据',
        timestamp: new Date().toISOString(),
        freshness: 'fresh',
      },
      {
        name: 'PMI指数',
        value: '52.3',
        trend: 'up',
        source: '模拟数据',
        timestamp: new Date().toISOString(),
        freshness: 'fresh',
      },
      {
        name: 'CPI通胀率',
        value: '2.7',
        trend: 'down',
        source: '模拟数据',
        timestamp: new Date().toISOString(),
        freshness: 'fresh',
      },
      {
        name: 'PPI',
        value: '1.2',
        trend: 'down',
        source: '模拟数据',
        timestamp: new Date().toISOString(),
        freshness: 'acceptable',
      },
    ];
  }

  /**
   * 获取数据来源
   */
  private getDataSources(indicators: MacroIndicator[]): DataSourceRef[] {
    const sourceMap = new Map<string, DataSourceRef>();

    for (const ind of indicators) {
      if (!sourceMap.has(ind.source)) {
        sourceMap.set(ind.source, {
          name: ind.source,
          timestamp: ind.timestamp,
        });
      }
    }

    return Array.from(sourceMap.values());
  }

  /**
   * 判定周期（同步方法，供内部使用）
   */
  determineCycle(indicators: MacroIndicator[]): {
    phase: 'recovery' | 'overheat' | 'stagflation' | 'recession';
    confidence: number;
    rationale: string;
  } {
    return this.cycleDetector.determine(indicators);
  }

  /**
   * 根据周期获取资产配置（同步方法）
   */
  getAllocationByCycle(phase: 'recovery' | 'overheat' | 'stagflation' | 'recession') {
    return this.assetAllocator.generateAllocation(phase);
  }
}
