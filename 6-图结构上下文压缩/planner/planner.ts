/**
 * 执行规划器 - AI 推理的核心调度器
 *
 * 位置: 6-图结构上下文压缩/planner/planner.ts
 *
 * 功能:
 * - 根据用户请求生成执行计划
 * - 逐步执行思维步骤
 * - 管理技能调用和置信度评估
 * - 处理迭代和降级
 *
 * 核心理念: AI 在每个思维步骤内做动态决策，选择最佳技能组合
 */

import {
  SkillCapability,
  SkillResult,
  ExecutionContext,
  createSuccessResult,
  createFailureResult,
  createFallbackResult,
} from './skill-types';
import {
  ThinkingStepDefinition,
  StepExecutionResult,
  StepDecision,
  Gap,
  S_CHAIN_STEPS,
  C_CHAIN_STEPS,
  F_CHAIN_STEPS,
  getStepDefinition,
} from './step-types';
import {
  PlannerContext,
  ExecutionPlan,
  PlannerExecutionResult,
  PlannedStep,
  PlannedCrossValidation,
  CrossValidationResult,
  PlannerConclusion,
  createDefaultPlannerContext,
  inferComplexity,
  calculatePlanCost,
  IntentType,
} from './planner-types';
import {
  SkillsRegistry,
  getSkillsRegistry,
} from './skills-registry';
import { SkillSelector } from './skill-selector';
import { ConfidenceEvaluator } from './confidence-evaluator';
import { VotingCalculator } from './voting-calculator';
import { CrossValidator, getCrossValidator } from './cross-validator';
import {
  CROSS_VALIDATION_CONFIGS,
  SignalDirection,
} from './cross-validation-types';
import { SerializedNode } from '../types';

// ============================================================
// 执行规划器
// ============================================================

/**
 * 执行规划器
 *
 * 使用示例:
 * ```typescript
 * const planner = new ExecutionPlanner();
 * const result = await planner.execute({
 *   sessionId: 'xxx',
 *   userRequest: 'BTC 下周应该怎么操作？',
 *   intent: 'deep_analysis',
 * });
 * ```
 */
export class ExecutionPlanner {
  private registry: SkillsRegistry;
  private skillSelector: SkillSelector;
  private confidenceEvaluator: ConfidenceEvaluator;
  private crossValidator: CrossValidator;

  constructor(registry?: SkillsRegistry) {
    this.registry = registry || getSkillsRegistry();
    this.skillSelector = new SkillSelector(this.registry);
    this.confidenceEvaluator = new ConfidenceEvaluator();
    this.crossValidator = getCrossValidator();
  }

  // ============================================================
  // 主执行入口
  // ============================================================

  /**
   * 执行完整的规划流程
   */
  async execute(context: PlannerContext): Promise<PlannerExecutionResult> {
    const startTime = Date.now();

    try {
      // 1. 创建执行计划
      const plan = this.createPlan(context);

      // 2. 执行计划
      const { steps, crossValidationResults } = await this.executePlan(plan, context);

      // 3. 生成结论
      const conclusion = this.generateConclusion(steps, crossValidationResults, context);

      // 4. 计算总成本
      const totalTokens = steps.reduce((sum, s) => sum + (s.tokensUsed || 0), 0);
      const totalLatency = Date.now() - startTime;
      const overallConfidence = this.calculateOverallConfidence(steps);

      return {
        success: true,
        planId: plan.planId,
        steps,
        crossValidationResults,
        totalTokensUsed: totalTokens,
        totalLatencyMs: totalLatency,
        overallConfidence,
        conclusion,
      };
    } catch (error) {
      return {
        success: false,
        planId: `plan_error_${Date.now()}`,
        steps: [],
        totalTokensUsed: 0,
        totalLatencyMs: Date.now() - startTime,
        overallConfidence: 0,
        error: error instanceof Error ? error.message : 'Unknown error',
      };
    }
  }

