/**
 * 标准输出管理器
 * 生成供其他模块读取的标准JSON格式
 */

import { ResearchResult, MultiVersionResult, CyclePhase, AssetCategory } from '../types';

const PHASE_NAMES: Record<string, string> = {
  recovery: '复苏期',
  overheat: '过热期',
  stagflation: '滞胀期',
  recession: '衰退期',
};

const CATEGORY_NAMES: Record<string, string> = {
  stock: '股票',
  bond: '债券',
  commodity: '商品',
  cash: '现金/货币',
  crypto: '加密货币',
};

const DIRECTION_NAMES: Record<string, string> = {
  overweight: '超配',
  neutral: '标配',
  underweight: '低配',
};

export interface StandardOutput {
  metadata: {
    generatedAt: string;
    engineVersion: string;
    region: string;
    dataSource: string;
    reportType: 'monthly' | 'quarterly' | 'quick' | 'on-demand';
  };
  cycle: {
    currentPhase: string;
    phaseName: string;
    confidence: number;
    indicators: Array<{
      name: string;
      value: string;
      unit?: string;
      trend: string;
      source: string;
    }>;
    rationale: string;
  };
  allocation: Record<string, number>;
  topAssets: Array<{
    rank: number;
    name: string;
    displayName: string;
    category: string;
    categoryName: string;
    direction: string;
    directionName: string;
    rationale?: string;
  }>;
  bottomAssets: Array<{
    rank: number;
    name: string;
    displayName: string;
    category: string;
    direction: string;
  }>;
  outlook: {
    shortTerm: {
      phase: string;
      phaseName: string;
      probability: number;
      keyDrivers?: string[];
    };
    midTerm: {
      phase: string;
      phaseName: string;
      probability: number;
      keyDrivers?: string[];
    };
    longTerm: {
      phase: string;
      phaseName: string;
      probability: number;
      keyDrivers?: string[];
    };
  };
  riskAlerts: string[];
}

/**
 * 标准输出管理器
 */
export class StandardOutputManager {
  /**
   * 生成标准输出JSON
   */
  static generate(
    result: ResearchResult,
    options?: {
      reportType?: 'monthly' | 'quarterly' | 'quick' | 'on-demand';
    }
  ): StandardOutput {
    const allocation: Record<string, number> = {};
    for (const item of result.assetAllocation) {
      allocation[item.category] = item.weight;
    }

    const topAssets = result.topSubCategories.slice(0, 10).map((sub, i) => ({
      rank: i + 1,
      name: sub.name,
      displayName: sub.displayName,
      category: '',
      categoryName: this.extractCategory(sub),
      direction: sub.direction,
      directionName: DIRECTION_NAMES[sub.direction] || sub.direction,
      rationale: sub.rationale,
    }));

    const bottomAssets = result.topSubCategories.slice(-5).reverse().map((sub, i) => ({
      rank: result.topSubCategories.length - 4 + i,
      name: sub.name,
      displayName: sub.displayName,
      category: '',
      direction: sub.direction,
    }));

    const output: StandardOutput = {
      metadata: {
        generatedAt: new Date().toISOString(),
        engineVersion: result.version,
        region: result.region,
        dataSource: result.dataSources.map(d => d.name).join(', '),
        reportType: options?.reportType || 'on-demand',
      },
      cycle: {
        currentPhase: result.cycle.currentPhase,
        phaseName: PHASE_NAMES[result.cycle.currentPhase] || result.cycle.currentPhase,
        confidence: result.cycle.confidence,
        indicators: result.cycle.indicators.map(ind => ({
          name: ind.name,
          value: ind.value,
          unit: ind.unit,
          trend: ind.trend,
          source: ind.source,
        })),
        rationale: result.cycle.rationale,
      },
      allocation,
      topAssets,
      bottomAssets,
      outlook: this.extractOutlook(result),
      riskAlerts: this.extractRiskAlerts(result),
    };

    return output;
  }

  /**
   * 保存到文件
   */
  static saveToFile(
    result: ResearchResult,
    filePath: string,
    options?: {
      reportType?: 'monthly' | 'quarterly' | 'quick' | 'on-demand';
    }
  ): void {
    const output = this.generate(result, options);
    const fs = require('fs');
    const path = require('path');

    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    fs.writeFileSync(filePath, JSON.stringify(output, null, 2));
    console.log(`[StandardOutput] 已保存到: ${filePath}`);
  }

  /**
   * 从文件读取
   */
  static readFromFile(filePath: string): StandardOutput | null {
    try {
      const fs = require('fs');
      if (!fs.existsSync(filePath)) {
        return null;
      }
      const data = fs.readFileSync(filePath, 'utf-8');
      return JSON.parse(data);
    } catch (error) {
      console.error('[StandardOutput] 读取文件失败:', error);
      return null;
    }
  }

  /**
   * 提取大类（从子资产推断）
   */
  private static extractCategory(sub: any): string {
    const catMap: Record<string, string> = {
      tech: '股票',
      financial: '股票',
      energy: '股票',
      consumer: '股票',
      cyclical: '股票',
      treasury: '债券',
      credit: '债券',
      convertible: '债券',
      high_yield: '债券',
      precious_metal: '商品',
      energy_commodity: '商品',
      industrial_metal: '商品',
      agricultural: '商品',
      usd: '现金/货币',
      cny: '现金/货币',
      eur: '现金/货币',
      jpy: '现金/货币',
      mainstream_crypto: '加密货币',
      exchange_token: '加密货币',
      layer2: '加密货币',
      defi: '加密货币',
      infrastructure: '加密货币',
    };
    return catMap[sub.name] || '其他';
  }

  /**
   * 提取周期展望
   */
  private static extractOutlook(result: ResearchResult): StandardOutput['outlook'] {
    const defaultOutlook = {
      phase: result.cycle.currentPhase,
      phaseName: PHASE_NAMES[result.cycle.currentPhase],
      probability: result.cycle.confidence,
    };

    return {
      shortTerm: {
        ...defaultOutlook,
        keyDrivers: ['经济增长趋势', '通胀走势', '政策动向'],
      },
      midTerm: {
        ...defaultOutlook,
        keyDrivers: ['经济周期演进', '政策周期', '外部环境'],
      },
      longTerm: {
        ...defaultOutlook,
        keyDrivers: ['结构性因素', '长期趋势'],
      },
    };
  }

  /**
   * 提取风险提示
   */
  private static extractRiskAlerts(result: ResearchResult): string[] {
    const alerts: string[] = [];

    if (result.confidence < 0.6) {
      alerts.push('模型置信度较低，建议谨慎参考');
    }

    if (result.cycle.currentPhase === 'stagflation') {
      alerts.push('滞胀期风险：经济增长放缓与高通胀并存，资产配置难度加大');
    }

    if (result.cycle.currentPhase === 'recession') {
      alerts.push('衰退期风险：经济下行压力大，风险资产可能承压');
    }

    alerts.push('美林投资时钟基于历史规律，未来市场可能呈现不同特征');
    alerts.push('宏观经济数据存在发布延迟，周期判定可能滞后');

    return alerts;
  }
}
