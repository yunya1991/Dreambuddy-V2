/**
 * 置信度评估器
 *
 * 位置: 6-图结构上下文压缩/planner/confidence-evaluator.ts
 *
 * 功能:
 * - 综合多个技能的输出来评估整体置信度
 * - 识别信息缺口
 * - 生成决策建议
 *
 * 核心理念: 每步完成后必须评估置信度，作为分支决策的依据
 */

import {
  SkillResult,
  SkillOutputs,
} from './skill-types';
import {
  ThinkingStepDefinition,
  StepExecutionResult,
  Gap,
  GapType,
} from './step-types';
import {
  ExecutionContext,
  ConfidenceDimensions,
} from './skill-types';

// ============================================================
// 置信度评估结果
// ============================================================

/**
 * 置信度评估结果
 */
export interface ConfidenceEvaluation {
  /** 综合置信度 (0-100) */
  overallScore: number;

  /** 分项评分 */
  dimensions: ConfidenceDimensions;

  /** 识别的缺口 */
  gaps: Gap[];

  /** 决策建议 */
  recommendation: 'ACCEPT' | 'ITERATE' | 'WARN' | 'REJECT';

  /** 决策原因 */
  reason: string;
}

// ============================================================
// 置信度评估器
// ============================================================

/**
 * 置信度评估器
 */
export class ConfidenceEvaluator {
  /**
   * 评估置信度
   */
  evaluate(
    skillResults: SkillResult[],
    stepDefinition: ThinkingStepDefinition,
    context: ExecutionContext
  ): ConfidenceEvaluation {
    // 1. 计算各项评分
    const dataCompleteness = this.calculateDataCompleteness(skillResults, stepDefinition);
    const logicalConsistency = this.calculateLogicalConsistency(skillResults);
    const crossSourceValidation = this.calculateCrossValidation(skillResults);
    const historicalAccuracy = this.calculateHistoricalAccuracy(skillResults);

    // 2. 综合计算
    const weights = { data: 0.2, logic: 0.25, cross: 0.25, history: 0.3 };
    const overallScore = Math.round(
      dataCompleteness * weights.data +
      logicalConsistency * weights.logic +
      crossSourceValidation * weights.cross +
      historicalAccuracy * weights.history
    );

    // 3. 识别缺口
    const gaps = this.identifyGaps(skillResults, stepDefinition);

    // 4. 决策建议
    const recommendation = this.makeRecommendation(
      overallScore,
      gaps,
      stepDefinition.confidenceThresholds
    );

    return {
      overallScore,
      dimensions: {
        dataCompleteness,
        logicalConsistency,
        crossValidation: crossSourceValidation,
        historicalPerformance: historicalAccuracy,
      },
      gaps,
      recommendation: recommendation.decision,
      reason: recommendation.reason,
    };
  }

  /**
   * 计算数据完整性
   */
  private calculateDataCompleteness(
    results: SkillResult[],
    stepDef: ThinkingStepDefinition
  ): number {
    if (results.length === 0) return 0;

    // 检查每个期望输出是否都有
    let matchedCount = 0;
    for (const expected of stepDef.expectedOutputs) {
      for (const result of results) {
        const outputs = result.outputs;
        // 简单的关键词匹配
        if (this.outputContains(outputs, expected)) {
          matchedCount++;
          break;
        }
      }
    }

    const matchRatio = matchedCount / stepDef.expectedOutputs.length;
    return Math.round(matchRatio * 100);
  }

  /**
   * 计算逻辑一致性
   */
  private calculateLogicalConsistency(results: SkillResult[]): number {
    if (results.length < 2) return 100; // 单技能直接满分

    // 检查方向一致性
    const directions = results
      .map(r => r.outputs.direction)
      .filter((d): d is string => d !== undefined);

    if (directions.length < 2) return 80;

    const uniqueDirections = new Set(directions);

    if (uniqueDirections.size === 1) {
      return 100; // 完全一致
    }

    // 计算置信度方差 (方差越小越一致)
    const confidences = results.map(r => r.confidence);
    const avg = confidences.reduce((a, b) => a + b, 0) / confidences.length;
    const variance = confidences.reduce((sum, c) => sum + Math.pow(c - avg, 2), 0) / confidences.length;

    return Math.max(0, Math.round(100 - Math.sqrt(variance)));
  }