  /**
   * 创建执行计划
   */
  createPlan(context: PlannerContext): ExecutionPlan {
    // 1. 确定使用的链
    const chains = this.determineChains(context);

    // 2. 选择主要链（使用 S 链作为主链）
    const primaryChain = 'S';

    // 3. 获取步骤定义
    const steps = this.getStepsForChain(primaryChain, context);

    // 4. 确定交叉验证节点
    const crossValidationNodes = this.determineCrossValidationNodes(steps);

    // 5. 计算成本
    const { tokens, latencyMs } = calculatePlanCost(
      steps.map(s => ({
        stepId: s.id,
        chain: s.chain,
        stage: s.stage,
        selectedSkills: [],
        expectedConfidence: 70,
        acceptableMinConfidence: 50,
        allowIteration: s.allowIteration ?? true,
        maxIterations: s.maxIterations ?? 2,
      }))
    );

    return {
      planId: `plan_${context.sessionId}_${Date.now()}`,
      createdAt: Date.now(),
      steps: steps.map(s => this.createPlannedStep(s, context)),
      estimatedTokens: tokens,
      estimatedLatencyMs: latencyMs,
      crossValidationNodes,
      metadata: {
        intent: context.intent,
        complexity: context.complexity,
        chains,
        primaryChain,
      },
    };
  }

  // ============================================================
  // 计划执行
  // ============================================================

  /**
   * 执行计划
   */
  private async executePlan(
    plan: ExecutionPlan,
    context: PlannerContext
  ): Promise<{ steps: StepExecutionResult[]; crossValidationResults: CrossValidationResult[] }> {
    const steps: StepExecutionResult[] = [];
    const crossValidationResults: CrossValidationResult[] = [];
    const stepResultsMap = new Map<string, StepExecutionResult>();

    // 构建执行上下文（累积前序结果）
    let executionContext = { ...context };

    // 执行每个步骤
    for (const plannedStep of plan.steps) {
      const stepDef = plannedStep.definition!;

      // 更新上下文，加入前序结果
      executionContext = {
        ...executionContext,
        priorOutputs: Object.fromEntries(
          steps.map(s => [s.stepId, createSuccessResult(s.stepId, { answer: s.answer }, s.confidence)])
        ),
      };

      // 执行步骤
      const stepResult = await this.executeStep(stepDef, plannedStep, executionContext);
      steps.push(stepResult);
      stepResultsMap.set(stepDef.id, stepResult);

      // 检查是否到达交叉验证节点
      const cvConfig = CROSS_VALIDATION_CONFIGS.find(c => c.afterStep === stepDef.id);
      if (cvConfig) {
        const cvResult = this.crossValidator.execute(cvConfig, stepResultsMap, context.chainWeights);
        crossValidationResults.push({
          nodeId: cvResult.nodeId,
          signals: cvResult.signals.map(s => ({
            chain: s.chain,
            direction: s.direction,
            confidence: s.confidence,
            reasoning: s.reasoning,
            sourceSteps: s.sourceSteps,
          })),
          consensus: {
            direction: cvResult.consensus.direction,
            overallConfidence: cvResult.consensus.overallConfidence,
            agreementLevel: cvResult.consensus.agreementLevel,
            votes: cvResult.consensus.votes,
          },
          conflicts: cvResult.conflicts,
          recommendedAction: cvResult.recommendedAction,
          deepDivePlan: cvResult.deepDivePlan,
        });

        // 如果需要暂停，等待用户确认
        if (cvResult.recommendedAction === 'pause') {
          break;
        }
      }

      // 如果决策是跳过，停止执行
      if (stepResult.decision === 'skip') {
        break;
      }
    }

    return { steps, crossValidationResults };
  }

