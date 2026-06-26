/**
 * 资产配置映射模块
 * 根据经济周期生成大类资产配置和子类优先级
 */

import {
  CyclePhase,
  AssetAllocation,
  AssetCategory,
  AssetSubCategory,
  AllocationDirection,
  SubCategoryAsset,
  ASSET_CATEGORY_CONFIG,
  SUB_CATEGORY_DISPLAY,
  CYCLE_CONFIG
} from '../../types';

/**
 * 资产配置器
 */
export class AssetAllocator {
  /**
   * 根据周期生成资产配置
   */
  generateAllocation(phase: CyclePhase): AssetAllocation[] {
    const weights = this.getCategoryWeights(phase);
    const allocations: AssetAllocation[] = [];

    for (const [category, weight] of Object.entries(weights)) {
      const subCategories = this.generateSubCategories(category as AssetCategory, phase);
      const direction = this.getDirection(weight);

      allocations.push({
        category: category as AssetCategory,
        displayName: ASSET_CATEGORY_CONFIG[category as AssetCategory].displayName,
        weight,
        direction,
        subCategories,
      });
    }

    // 按权重降序排序
    return allocations.sort((a, b) => b.weight - a.weight);
  }

  /**
   * 获取大类资产权重
   */
  private getCategoryWeights(phase: CyclePhase): Record<AssetCategory, number> {
    const WEIGHT_MAP: Record<CyclePhase, Record<AssetCategory, number>> = {
      recovery: {
        stock: 40,
        bond: 20,
        commodity: 15,
        cash: 10,
        crypto: 15,
      },
      overheat: {
        stock: 25,
        bond: 10,
        commodity: 35,
        cash: 10,
        crypto: 20,
      },
      stagflation: {
        stock: 10,
        bond: 20,
        commodity: 30,
        cash: 30,
        crypto: 10,
      },
      recession: {
        stock: 15,
        bond: 35,
        commodity: 10,
        cash: 30,
        crypto: 10,
      },
    };

    return WEIGHT_MAP[phase];
  }

  /**
   * 生成子类资产配置
   */
  private generateSubCategories(
    category: AssetCategory,
    phase: CyclePhase
  ): SubCategoryAsset[] {
    const subCategoryConfigs = this.getSubCategoryConfigs(category);
    const preferences = this.getPreferences(phase);

    const subAssets: SubCategoryAsset[] = [];

    for (const [subCategory, basePreference] of Object.entries(subCategoryConfigs)) {
      const preference = (preferences as Record<string, number>)[subCategory] ?? 3;
      const priority = 6 - preference; // 5分 -> 优先级1, 1分 -> 优先级5
      const direction = this.getSubCategoryDirection(preference);
      const rationale = this.buildSubCategoryRationale(
        category as AssetCategory,
        subCategory as AssetSubCategory,
        phase,
        preference
      );

      subAssets.push({
        name: subCategory as AssetSubCategory,
        displayName: SUB_CATEGORY_DISPLAY[subCategory as AssetSubCategory].name,
        priority,
        direction,
        rationale,
        cyclePreference: this.getCyclePreference(subCategory as AssetSubCategory),
      });
    }

    // 按优先级排序
    return subAssets.sort((a, b) => a.priority - b.priority);
  }

  /**
   * 获取子类配置
   */
  private getSubCategoryConfigs(category: AssetCategory): Record<string, number> {
    const CONFIGS: Record<AssetCategory, string[]> = {
      stock: ['tech', 'financial', 'energy', 'consumer', 'cyclical'],
      bond: ['treasury', 'credit', 'convertible', 'high_yield'],
      commodity: ['precious_metal', 'energy_commodity', 'industrial_metal', 'agricultural'],
      cash: ['usd', 'cny', 'eur', 'jpy'],
      crypto: ['mainstream_crypto', 'exchange_token', 'layer2', 'defi', 'infrastructure'],
    };

    // 返回基础偏好分数（都是3，用于后续调整）
    const subs = CONFIGS[category];
    return Object.fromEntries(subs.map(s => [s, 3]));
  }

