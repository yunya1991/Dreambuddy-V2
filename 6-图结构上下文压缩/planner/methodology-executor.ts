/**
 * MethodologyExecutor - C 层方法论执行器（包装器模式）
 *
 * 位置: 6-图结构上下文压缩/planner/methodology-executor.ts
 *
 * 设计依据: Claude Code Superpowers 7阶段方法论
 *   借鉴其"先验证后完成"的执行理念，作为 C 层节点执行的包装器
 *
 * 核心理念:
 *   - 包装器模式：在不改变 GraphExecutor 核心逻辑的前提下增加方法论约束
 *   - 可开关：方法论层可随时关闭，回退到原有执行模式
 *   - 复杂度路由：简单任务跳过方法论，复杂任务启用
 *
 * 方法论适配点（借鉴 Superpowers）:
 *   1. 节点级 TDD - 先验证后实现（仅策略代码节点）
 *   2. 两阶段审查 - Spec合规 + 质量审查（所有节点）
 *   3. 子代理派发 - 复杂节点拆分子任务并行（高复杂度节点）
 *
 * 不改变的核心创新:
 *   - 动态图编排（非固定流水线）
 *   - 反射决策机制（CONTINUE/REDO/JUMP）
 *   - 置信度驱动
 */

import { ThinkingStepDefinition } from './step-types';
import { ExecutionContext, SkillResult } from './skill-types';
import { ComplexityLevel, PlannerContext } from './planner-types';
import { SkillsRegistry } from './skills-registry';

// ============================================================
// 类型定义
// ============================================================

/** 方法论模式 */
export type MethodologyMode = 'off' | 'light' | 'standard' | 'full';

/** 方法论配置 */
export interface MethodologyConfig {
  /** 方法论模式 */
  mode: MethodologyMode;
  /** 是否启用 TDD（仅策略代码节点） */
  enableTDD: boolean;
  /** 是否启用两阶段审查 */
  enableTwoPhaseReview: boolean;
  /** 是否启用子代理派发 */
  enableSubagents: boolean;
  /** 触发方法论的最小复杂度 */
  minComplexity: ComplexityLevel;
  /** 子代理最大数量 */
  maxSubagents: number;
}

/** 默认配置 */
const DEFAULT_CONFIG: MethodologyConfig = {
  mode: 'light',
  enableTDD: false,
  enableTwoPhaseReview: true,
  enableSubagents: false,
  minComplexity: 'standard',
  maxSubagents: 3,
};

/** 两阶段审查结果 */
export interface TwoPhaseReviewResult {
  /** 阶段1: Spec合规审查通过 */
  specCompliant: boolean;
  /** 阶段2: 质量审查通过 */
  qualityPassed: boolean;
  /** 发现的问题 */
  issues: ReviewIssue[];
  /** 是否阻塞继续执行 */
  blocking: boolean;
  /** 审查报告摘要 */
  summary: string;
}

/** 审查问题 */
export interface ReviewIssue {
  /** 严重程度 */
  severity: 'critical' | 'warning' | 'info';
  /** 问题描述 */
  description: string;
  /** 所属阶段 */
  phase: 'spec' | 'quality';
  /** 建议修复方式 */
  suggestion?: string;
}

/** 节点执行包装结果 */
export interface MethodologyExecutionResult {
  /** 原始执行结果 */
  rawResult: SkillResult;
  /** 两阶段审查结果 */
  review?: TwoPhaseReviewResult;
  /** 是否经过 TDD 流程 */
  tddApplied?: boolean;
  /** 是否使用子代理 */
  subagentUsed?: boolean;
  /** 方法耗时（毫秒） */
  methodologyOverheadMs: number;
}

// ============================================================
// MethodologyExecutor 主类
// ============================================================

/**
 * 方法论执行器 - C 层节点执行的包装器
 *
 * 包装器模式：在不改变 GraphExecutor 核心逻辑的前提下，
 * 为节点执行增加方法论约束。可随时开关，不破坏核心架构。
 */
export class MethodologyExecutor {
  private config: MethodologyConfig;
  private registry: SkillsRegistry;