  /**
   * 执行单个步骤
   */
  private async executeStep(
    stepDef: ThinkingStepDefinition,
    plannedStep: PlannedStep,
    context: ExecutionContext
  ): Promise<StepExecutionResult> {
    const startTime = Date.now();
    const skillCallRecords: StepExecutionResult['skillsCalled'] = [];
    let iteration = 0;
    const maxIterations = plannedStep.maxIterations;
    let currentConfidence = 0;
    let currentGaps: Gap[] = [];

    // 执行循环（支持迭代）
    while (iteration < maxIterations) {
      iteration++;

      // 1. 选择技能
      const selectedSkills = plannedStep.selectedSkills;
      if (iteration > 1) {
        // 迭代时，可能需要选择补充技能
        const currentSkillIds = skillCallRecords.map(s => s.skillId);
        const gapFilling = this.skillSelector.selectGapFilling(
          currentGaps[0]?.type || 'missing-data',
          context,
          new Set(currentSkillIds)
        );
        // 添加补充技能
        for (const filling of gapFilling) {
          if (!selectedSkills.find(s => s.skillId === filling.skillId)) {
            selectedSkills.push(filling);
          }
        }
      }

      // 2. 调用技能
      for (const skillCall of selectedSkills) {
        const skill = this.registry.get(skillCall.skillId);
        if (!skill) continue;

        try {
          const result = await this.registry.invoke(skillCall.skillId, {}, context);
          skillCallRecords.push({
            skillId: skill.metadata.id,
            skillName: skill.metadata.name,
            result,
            invocationIndex: iteration,
            latencyMs: result.latencyMs,
          });
        } catch (error) {
          skillCallRecords.push({
            skillId: skill.metadata.id,
            skillName: skill.metadata.name,
            result: createFailureResult(
              skill.metadata.id,
              error instanceof Error ? error.message : 'Unknown error'
            ),
            invocationIndex: iteration,
          });
        }
      }

      // 3. 评估置信度
      const skillResults = skillCallRecords
        .filter(r => r.invocationIndex === iteration)
        .map(r => r.result);

      const evaluation = this.confidenceEvaluator.evaluate(skillResults, stepDef, context);
      currentConfidence = evaluation.overallScore;
      currentGaps = evaluation.gaps;

      // 4. 检查是否需要继续迭代
      if (evaluation.recommendation === 'ACCEPT') {
        break;
      }

      if (iteration >= maxIterations) {
        break;
      }
    }

    // 5. 生成答案
    const answer = this.generateAnswer(skillCallRecords, currentConfidence);

    // 6. 做出决策
    const decision = this.makeDecision(currentConfidence, currentGaps, stepDef, iteration);

    // 7. 创建架构节点
    const architectureNode = this.createArchitectureNode(
      stepDef,
      skillCallRecords,
      currentConfidence,
      decision,
      iteration
    );

    const endTime = Date.now();

    return {
      stepId: stepDef.id,
      stage: stepDef.stage,
      chain: stepDef.chain,
      status: decision === 'skip' ? 'skipped' : 'completed',
      coreQuestion: stepDef.coreQuestion,
      answer,
      skillsCalled: skillCallRecords,
      confidence: currentConfidence,
      confidenceDimensions: {
        dataCompleteness: skillCallRecords.length > 0
          ? skillCallRecords.reduce((sum, r) => sum + (r.result.confidenceDimensions?.dataCompleteness || r.result.confidence), 0) / skillCallRecords.length
          : 0,
        logicalConsistency: currentConfidence,
      },
      gaps: currentGaps,
      decision,
      decisionReason: this.getDecisionReason(decision, currentConfidence, stepDef),
      iterations: iteration > 1 ? iteration : undefined,
      tokensUsed: skillCallRecords.reduce((sum, r) => sum + (r.result.tokensUsed || 0), 0),
      latencyMs: endTime - startTime,
      architectureNode,
    };
  }

  // ============================================================
  // 辅助方法
  // ============================================================

  /**
   * 确定使用的链
   */
  private determineChains(context: PlannerContext): SkillChain[] {
    switch (context.tradingMode) {
      case 'ai_skill':
        return ['S'];
      case 'classic':
        return ['C'];
      case 'hybrid':
        return ['S', 'C', 'F'];
      default:
        return ['S'];
    }
  }