  /**
   * 计算跨源印证
   */
  private calculateCrossValidation(results: SkillResult[]): number {
    if (results.length < 2) return 100; // 单技能直接满分

    // 检查是否有多个技能给出相似的结论
    const confidences = results.map(r => r.confidence);
    const avg = confidences.reduce((a, b) => a + b, 0) / confidences.length;

    // 如果所有置信度都接近平均分，说明印证好
    const variance = confidences.reduce((sum, c) => sum + Math.pow(c - avg, 2), 0) / confidences.length;
    const stdDev = Math.sqrt(variance);

    // 标准差越小，印证越好
    if (stdDev < 10) return 100;
    if (stdDev < 20) return 80;
    if (stdDev < 30) return 60;
    return Math.max(20, 100 - stdDev);
  }

  /**
   * 计算历史准确率
   */
  private calculateHistoricalAccuracy(results: SkillResult[]): number {
    if (results.length === 0) return 50; // 默认中等

    // 使用结果中携带的历史表现信息
    const accuracies = results
      .map(r => r.confidenceDimensions?.historicalPerformance)
      .filter((a): a is number => a !== undefined);

    if (accuracies.length === 0) {
      // 使用技能结果本身的置信度作为代理
      const avgConfidence = results.reduce((sum, r) => sum + r.confidence, 0) / results.length;
      return Math.round(avgConfidence * 0.8); // 打 8 折作为历史表现代理
    }

    return Math.round(accuracies.reduce((a, b) => a + b, 0) / accuracies.length);
  }

  /**
   * 识别缺口
   */
  private identifyGaps(
    results: SkillResult[],
    stepDef: ThinkingStepDefinition
  ): Gap[] {
    const gaps: Gap[] = [];

    // 1. 检查缺失输出
    const providedOutputs = new Set<string>();
    results.forEach(r => {
      Object.keys(r.outputs).forEach(key => providedOutputs.add(key));
    });

    stepDef.expectedOutputs.forEach(expected => {
      if (!this.outputMatchesAny(outputs => this.outputContains(outputs, expected), results)) {
        gaps.push({
          type: 'missing-data',
          description: `缺少期望输出: ${expected}`,
          suggestedAction: '调用补充技能获取该数据',
          priority: 'medium',
        });
      }
    });

    // 2. 检查低置信度技能
    results.forEach(result => {
      if (result.confidence < 50) {
        gaps.push({
          type: 'low-confidence',
          description: `技能 ${result.capabilityId} 置信度过低: ${result.confidence}`,
          suggestedAction: result.suggestions?.[0] || '考虑迭代或降级',
          priority: result.confidence < 30 ? 'high' : 'medium',
        });
      }
    });

    // 3. 检查逻辑冲突
    const directions = results
      .map(r => r.outputs.direction)
      .filter((d): d is string => d !== undefined);

    if (directions.length >= 2) {
      const uniqueDirections = new Set(directions);
      if (uniqueDirections.size > 1) {
        gaps.push({
          type: 'logical-conflict',
          description: `技能间方向冲突: ${Array.from(uniqueDirections).join(' vs ')}`,
          suggestedAction: '进行交叉验证或调用冲突检测技能',
          suggestedSkillId: 'dual-agent-conflict-gate',
          priority: 'high',
        });
      }
    }

    // 4. 检查数据不足
    const avgConfidence = results.reduce((sum, r) => sum + r.confidence, 0) / results.length;
    if (avgConfidence < 60 && results.length < 2) {
      gaps.push({
        type: 'insufficient-evidence',
        description: `数据来源不足: 仅 ${results.length} 个技能提供数据`,
        suggestedAction: '调用更多技能增加数据来源',
        priority: 'medium',
      });
    }

    return gaps;
  }

