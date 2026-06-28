/**
 * 资产调研 - 第一屏集成适配器
 * 供第一屏 screen1-macro-finance 调用
 *
 * 使用方式：
 *   import { AssetResearchBridge } from './asset-research-bridge';
 *
 *   // 读取最新调研结果
 *   const result = AssetResearchBridge.getLatest();
 *
 *   // 获取周期结论
 *   const cycle = AssetResearchBridge.getCycleInfo();
 *
 *   // 获取资产配置建议
 *   const allocation = AssetResearchBridge.getAllocation();
 */

import { StandardOutputManager } from '../output/standard-output';
import * as fs from 'fs';
import * as path from 'path';

const DEFAULT_OUTPUT_PATH = path.join(
  __dirname,
  '..',
  '..',
  'output',
  'latest.json'
);

export interface CycleInfo {
  currentPhase: string;
  phaseName: string;
  confidence: number;
  indicators: Array<{
    name: string;
    value: string;
    trend: string;
  }>;
  rationale: string;
}

export interface AllocationInfo {
  weights: Record<string, number>;
  topAssets: Array<{
    rank: number;
    name: string;
    category: string;
    direction: string;
  }>;
  bottomAssets: Array<{
    rank: number;
    name: string;
    direction: string;
  }>;
}

export interface OutlookInfo {
  shortTerm: { phase: string; phaseName: string; probability: number };
  midTerm: { phase: string; phaseName: string; probability: number };
  longTerm: { phase: string; phaseName: string; probability: number };
}

export interface ResearchSummary {
  hasData: boolean;
  generatedAt?: string;
  engineVersion?: string;
  cycle?: CycleInfo;
  allocation?: AllocationInfo;
  outlook?: OutlookInfo;
  riskAlerts?: string[];
}

/**
 * 资产调研桥接器
 * 供第一屏等模块读取资产调研结果
 */
export class AssetResearchBridge {
  private static cache: ResearchSummary | null = null;
  private static cacheTime: number = 0;
  private static cacheTTL = 30 * 60 * 1000; // 30分钟缓存

  /**
   * 获取最新调研结果摘要
   */
  static getLatest(customPath?: string): ResearchSummary {
    const now = Date.now();

    // 检查缓存
    if (this.cache && now - this.cacheTime < this.cacheTTL) {
      return this.cache;
    }

    const outputPath = customPath || DEFAULT_OUTPUT_PATH;
    const result = StandardOutputManager.readFromFile(outputPath);

    if (!result) {
      this.cache = { hasData: false };
      this.cacheTime = now;
      return this.cache;
    }

    const summary: ResearchSummary = {
      hasData: true,
      generatedAt: result.metadata.generatedAt,
      engineVersion: result.metadata.engineVersion,
      cycle: {
        currentPhase: result.cycle.currentPhase,
        phaseName: result.cycle.phaseName,
        confidence: result.cycle.confidence,
        indicators: result.cycle.indicators,
        rationale: result.cycle.rationale,
      },
      allocation: {
        weights: result.allocation,
        topAssets: result.topAssets.slice(0, 10).map(a => ({
          rank: a.rank,
          name: a.displayName,
          category: a.categoryName,
          direction: a.directionName,
        })),
        bottomAssets: result.bottomAssets.map(a => ({
          rank: a.rank,
          name: a.displayName,
          direction: a.direction,
        })),
      },
      outlook: result.outlook,
      riskAlerts: result.riskAlerts,
    };

    this.cache = summary;
    this.cacheTime = now;
    return summary;
  }

  /**
   * 获取周期信息
   */
  static getCycleInfo(customPath?: string): CycleInfo | null {
    const summary = this.getLatest(customPath);
    return summary.cycle || null;
  }

  /**
   * 获取资产配置
   */
  static getAllocation(customPath?: string): AllocationInfo | null {
    const summary = this.getLatest(customPath);
    return summary.allocation || null;
  }

  /**
   * 获取周期展望
   */
  static getOutlook(customPath?: string): OutlookInfo | null {
    const summary = this.getLatest(customPath);
    return summary.outlook || null;
  }

  /**
   * 检查是否有数据
   */
  static hasData(customPath?: string): boolean {
    return this.getLatest(customPath).hasData;
  }

  /**
   * 获取数据新鲜度（分钟）
   */
  static getDataAge(customPath?: string): number | null {
    const summary = this.getLatest(customPath);
    if (!summary.generatedAt) return null;
    const ageMs = Date.now() - new Date(summary.generatedAt).getTime();
    return Math.floor(ageMs / 60000);
  }

  /**
   * 强制刷新缓存
   */
  static refreshCache(): void {
    this.cache = null;
    this.cacheTime = 0;
  }

  /**
   * 获取周期的中文描述（用于第一屏展示）
   */
  static getCycleDescription(customPath?: string): string {
    const cycle = this.getCycleInfo(customPath);
    if (!cycle) return '暂无周期数据';

    const descriptions: Record<string, string> = {
      recovery: '经济复苏期：增长上行，通胀下行。股票是表现最好的资产。',
      overheat: '经济过热期：增长上行，通胀上行。大宗商品是表现最好的资产。',
      stagflation: '经济滞胀期：增长下行，通胀上行。现金/货币和商品表现较好。',
      recession: '经济衰退期：增长下行，通胀下行。债券是表现最好的资产。',
    };

    return descriptions[cycle.currentPhase] || `当前周期：${cycle.phaseName}`;
  }

  /**
   * 获取对加密货币的建议（专供第一屏使用）
   */
  static getCryptoRecommendation(customPath?: string): {
    allocation: number;
    direction: string;
    rationale: string;
  } | null {
    const allocation = this.getAllocation(customPath);
    if (!allocation) return null;

    const cryptoWeight = allocation.weights.crypto || 0;
    const direction = cryptoWeight >= 15 ? '超配' : cryptoWeight >= 10 ? '标配' : '低配';

    const rationale = `美林时钟模型建议加密货币配置比例为 ${cryptoWeight}%，属于${direction}区间。`;

    return {
      allocation: cryptoWeight,
      direction,
      rationale,
    };
  }
}