  /**
   * 获取链的步骤
   */
  private getStepsForChain(chain: SkillChain, context: PlannerContext): ThinkingStepDefinition[] {
    let steps: ThinkingStepDefinition[];

    switch (chain) {
      case 'S':
        steps = [...S_CHAIN_STEPS];
        break;
      case 'C':
        steps = [...C_CHAIN_STEPS];
        break;
      case 'F':
        steps = [...F_CHAIN_STEPS];
        break;
    }

    // 根据复杂度调整步骤数量
    switch (context.complexity) {
      case 'quick':
        return steps.slice(0, 1); // 只执行第一步
      case 'standard':
        return steps.slice(0, 3); // 执行前3步
      case 'deep':
        return steps; // 执行全部
    }
  }

  /**
   * 创建计划的步骤
   */
  private createPlannedStep(stepDef: ThinkingStepDefinition, context: PlannerContext): PlannedStep {
    const recommendations = this.registry.recommend(context);
    const selectedSkills = this.skillSelector.select(stepDef, context);

    return {
      stepId: stepDef.id,
      chain: stepDef.chain,
      stage: stepDef.stage,
      selectedSkills,
      expectedConfidence: 70,
      acceptableMinConfidence: stepDef.confidenceThresholds.medium,
      allowIteration: stepDef.allowIteration ?? true,
      maxIterations: stepDef.maxIterations ?? 2,
      definition: stepDef,
    };
  }

  /**
   * 确定交叉验证节点
   */
  private determineCrossValidationNodes(steps: ThinkingStepDefinition[]): PlannedCrossValidation[] {
    const result: PlannedCrossValidation[] = [];

    for (const step of steps) {
      if (step.isCrossValidationPoint) {
        const config = CROSS_VALIDATION_CONFIGS.find(c => c.afterStep === step.id);
        if (config) {
          result.push({
            nodeId: config.nodeId,
            afterStep: config.afterStep,
            participatingChains: config.participatingChains,
            weights: config.weights,
            triggerCondition: config.triggerCondition,
            fallback: config.fallback,
          });
        }
      }
    }

    return result;
  }

  /**
   * 生成答案
   */
  private generateAnswer(
    skillCallRecords: StepExecutionResult['skillsCalled'],
    confidence: number
  ): string {
    if (skillCallRecords.length === 0) {
      return '未调用任何技能';
    }

    const summaries = skillCallRecords.map(r => {
      const output = r.result.outputs;
      if (output.direction) {
        return `${r.skillName}: ${output.direction} (置信度 ${r.result.confidence}%)`;
      }
      if (output.analysis) {
        return `${r.skillName}: ${String(output.analysis).slice(0, 100)}...`;
      }
      return `${r.skillName}: 完成 (置信度 ${r.result.confidence}%)`;
    });

    return [
      `综合置信度: ${confidence}%`,
      '',
      ...summaries,
    ].join('\n');
  }

  /**
   * 做出决策
   */
  private makeDecision(
    confidence: number,
    gaps: Gap[],
    stepDef: ThinkingStepDefinition,
    iteration: number
  ): StepDecision {
    const { high, medium, low } = stepDef.confidenceThresholds;

    if (confidence >= high) {
      return 'proceed';
    }

    if (confidence >= medium && iteration < (stepDef.maxIterations || 2)) {
      return 'iterate';
    }

    if (confidence >= low) {
      return 'warn';
    }

    return 'skip';
  }

  /**
   * 获取决策原因
   */
  private getDecisionReason(decision: StepDecision, confidence: number, stepDef: ThinkingStepDefinition): string {
    switch (decision) {
      case 'proceed':
        return `置信度 ${confidence}% >= 高阈值 ${stepDef.confidenceThresholds.high}%，进入下一步`;
      case 'iterate':
        return `置信度 ${confidence}% >= 中阈值 ${stepDef.confidenceThresholds.medium}%，进行迭代`;
      case 'warn':
        return `置信度 ${confidence}% >= 低阈值 ${stepDef.confidenceThresholds.low}%，警告继续`;
      case 'skip':
        return `置信度 ${confidence}% < 低阈值 ${stepDef.confidenceThresholds.low}%，跳过`;
      default:
        return '未知决策';
    }
  }

