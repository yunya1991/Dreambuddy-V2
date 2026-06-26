/**
 * 资产标的调研引擎 - 总入口
 * Asset Research Engine - Main Entry
 */

import {
  ResearchOptions,
  ResearchResult,
  MultiVersionResult,
  VersionComparison,
  MacroIndicator,
  Region
} from './types';
import { V1MerrillClockEngine } from './engines/v1-merrill-clock';
import { V2MultiFactorEngine } from './engines/v2-multi-factor';
import { V3ScenarioSimEngine } from './engines/v3-scenario-sim';
import { JsonSerializer } from './report/json-serializer';
import { ResearchHistoryManager } from './history/history-manager';

/**
 * 资产研究引擎编排器
 * 支持多版本并行运行和结果对比
 */
export class AssetResearchOrchestrator {
  private engines: Map<string, any> = new Map();
  private jsonSerializer: JsonSerializer;
  private historyManager: ResearchHistoryManager;
  private autoSaveHistory: boolean;

  constructor(options?: {
    autoSaveHistory?: boolean;
    historyDir?: string;
  }) {
    this.jsonSerializer = new JsonSerializer();
    this.autoSaveHistory = options?.autoSaveHistory ?? false;
    this.historyManager = new ResearchHistoryManager(options?.historyDir);

    // 注册所有引擎
    this.registerEngine('1', new V1MerrillClockEngine());
    this.registerEngine('2', new V2MultiFactorEngine());
    this.registerEngine('3', new V3ScenarioSimEngine());
  }

  /**
   * 注册引擎
   */
  registerEngine(version: string, engine: any): void {
    this.engines.set(version, engine);
    console.log(`[Orchestrator] 已注册引擎: v${version} - ${engine.name}`);
  }

  /**
   * 运行研究
   */
  async run(options?: ResearchOptions): Promise<MultiVersionResult> {
    const runAllVersions = options?.runAllVersions ?? false;

    if (runAllVersions && this.engines.size > 1) {
      return this.runAllVersions(options);
    }

    // 默认运行v1
    const v1Engine = this.engines.get('1');
    if (!v1Engine) {
      throw new Error('v1引擎未注册');
    }

    const result = await v1Engine.run(options);

    return {
      results: [result],
    };
  }

  /**
   * 运行所有版本
   */
  private async runAllVersions(options?: ResearchOptions): Promise<MultiVersionResult> {
    console.log(`[Orchestrator] 启动多版本研究，共 ${this.engines.size} 个引擎`);

    const results: ResearchResult[] = [];

    for (const [version, engine] of this.engines.entries()) {
      try {
        console.log(`[Orchestrator] 运行 v${version}...`);
        const result = await engine.run(options);
        results.push(result);
      } catch (error) {
        console.error(`[Orchestrator] v${version} 运行失败:`, error);
      }
    }

    // 生成对比报告
    let comparison: VersionComparison | undefined;
    if (results.length > 1) {
      comparison = this.generateComparison(results);
    }

    // 选择最佳版本
    const bestVersion = this.selectBestVersion(results);

    return {
      results,
      comparison,
      bestVersion,
    };
  }

  /**
   * 生成版本对比报告
   */
  private generateComparison(results: ResearchResult[]): VersionComparison {
    const cycleAgreement = this.calculateCycleAgreement(results);
    const allocationCorrelation = this.calculateAllocationCorrelation(results);
    const topSubCategoriesOverlap = this.calculateTopOverlap(results);

    return {
      versions: results.map(r => r.version),
      cycleAgreement,
      allocationCorrelation,
      topSubCategoriesOverlap,
      recommendation: this.generateRecommendation(results, {
        cycleAgreement,
        allocationCorrelation,
        topSubCategoriesOverlap,
      }),
      rollbackCandidate: this.detectRollbackCandidate(results),
      details: {
        cyclePhase: Object.fromEntries(results.map(r => [r.version, r.cycle.currentPhase])),
        topAssets: Object.fromEntries(results.map(r => [
          r.version,
          r.topSubCategories.slice(0, 5).map(s => s.displayName)
        ])),
      },
    };
  }

  /**
   * 计算周期一致性
   */
  private calculateCycleAgreement(results: ResearchResult[]): number {
    if (results.length < 2) return 1;

    const phases = results.map(r => r.cycle.currentPhase);
    const phaseCount = new Set(phases).size;

    // 全部一致 = 1, 全部不一致 = 0
    return 1 - (phaseCount - 1) / 3;
  }

  /**
   * 计算配置相关性
   */
  private calculateAllocationCorrelation(results: ResearchResult[]): number {
    if (results.length < 2) return 1;

    // 简化版：基于Top资产重合度计算
    return this.calculateTopOverlap(results);
  }

  /**
   * 计算Top资产重合度
   */
  private calculateTopOverlap(results: ResearchResult[]): number {
    if (results.length < 2) return 1;

    const topSets = results.map(r =>
      new Set(r.topSubCategories.slice(0, 5).map(s => s.name))
    );

    // 计算所有版本两两之间的重合度，然后取平均
    let totalOverlap = 0;
    let pairCount = 0;

    for (let i = 0; i < topSets.length; i++) {
      for (let j = i + 1; j < topSets.length; j++) {
        const intersection = new Set([...topSets[i]].filter(x => topSets[j].has(x)));
        const overlap = intersection.size / 5; // 基于Top5计算
        totalOverlap += overlap;
        pairCount++;
      }
    }

    return pairCount > 0 ? totalOverlap / pairCount : 1;
  }

