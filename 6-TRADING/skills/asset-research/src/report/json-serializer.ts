/**
 * JSON序列化模块
 */

import { ResearchResult, MultiVersionResult } from '../types';

/**
 * JSON序列化器
 */
export class JsonSerializer {
  /**
   * 序列化研究结果
   */
  serialize(result: ResearchResult): string {
    return JSON.stringify(result, null, 2);
  }

  /**
   * 反序列化研究结果
   */
  deserialize(json: string): ResearchResult {
    return JSON.parse(json) as ResearchResult;
  }

  /**
   * 序列化为紧凑格式（无缩进）
   */
  serializeCompact(result: ResearchResult): string {
    return JSON.stringify(result);
  }

  /**
   * 提取关键字段（用于快速预览）
   */
  extractSummary(result: ResearchResult): {
    version: string;
    phase: string;
    topAssets: string[];
    confidence: number;
    timestamp: string;
  } {
    const topAssets = result.topSubCategories
      .slice(0, 5)
      .map(sub => sub.displayName);

    return {
      version: result.version,
      phase: result.cycle.currentPhase,
      topAssets,
      confidence: result.confidence,
      timestamp: result.timestamp,
    };
  }

  /**
   * 序列化为可存储格式（包含元数据）
   */
  serializeForStorage(result: ResearchResult): {
    id: string;
    data: ResearchResult;
    metadata: {
      createdAt: string;
      hash: string;
      size: number;
    };
  } {
    const hash = this.simpleHash(JSON.stringify(result));

    return {
      id: `research_${result.version}_${Date.now()}`,
      data: result,
      metadata: {
        createdAt: new Date().toISOString(),
        hash,
        size: JSON.stringify(result).length,
      },
    };
  }

  /**
   * 生成简单的哈希值
   */
  private simpleHash(str: string): string {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return Math.abs(hash).toString(16);
  }

  /**
   * 导出为CSV格式（子类资产表）
   */
  exportToCsv(result: ResearchResult): string {
    const lines: string[] = [
      '优先级,子类名称,大类,配置方向,推荐理由'
    ];

    for (const allocation of result.assetAllocation) {
      for (const sub of allocation.subCategories) {
        lines.push([
          sub.priority,
          sub.displayName,
          allocation.displayName,
          sub.direction,
          `"${sub.rationale.replace(/"/g, '""')}"`
        ].join(','));
      }
    }

    return lines.join('\n');
  }

  /**
   * 导出多版本对比为CSV
   */
  exportComparisonToCsv(results: ResearchResult[]): string {
    const lines: string[] = [
      '版本,周期,置信度,Top1资产,Top2资产,Top3资产'
    ];

    for (const result of results) {
      const topAssets = result.topSubCategories.slice(0, 3).map(s => s.displayName);
      lines.push([
        result.version,
        result.cycle.currentPhase,
        (result.confidence * 100).toFixed(0) + '%',
        ...topAssets,
        ...Array(3 - topAssets.length).fill('')
      ].join(','));
    }

    return lines.join('\n');
  }
}
