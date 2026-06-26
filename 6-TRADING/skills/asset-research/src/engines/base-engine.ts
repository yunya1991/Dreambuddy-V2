/**
 * 资产标的调研引擎 - v1 美林时钟基类
 * Base Engine for Asset Research
 */

import {
  AssetResearchEngine,
  ResearchOptions,
  ResearchResult,
  CyclePhase,
  AssetAllocation,
  MacroIndicator,
  Region,
  DataSourceRef
} from '../../types';

/**
 * v1美林时钟引擎基类
 * 提供周期判定和资产配置的核心逻辑
 */
export abstract class BaseMerrillClockEngine implements AssetResearchEngine {
  abstract readonly version: string;
  abstract readonly name: string;
  readonly description: string = '美林投资时钟经典框架';

  /**
   * 判定当前经济周期
   */
  abstract determineCycle(indicators: MacroIndicator[]): {
    phase: CyclePhase;
    confidence: number;
    rationale: string;
  };

  /**
   * 根据周期获取资产配置
   */
  abstract getAllocationByCycle(phase: CyclePhase): AssetAllocation[];

  /**
   * 执行研究
   */
  abstract run(options?: ResearchOptions): Promise<ResearchResult>;

  /**
   * 获取子类资产在特定周期的偏好度
   * @param subCategory 子类
   * @param phase 经济周期
   * @returns 偏好度分数 (1-5, 5最高)
   */
  protected getSubCategoryPreference(
    subCategory: string,
    phase: CyclePhase
  ): number {
    // 子类在四阶段的偏好度配置
    const PREFERENCE_MAP: Record<string, Record<CyclePhase, number>> = {
      // 股票
      tech: { recovery: 5, overheat: 2, stagflation: 1, recession: 1 },
      financial: { recovery: 4, overheat: 2, stagflation: 1, recession: 1 },
      energy: { recovery: 1, overheat: 5, stagflation: 4, recession: 1 },
      consumer: { recovery: 2, overheat: 2, stagflation: 2, recession: 4 },
      cyclical: { recovery: 5, overheat: 4, stagflation: 1, recession: 1 },
      // 债券
      treasury: { recovery: 1, overheat: 1, stagflation: 2, recession: 5 },
      credit: { recovery: 4, overheat: 2, stagflation: 1, recession: 1 },
      convertible: { recovery: 4, overheat: 4, stagflation: 1, recession: 1 },
      high_yield: { recovery: 2, overheat: 4, stagflation: 1, recession: 1 },
      // 商品
      precious_metal: { recovery: 1, overheat: 2, stagflation: 5, recession: 2 },
      energy_commodity: { recovery: 1, overheat: 4, stagflation: 4, recession: 1 },
      industrial_metal: { recovery: 4, overheat: 5, stagflation: 1, recession: 1 },
      agricultural: { recovery: 2, overheat: 2, stagflation: 4, recession: 2 },
      // 现金/货币
      usd: { recovery: 1, overheat: 1, stagflation: 4, recession: 4 },
      cny: { recovery: 4, overheat: 2, stagflation: 1, recession: 1 },
      eur: { recovery: 1, overheat: 1, stagflation: 2, recession: 2 },
      jpy: { recovery: 1, overheat: 1, stagflation: 2, recession: 4 },
      // 加密
      mainstream_crypto: { recovery: 4, overheat: 5, stagflation: 1, recession: 1 },
      exchange_token: { recovery: 2, overheat: 4, stagflation: 1, recession: 1 },
      layer2: { recovery: 2, overheat: 4, stagflation: 1, recession: 1 },
      defi: { recovery: 4, overheat: 2, stagflation: 1, recession: 1 },
      infrastructure: { recovery: 2, overheat: 4, stagflation: 1, recession: 1 },
    };

    return PREFERENCE_MAP[subCategory]?.[phase] ?? 3;
  }

  /**
   * 计算大类资产配置权重
   */
  protected calculateCategoryWeights(phase: CyclePhase): Record<string, number> {
    const WEIGHT_MAP: Record<CyclePhase, Record<string, number>> = {
      recovery: {
        stock: 40,
        bond: 25,
        commodity: 15,
        cash: 10,
        crypto: 10
      },
      overheat: {
        stock: 25,
        bond: 10,
        commodity: 35,
        cash: 15,
        crypto: 15
      },
      stagflation: {
        stock: 10,
        bond: 20,
        commodity: 30,
        cash: 30,
        crypto: 10
      },
      recession: {
        stock: 15,
        bond: 40,
        commodity: 10,
        cash: 25,
        crypto: 10
      }
    };

    return WEIGHT_MAP[phase];
  }

  /**
   * 验证指标新鲜度
   */
  protected checkDataFreshness(timestamp: string): 'fresh' | 'acceptable' | 'stale' {
    const dataTime = new Date(timestamp).getTime();
    const now = Date.now();
    const daysDiff = (now - dataTime) / (1000 * 60 * 60 * 24);

    if (daysDiff <= 7) return 'fresh';
    if (daysDiff <= 30) return 'acceptable';
    return 'stale';
  }

  /**
   * 计算整体置信度
   */
  protected calculateConfidence(
    indicatorCount: number,
    averageFreshness: number,
    crossValidationScore: number
  ): number {
    // 基于指标数量的置信度
    const countScore = Math.min(indicatorCount / 10, 1) * 0.4;
    // 基于新鲜度的置信度
    const freshnessScore = averageFreshness * 0.3;
    // 基于交叉验证的置信度
    const validationScore = crossValidationScore * 0.3;

    return Math.min(countScore + freshnessScore + validationScore, 1);
  }

  /**
   * 获取当前周期
   */
  getCyclePhase(): CyclePhase {
    return 'recovery'; // 默认值，子类实现时应返回实际判定结果
  }

  /**
   * 获取资产配置
   */
  getAssetAllocation(phase: CyclePhase): AssetAllocation[] {
    return this.getAllocationByCycle(phase);
  }
}