  /**
   * 创建架构节点
   */
  private createArchitectureNode(
    stepDef: ThinkingStepDefinition,
    skillCallRecords: StepExecutionResult['skillsCalled'],
    confidence: number,
    decision: StepDecision,
    iteration: number
  ): SerializedNode {
    return {
      id: stepDef.id,
      type: 'thinking-step',
      name: stepDef.label,
      level: 'A',
      status: decision === 'skip' ? 'skipped' : 'completed',
      tokens: skillCallRecords.reduce((sum, r) => sum + (r.result.tokensUsed || 0), 0),
      latencyMs: skillCallRecords.reduce((sum, r) => sum + (r.latencyMs || 0), 0),
      summary: `${stepDef.label}: 置信度 ${confidence}%`,
      meta: {
        stage: stepDef.stage,
        chain: stepDef.chain,
        decision,
        iteration,
        skillsInvoked: skillCallRecords.map(s => s.skillId),
      },
    };
  }

  /**
   * 计算总体置信度
   */
  private calculateOverallConfidence(steps: StepExecutionResult[]): number {
    if (steps.length === 0) return 0;

    // 加权平均，最近的步骤权重更高
    let totalWeight = 0;
    let weightedSum = 0;

    steps.forEach((step, index) => {
      const weight = index + 1; // 越近权重越高
      weightedSum += step.confidence * weight;
      totalWeight += weight;
    });

    return Math.round(weightedSum / totalWeight);
  }

  /**
   * 生成结论
   */
  private generateConclusion(
    steps: StepExecutionResult[],
    crossValidationResults: CrossValidationResult[],
    context: PlannerContext
  ): PlannerConclusion {
    // 找到最终方向
    const lastCV = crossValidationResults[crossValidationResults.length - 1];
    const direction: SignalDirection = lastCV?.consensus.direction || 'neutral';

    // 收集关键决策点
    const keyDecisionPoints = steps
      .filter(s => s.confidence >= 70)
      .map(s => `${s.stepId}: ${s.answer.slice(0, 50)}...`);

    // 收集推理路径
    const reasoningPath = steps.map(s => s.stepId);

    // 生成下一步建议
    const nextSteps: PlannerConclusion['nextSteps'] = [];

    if (direction !== 'neutral') {
      nextSteps.push({
        action: direction === 'long' ? 'EXECUTE' : 'EXECUTE',
        reasoning: `三链投票结果: ${direction}，置信度 ${lastCV?.consensus.overallConfidence || 0}%`,
        estimatedConfidence: lastCV?.consensus.overallConfidence,
      });
    } else {
      nextSteps.push({
        action: 'WAIT_FOR_SIGNAL',
        reasoning: '三链投票结果不明确，需要等待更多信息',
        triggerConditions: ['市场出现明确信号', '置信度提升'],
      });
    }

    return {
      direction,
      confidence: lastCV?.consensus.overallConfidence || this.calculateOverallConfidence(steps),
      participatingChains: ['S', 'C', 'F'],
      keyDecisionPoints,
      reasoningPath,
      nextSteps,
    };
  }
}

// ============================================================
// 便捷函数
// ============================================================

/**
 * 快速执行编排
 */
export async function orchestrate(
  sessionId: string,
  userRequest: string,
  intent: IntentType = 'deep_analysis',
  options?: Partial<PlannerContext>
): Promise<PlannerExecutionResult> {
  const context = createDefaultPlannerContext(sessionId, userRequest, intent);
  Object.assign(context, options);

  const planner = new ExecutionPlanner();
  return planner.execute(context);
}