  /**
   * 获取某周期的子类偏好
   */
  private getPreferences(phase: CyclePhase): Record<string, number> {
    const PREFERENCE_MAP: Record<CyclePhase, Record<string, number>> = {
      recovery: {
        // 股票
        tech: 5, financial: 4, energy: 1, consumer: 2, cyclical: 5,
        // 债券
        treasury: 1, credit: 4, convertible: 4, high_yield: 2,
        // 商品
        precious_metal: 1, energy_commodity: 1, industrial_metal: 4, agricultural: 2,
        // 现金
        usd: 1, cny: 4, eur: 1, jpy: 1,
        // 加密
        mainstream_crypto: 4, exchange_token: 2, layer2: 2, defi: 4, infrastructure: 2,
      },
      overheat: {
        tech: 2, financial: 2, energy: 5, consumer: 2, cyclical: 4,
        treasury: 1, credit: 2, convertible: 4, high_yield: 4,
        precious_metal: 2, energy_commodity: 4, industrial_metal: 5, agricultural: 2,
        usd: 1, cny: 2, eur: 1, jpy: 1,
        mainstream_crypto: 5, exchange_token: 4, layer2: 4, defi: 2, infrastructure: 4,
      },
      stagflation: {
        tech: 1, financial: 1, energy: 4, consumer: 2, cyclical: 1,
        treasury: 2, credit: 1, convertible: 1, high_yield: 1,
        precious_metal: 5, energy_commodity: 4, industrial_metal: 1, agricultural: 4,
        usd: 4, cny: 1, eur: 2, jpy: 2,
        mainstream_crypto: 1, exchange_token: 1, layer2: 1, defi: 1, infrastructure: 1,
      },
      recession: {
        tech: 1, financial: 1, energy: 1, consumer: 4, cyclical: 1,
        treasury: 5, credit: 1, convertible: 1, high_yield: 1,
        precious_metal: 2, energy_commodity: 1, industrial_metal: 1, agricultural: 2,
        usd: 4, cny: 1, eur: 2, jpy: 4,
        mainstream_crypto: 1, exchange_token: 1, layer2: 1, defi: 1, infrastructure: 1,
      },
    };

    return PREFERENCE_MAP[phase];
  }

  /**
   * 获取配置方向
   */
  private getDirection(weight: number): AllocationDirection {
    if (weight >= 30) return 'overweight';
    if (weight <= 15) return 'underweight';
    return 'neutral';
  }

  /**
   * 获取子类配置方向
   */
  private getSubCategoryDirection(preference: number): AllocationDirection {
    if (preference >= 4) return 'overweight';
    if (preference <= 2) return 'underweight';
    return 'neutral';
  }

  /**
   * 构建子类推荐理由
   */
  private buildSubCategoryRationale(
    category: AssetCategory,
    subCategory: AssetSubCategory,
    phase: CyclePhase,
    preference: number
  ): string {
    const phaseConfig = CYCLE_CONFIG[phase];
    const displayName = SUB_CATEGORY_DISPLAY[subCategory].name;

    if (preference >= 4) {
      return `${displayName}在${phaseConfig.displayName}表现最优，经济环境有利于该类资产`;
    }
    if (preference >= 2) {
      return `${displayName}在${phaseConfig.displayName}表现中性，可适度配置`;
    }
    return `${displayName}在${phaseConfig.displayName}表现较弱，建议低配或回避`;
  }

  /**
   * 获取偏好的周期
   */
  private getCyclePreference(subCategory: AssetSubCategory): CyclePhase[] {
    const PREFERENCE_CYCLES: Record<AssetSubCategory, CyclePhase[]> = {
      // 股票
      tech: ['recovery'],
      financial: ['recovery'],
      energy: ['overheat', 'stagflation'],
      consumer: ['recession'],
      cyclical: ['recovery', 'overheat'],
      // 债券
      treasury: ['recession'],
      credit: ['recovery'],
      convertible: ['recovery', 'overheat'],
      high_yield: ['overheat'],
      // 商品
      precious_metal: ['stagflation'],
      energy_commodity: ['overheat', 'stagflation'],
      industrial_metal: ['recovery', 'overheat'],
      agricultural: ['stagflation'],
      // 现金
      usd: ['stagflation', 'recession'],
      cny: ['recovery'],
      eur: [],
      jpy: ['recession'],
      // 加密
      mainstream_crypto: ['overheat'],
      exchange_token: ['overheat'],
      layer2: ['overheat'],
      defi: ['recovery'],
      infrastructure: ['overheat'],
    };

    return PREFERENCE_CYCLES[subCategory] || [];
  }

  /**
   * 获取排名前N的子类资产
   */
  getTopSubCategories(
    allocations: AssetAllocation[],
    topN: number = 10
  ): SubCategoryAsset[] {
    const allSubCategories: SubCategoryAsset[] = [];

    for (const allocation of allocations) {
      for (const sub of allocation.subCategories) {
        // 添加大类权重作为二次排序
        allSubCategories.push({
          ...sub,
          // 优先级考虑大类权重
          priority: sub.priority - (allocation.weight / 100),
        });
      }
    }

    // 去重（同名保留最高优先级）
    const uniqueMap = new Map<string, SubCategoryAsset>();
    for (const sub of allSubCategories.sort((a, b) => a.priority - b.priority)) {
      if (!uniqueMap.has(sub.name)) {
        uniqueMap.set(sub.name, sub);
      }
    }

    return Array.from(uniqueMap.values()).slice(0, topN);
  }
}