  constructor(registry: SkillsRegistry, config?: Partial<MethodologyConfig>) {
    this.registry = registry;
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * 更新方法论配置
   */
  updateConfig(config: Partial<MethodologyConfig>): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * 获取当前配置
   */
  getConfig(): MethodologyConfig {
    return { ...this.config };
  }

  /**
   * 判断节点是否需要应用方法论
   */
  shouldApplyMethodology(
    step: ThinkingStepDefinition,
    context: PlannerContext,
  ): boolean {
    if (this.config.mode === 'off') return false;

    const complexity = context.complexity || 'standard';
    const complexityOrder: Record<ComplexityLevel, number> = {
      quick: 1,
      standard: 2,
      deep: 3,
    };

    const minOrder = complexityOrder[this.config.minComplexity];
    const currentOrder = complexityOrder[complexity];

    if (currentOrder < minOrder) return false;

    // light 模式：只对策略代码节点启用
    if (this.config.mode === 'light') {
      const isDevNode = step.id.includes('S5') ||
        step.id.includes('developer') ||
        step.id.includes('code') ||
        step.category === 'strategy_development';
      return isDevNode && this.config.enableTwoPhaseReview;
    }

    // standard/full 模式：对所有节点启用
    return true;
  }

  /**
   * 包装节点执行 - 添加方法论约束
   *
   * 这是核心方法：在执行节点前后增加方法论检查点
   */
  async wrapExecution(
    step: ThinkingStepDefinition,
    context: PlannerContext,
    executor: (step: ThinkingStepDefinition, ctx: PlannerContext) => Promise<SkillResult>,
  ): Promise<MethodologyExecutionResult> {
    const startTime = Date.now();
    const applyMethodology = this.shouldApplyMethodology(step, context);

    if (!applyMethodology) {
      const rawResult = await executor(step, context);
      return {
        rawResult,
        methodologyOverheadMs: Date.now() - startTime,
      };
    }

    // TDD 阶段（仅策略代码节点，且配置启用）
    let tddApplied = false;
    if (this.config.enableTDD && this.isTDDApplicable(step)) {
      tddApplied = true;
      // TDD 流程由节点内部实现，这里仅做标记
      // 实际 TDD 逻辑在 dev-chain 的 S5 执行引擎中
    }

    // 执行原始节点
    const rawResult = await executor(step, context);

    // 两阶段审查
    let review: TwoPhaseReviewResult | undefined;
    if (this.config.enableTwoPhaseReview) {
      review = this.performTwoPhaseReview(step, rawResult, context);
    }

    const overheadMs = Date.now() - startTime;

    return {
      rawResult,
      review,
      tddApplied,
      methodologyOverheadMs: overheadMs,
    };
  }

  /**
   * 判断节点是否适用 TDD
   */
  private isTDDApplicable(step: ThinkingStepDefinition): boolean {
    const devKeywords = ['S5', 'developer', 'code', 'strategy_dev', 'strategy_development'];
    const id = step.id.toLowerCase();
    const category = (step.category || '').toLowerCase();
    return devKeywords.some(kw => id.includes(kw.toLowerCase()) || category.includes(kw.toLowerCase()));
  }

  /**
   * 执行两阶段审查
   *
   * 阶段1: Spec 合规审查 - 是否符合计划要求
   * 阶段2: 质量审查 - 置信度/完整性/边界情况
   */
  performTwoPhaseReview(
    step: ThinkingStepDefinition,
    result: SkillResult,
    context: PlannerContext,
  ): TwoPhaseReviewResult {
    const issues: ReviewIssue[] = [];

    // ===== 阶段1: Spec 合规审查 =====
    let specCompliant = true;

    // 检查1: 执行是否成功
    if (!result.success) {
      issues.push({
        severity: 'critical',
        phase: 'spec',
        description: `节点执行失败: ${result.error || '未知错误'}`,
        suggestion: '检查节点输入和执行环境',
      });
      specCompliant = false;
    }

    // 检查2: 是否有产出（summary 非空）
    if (!result.summary || result.summary.trim().length === 0) {
      issues.push({
        severity: 'critical',
        phase: 'spec',
        description: '节点执行无摘要产出',
        suggestion: '确保节点返回 summary 字段',
      });
      specCompliant = false;
    }

    // ===== 阶段2: 质量审查 =====
    let qualityPassed = true;

    // 检查3: 置信度是否达标
    const confidence = result.confidence ?? 0;
    const targetConfidence = context.targetConfidence ?? 70;
    if (confidence < targetConfidence * 0.7) {
      issues.push({
        severity: 'warning',
        phase: 'quality',
        description: `置信度过低: ${Math.round(confidence * 100)}% (目标: ${targetConfidence}%)`,
        suggestion: '考虑追加更多分析节点或补充数据',
      });
      qualityPassed = false;
    }

    // 检查4: 是否有置信度相关警告
    if (result.uncertainty && result.uncertainty.length > 0) {
      for (const uncertainty of result.uncertainty.slice(0, 3)) {
        issues.push({
          severity: 'warning',
          phase: 'quality',
          description: `不确定因素: ${uncertainty}`,
        });
      }
    }

    // 检查5: 是否发现风险/问题
    if (result.risks && result.risks.length > 0) {
      for (const risk of result.risks.slice(0, 2)) {
        issues.push({
          severity: 'info',
          phase: 'quality',
          description: `风险提示: ${risk}`,
        });
      }
    }

    // ===== 综合判断 =====
    const hasCritical = issues.some(i => i.severity === 'critical');
    const hasWarning = issues.some(i => i.severity === 'warning');

    let summary: string;
    if (hasCritical) {
      summary = '审查不通过：存在严重问题，需要修复后继续';
    } else if (hasWarning) {
      summary = '审查通过（有警告）：可继续执行，建议关注警告项';
    } else {
      summary = '审查通过：Spec 合规且质量达标';
    }

    return {
      specCompliant,
      qualityPassed,
      issues,
      blocking: hasCritical,
      summary,
    };
  }

  /**
   * 获取审查报告（文本格式）
   */
  formatReviewReport(review: TwoPhaseReviewResult): string {
    const lines: string[] = [];
    lines.push('## 两阶段审查报告');
    lines.push('');
    lines.push(`**结论**: ${review.summary}`);
    lines.push('');

    if (review.issues.length === 0) {
      lines.push('未发现问题。');
      return lines.join('\n');
    }

    const criticalIssues = review.issues.filter(i => i.severity === 'critical');
    const warningIssues = review.issues.filter(i => i.severity === 'warning');
    const infoIssues = review.issues.filter(i => i.severity === 'info');

    if (criticalIssues.length > 0) {
      lines.push('### 🔴 严重问题');
      lines.push('');
      for (const issue of criticalIssues) {
        lines.push(`- **[${issue.phase}]** ${issue.description}`);
        if (issue.suggestion) {
          lines.push(`  - 建议: ${issue.suggestion}`);
        }
      }
      lines.push('');
    }

    if (warningIssues.length > 0) {
      lines.push('### 🟡 警告');
      lines.push('');
      for (const issue of warningIssues) {
        lines.push(`- **[${issue.phase}]** ${issue.description}`);
        if (issue.suggestion) {
          lines.push(`  - 建议: ${issue.suggestion}`);
        }
      }
      lines.push('');
    }

    if (infoIssues.length > 0) {
      lines.push('### ℹ️ 提示');
      lines.push('');
      for (const issue of infoIssues) {
        lines.push(`- **[${issue.phase}]** ${issue.description}`);
      }
      lines.push('');
    }

    return lines.join('\n');
  }
}

/**
 * 根据意图和复杂度自动选择方法论模式
 */
export function selectMethodologyMode(
  intent: string,
  complexity: ComplexityLevel,
): MethodologyMode {
  const fullPipelineIntents = ['scenario_sim', 'strategy_verify', 'execute_trade', 'developer'];
  const analysisIntents = ['deep_analysis', 'risk_alert'];

  if (fullPipelineIntents.includes(intent)) {
    return complexity === 'deep' ? 'full' : 'standard';
  }
  if (analysisIntents.includes(intent)) {
    return complexity === 'deep' ? 'standard' : 'light';
  }
  return 'light';
}