  /**
   * 生成决策建议
   */
  private makeRecommendation(
    overallScore: number,
    gaps: Gap[],
    thresholds: ThinkingStepDefinition['confidenceThresholds']
  ): { decision: 'ACCEPT' | 'ITERATE' | 'WARN' | 'REJECT'; reason: string } {
    // 高优先级缺口
    const highPriorityGaps = gaps.filter(g => g.priority === 'high');

    if (overallScore >= thresholds.high && highPriorityGaps.length === 0) {
      return {
        decision: 'ACCEPT',
        reason: `综合置信度 ${overallScore}% >= 高阈值 ${thresholds.high}%，且无高优先级缺口`,
      };
    }

    if (overallScore >= thresholds.medium && highPriorityGaps.length <= 1) {
      return {
        decision: 'ITERATE',
        reason: `综合置信度 ${overallScore}% >= 中阈值 ${thresholds.medium}%，可进行迭代补充`,
      };
    }

    if (overallScore >= thresholds.low) {
      return {
        decision: 'WARN',
        reason: `综合置信度 ${overallScore}% >= 低阈值 ${thresholds.low}%，建议用户关注风险`,
      };
    }

    return {
      decision: 'REJECT',
      reason: `综合置信度 ${overallScore}% < 低阈值 ${thresholds.low}%，建议降级处理`,
    };
  }

  // ============================================================
  // 辅助方法
  // ============================================================

  private outputContains(outputs: SkillOutputs, keyword: string): boolean {
    const keywordLower = keyword.toLowerCase();

    // 检查所有输出的键
    for (const key of Object.keys(outputs)) {
      if (key.toLowerCase().includes(keywordLower)) {
        return true;
      }
    }

    // 检查所有输出的值
    for (const value of Object.values(outputs)) {
      if (typeof value === 'string' && value.toLowerCase().includes(keywordLower)) {
        return true;
      }
    }

    return false;
  }

  private outputMatchesAny(
    predicate: (outputs: SkillOutputs) => boolean,
    results: SkillResult[]
  ): boolean {
    return results.some(r => predicate(r.outputs));
  }

  /**
   * 生成置信度报告
   */
  generateReport(evaluation: ConfidenceEvaluation): string {
    const lines: string[] = [];

    lines.push(`## 置信度评估报告`);
    lines.push(``);
    lines.push(`**综合置信度**: ${evaluation.overallScore}%`);
    lines.push(``);
    lines.push(`### 分项评分`);
    lines.push(`- 数据完整性: ${evaluation.dimensions.dataCompleteness}%`);
    lines.push(`- 逻辑一致性: ${evaluation.dimensions.logicalConsistency}%`);
    lines.push(`- 跨源印证: ${evaluation.dimensions.crossValidation}%`);
    lines.push(`- 历史准确率: ${evaluation.dimensions.historicalPerformance}%`);
    lines.push(``);

    if (evaluation.gaps.length > 0) {
      lines.push(`### 识别的缺口`);
      for (const gap of evaluation.gaps) {
        lines.push(`- [${gap.priority.toUpperCase()}] ${gap.type}: ${gap.description}`);
        lines.push(`  建议: ${gap.suggestedAction}`);
      }
      lines.push(``);
    }

    lines.push(`**决策**: ${evaluation.recommendation}`);
    lines.push(`**原因**: ${evaluation.reason}`);

    return lines.join('\n');
  }
}

// ============================================================
// 单例
// ============================================================

let globalEvaluator: ConfidenceEvaluator | null = null;

/**
 * 获取全局置信度评估器
 */
export function getConfidenceEvaluator(): ConfidenceEvaluator {
  if (!globalEvaluator) {
    globalEvaluator = new ConfidenceEvaluator();
  }
  return globalEvaluator;
}