  /**
   * 生成建议
   */
  private generateRecommendation(
    results: ResearchResult[],
    scores: { cycleAgreement: number; allocationCorrelation: number; topSubCategoriesOverlap: number }
  ): string {
    const avgScore = (scores.cycleAgreement + scores.allocationCorrelation + scores.topSubCategoriesOverlap) / 3;

    if (avgScore >= 0.8) {
      return '多版本结论高度一致，建议信任当前配置';
    }
    if (avgScore >= 0.5) {
      return '多版本存在一定分歧，建议关注差异最大的资产类别';
    }
    return '多版本结论分歧较大，建议结合更多数据源验证';
  }

  /**
   * 检测回退候选
   */
  private detectRollbackCandidate(results: ResearchResult[]): string | undefined {
    // 如果某个版本的置信度明显低于其他版本，考虑回退
    const confidences = results.map(r => r.confidence);
    const avgConfidence = confidences.reduce((a, b) => a + b, 0) / confidences.length;

    const lowConfidence = results.find(r =>
      r.confidence < avgConfidence * 0.7
    );

    return lowConfidence?.version;
  }

  /**
   * 选择最佳版本
   */
  private selectBestVersion(results: ResearchResult[]): string | undefined {
    if (results.length === 0) return undefined;

    // 基于置信度选择
    const sorted = [...results].sort((a, b) => b.confidence - a.confidence);
    return sorted[0].version;
  }

  /**
   * 获取可用版本列表
   */
  getAvailableVersions(): string[] {
    return Array.from(this.engines.keys());
  }

  /**
   * 运行指定版本
   */
  async runVersion(version: string, options?: ResearchOptions): Promise<ResearchResult> {
    const engine = this.engines.get(version);
    if (!engine) {
      throw new Error(`引擎 v${version} 未注册`);
    }

    return engine.run(options);
  }

  /**
   * 运行v1引擎（便捷方法）
   */
  async runV1(options?: ResearchOptions): Promise<ResearchResult> {
    return this.runVersion('1', options);
  }

  /**
   * 运行v2引擎（便捷方法）
   */
  async runV2(options?: ResearchOptions): Promise<ResearchResult> {
    return this.runVersion('2', options);
  }

  /**
   * 运行v3引擎（便捷方法）
   */
  async runV3(options?: ResearchOptions): Promise<ResearchResult> {
    return this.runVersion('3', options);
  }

  /**
   * 保存结果到历史记录
   */
  saveToHistory(result: ResearchResult): string {
    return this.historyManager.saveRecord(result);
  }

  /**
   * 获取历史记录
   */
  getHistory(options?: any): any[] {
    return this.historyManager.getRecords(options);
  }

  /**
   * 获取周期趋势分析
   */
  getCycleTrend(region?: string): any {
    return this.historyManager.analyzeCycleTrend(region);
  }

  /**
   * 获取最新记录
   */
  getLatestRecord(version?: string): any | null {
    return this.historyManager.getLatestRecord(version);
  }

  /**
   * 清除历史记录
   */
  clearHistory(): void {
    this.historyManager.clearAll();
  }
}

// ==================== 便捷函数 ====================

/**
 * 快速运行资产研究（默认v1）
 */
export async function runAssetResearch(options?: ResearchOptions): Promise<ResearchResult> {
  const orchestrator = new AssetResearchOrchestrator();
  return orchestrator.runV1(options);
}

/**
 * 运行多版本对比
 */
export async function runMultiVersionResearch(options?: ResearchOptions): Promise<MultiVersionResult> {
  const orchestrator = new AssetResearchOrchestrator();
  return orchestrator.run({ ...options, runAllVersions: true });
}

// 导出所有类型
export * from './types';

// 导出引擎
export { V1MerrillClockEngine } from './engines/v1-merrill-clock';
export { V2MultiFactorEngine } from './engines/v2-multi-factor';
export { V3ScenarioSimEngine } from './engines/v3-scenario-sim';
export { CycleDetector } from './engines/v1-merrill-clock/cycle-detector';
export { AssetAllocator } from './engines/v1-merrill-clock/asset-allocation';
export { MultiFactorCalculator } from './engines/v2-multi-factor/factor-calculator';
export { CyclePredictor } from './engines/v3-scenario-sim/cycle-predictor';

// 导出数据模块
export { TavilyFetcher } from './data/tavily-fetcher';

// 导出报告模块
export { MarkdownGenerator } from './report/markdown-generator';
export { JsonSerializer } from './report/json-serializer';

// 导出历史记录模块
export { ResearchHistoryManager } from './history/history-manager';

// 导出回测模块
export { BacktestEngine, HistoricalPeriod } from './backtest/backtest-engine';

// 导出告警模块
export { AlertManager, LarkWebhookHandler, WebhookHandler, EmailHandler } from './alerts/alert-manager';

// 导出导出模块
export { ReportExporter } from './export/report-exporter';

// 导出调度模块
export { ResearchScheduler } from './scheduler/research-scheduler';
