/**
 * 交叉验证器
 *
 * 位置: 6-图结构上下文压缩/planner/cross-validator.ts
 *
 * 功能:
 * - 在关键节点执行三链交叉验证
 * - 收集各链信号
 * - 调用投票计算器
 * - 生成深入分析计划
 *
 * 核心理念: S/C/F 三链在关键节点交汇，通过投票达成共识
 */

import {
  SkillChain,
  SkillResult,
} from './skill-types.ts';
import {
  StepExecutionResult,
} from './step-types.ts';
import {
  CrossValidationConfig,
  CrossValidationNode,
  ChainSignal,
  SignalDirection,
  createEmptyCrossValidationNode,
  CROSS_VALIDATION_CONFIGS,
  getDirectionLabel,
  getAgreementLevelLabel,
} from './cross-validation-types.ts';
import { VotingCalculator } from './voting-calculator.ts';
import { SerializedNode } from '../types.ts';

// ============================================================
// 交叉验证器
// ============================================================

/**
 * 交叉验证器
 */
export class CrossValidator {
  private calculator: VotingCalculator;

  constructor(calculator?: VotingCalculator) {
    this.calculator = calculator || new VotingCalculator();
  }

  /**
   * 执行交叉验证
   */
  execute(
    config: CrossValidationConfig,
    stepResults: Map<string, StepExecutionResult>,
    chainWeights?: { a_chain: number; c_chain: number; f_chain: number }
  ): CrossValidationNode {
    // 1. 收集参与的链的信号
    const signals = this.collectSignals(config, stepResults);

    if (signals.length === 0) {
      return createEmptyCrossValidationNode(config.nodeId, 'analysis');
    }

    // 2. 使用投票计算器
    const votingResult = this.calculator.calculate(signals);

    // 3. 应用降级策略（如果有冲突）
    let finalDirection = votingResult.direction;
    let finalConfidence = votingResult.overallConfidence;

    if (votingResult.conflicts.length > 0) {
      const resolved = this.calculator.resolve(votingResult, config.fallback.type);
      finalDirection = resolved;
    }

    // 4. 生成决策建议
    const { recommendedAction, reason, deepDivePlan } = this.makeDecision(
      votingResult,
      config,
      chainWeights
    );

    // 5. 创建架构节点
    const architectureNode = this.createArchitectureNode(
      config.nodeId,
      signals,
      votingResult,
      recommendedAction
    );

    return {
      nodeId: config.nodeId,
      stage: this.getStageForStep(config.afterStep, stepResults),
      triggeredAt: Date.now(),
      signals,
      consensus: {
        direction: finalDirection,
        overallConfidence: finalConfidence,
        agreementLevel: votingResult.agreementLevel,
        votes: votingResult.votes.map(v => ({
          chain: v.chain,
          weight: v.weight,
          rawConfidence: v.rawConfidence,
          weightedContribution: v.weightedContribution,
        })),
      },
      conflicts: votingResult.conflicts,
      recommendedAction,
      recommendationReason: reason,
      deepDivePlan,
      architectureNode,
    };
  }

  /**
   * 收集参与的链的信号
   */
  private collectSignals(
    config: CrossValidationConfig,
    stepResults: Map<string, StepExecutionResult>
  ): ChainSignal[] {
    const signals: ChainSignal[] = [];

    for (const stepResult of stepResults.values()) {
      // 检查该步骤的链是否在参与列表中
      if (!config.participatingChains.includes(stepResult.chain)) {
        continue;
      }

      // 从步骤结果中提取信号
      const direction = this.extractDirection(stepResult);
      const confidence = stepResult.confidence;
      const reasoning = stepResult.answer.slice(0, 200); // 截取前200字符

      signals.push({
        chain: stepResult.chain,
        direction,
        confidence,
        reasoning,
        sourceSteps: [stepResult.stepId],
        outputs: this.extractOutputs(stepResult),
      });
    }

    return signals;
  }

  /**
   * 从步骤结果提取方向
   */
  private extractDirection(stepResult: StepExecutionResult): SignalDirection {
    // 尝试从技能调用结果中提取方向
    for (const call of stepResult.skillsCalled) {
      if (call.result.outputs.direction) {
        const dir = call.result.outputs.direction as string;
        if (['long', 'short', 'neutral', 'wait'].includes(dir)) {
          return dir as SignalDirection;
        }
      }

      // 检查信号
      if (call.result.outputs.signal) {
        const signal = call.result.outputs.signal as string;
        if (signal === 'buy') return 'long';
        if (signal === 'sell') return 'short';
      }
    }

    // 默认根据置信度和答案推断
    if (stepResult.confidence >= 70) {
      // 从答案中检测方向关键词
      const answer = stepResult.answer.toLowerCase();
      if (answer.includes('做多') || answer.includes('买入') || answer.includes('做空')) {
        if (answer.includes('做多') || answer.includes('买入')) return 'long';
        if (answer.includes('做空') || answer.includes('卖出')) return 'short';
      }
    }

    return 'neutral';
  }

  /**
   * 从步骤结果提取输出
   */
  private extractOutputs(stepResult: StepExecutionResult): Record<string, unknown> {
    const outputs: Record<string, unknown> = {};

    // 合并所有技能调用的输出
    for (const call of stepResult.skillsCalled) {
      Object.assign(outputs, call.result.outputs);
    }

    // 添加步骤自身的置信度
    outputs._stepConfidence = stepResult.confidence;

    return outputs;
  }

  /**
   * 生成决策建议
   */
  private makeDecision(
    votingResult: ReturnType<VotingCalculator['calculate']>,
    config: CrossValidationConfig,
    chainWeights?: { a_chain: number; c_chain: number; f_chain: number }
  ): {
    recommendedAction: 'proceed' | 'deep_dive' | 'pause' | 'override';
    reason: string;
    deepDivePlan?: CrossValidationNode['deepDivePlan'];
  } {
    // 1. 检查是否有冲突
    if (votingResult.conflicts.length > 0) {
      // 有冲突，需要深入分析或暂停
      if (config.fallback.requireUserConfirmation) {
        return {
          recommendedAction: 'pause',
          reason: `检测到 ${votingResult.conflicts.length} 个冲突，需要用户确认方向`,
        };
      }

      return {
        recommendedAction: 'deep_dive',
        reason: `检测到冲突: ${votingResult.conflicts.map(c => c.description).join('; ')}`,
        deepDivePlan: {
          additionalSkills: this.suggestSkillsForConflict(votingResult.conflicts),
          expectedImprovement: 20,
          estimatedExtraCost: 500,
        },
      };
    }

    // 2. 检查一致性等级
    if (votingResult.agreementLevel === 'strong') {
      return {
        recommendedAction: 'proceed',
        reason: `三链一致性高 (${getAgreementLevelLabel(votingResult.agreementLevel)})，置信度 ${votingResult.overallConfidence}%`,
      };
    }

    if (votingResult.agreementLevel === 'moderate') {
      return {
        recommendedAction: 'proceed',
        reason: `三链有一定一致性，置信度 ${votingResult.overallConfidence}%`,
      };
    }

    if (votingResult.agreementLevel === 'weak') {
      return {
        recommendedAction: 'deep_dive',
        reason: `三链一致性较弱，建议进一步分析`,
        deepDivePlan: {
          additionalSkills: ['master-seminar', 'contradiction-theory'],
          expectedImprovement: 15,
          estimatedExtraCost: 300,
        },
      };
    }

    // agreementLevel === 'conflict'（无有效信号）→ deep_dive 而非 pause
    if (votingResult.agreementLevel === 'conflict') {
      return {
        recommendedAction: 'deep_dive',
        reason: `链间信号冲突或无有效投票，建议补充分析`,
        deepDivePlan: {
          additionalSkills: ['dual-agent-conflict-gate', 'dream-regime-detector'],
          expectedImprovement: 15,
          estimatedExtraCost: 300,
        },
      };
    }

    // 3. 检查置信度阈值（修复运算符优先级 bug）
    const threshold = config.triggerCondition.threshold ?? 60;
    if (votingResult.overallConfidence < threshold) {
      return {
        recommendedAction: 'deep_dive',
        reason: `综合置信度 ${votingResult.overallConfidence}% 低于阈值 ${threshold}%，建议补充分析`,
      };
    }

    return {
      recommendedAction: 'proceed',
      reason: `可以继续执行，置信度 ${votingResult.overallConfidence}%`,
    };
  }

  /**
   * 为冲突推荐技能
   */
  private suggestSkillsForConflict(
    conflicts: Array<{ type: string; involvedChains: SkillChain[] }>
  ): string[] {
    const skills: string[] = [];

    for (const conflict of conflicts) {
      if (conflict.type === 'direction_conflict') {
        skills.push('dual-agent-conflict-gate');
        skills.push('master-seminar');
      }
      if (conflict.type === 'confidence_gap') {
        skills.push('intelligence-monitor');
        skills.push('strategy-research');
      }
    }

    return [...new Set(skills)]; // 去重
  }

  /**
   * 获取步骤对应的阶段
   */
  private getStageForStep(
    stepId: string,
    stepResults: Map<string, StepExecutionResult>
  ): 'research' | 'analysis' | 'design' | 'validate' | 'execute' {
    const stepResult = stepResults.get(stepId);
    if (stepResult) {
      return stepResult.stage;
    }

    // 默认推断
    if (stepId.startsWith('S1') || stepId.startsWith('C1') || stepId.startsWith('F1')) {
      return 'research';
    }
    if (stepId.startsWith('S2') || stepId.startsWith('C2') || stepId.startsWith('F2')) {
      return 'analysis';
    }
    if (stepId.startsWith('S3') || stepId.startsWith('C3') || stepId.startsWith('F3')) {
      return 'design';
    }
    if (stepId.startsWith('S4') || stepId.startsWith('C4') || stepId.startsWith('F4')) {
      return 'validate';
    }
    return 'execute';
  }

  /**
   * 创建架构节点
   */
  private createArchitectureNode(
    nodeId: string,
    signals: ChainSignal[],
    votingResult: ReturnType<VotingCalculator['calculate']>,
    recommendedAction: string
  ): SerializedNode {
    return {
      id: nodeId,
      type: 'cross-validation',
      name: `交叉验证节点 ${nodeId}`,
      level: 'B',
      status: recommendedAction === 'proceed' ? 'completed' : 'pending',
      summary: `${getDirectionLabel(votingResult.direction)} (置信度 ${votingResult.overallConfidence}%)`,
      meta: {
        signals: signals.map(s => ({
          chain: s.chain,
          direction: s.direction,
          confidence: s.confidence,
        })),
        consensus: {
          direction: votingResult.direction,
          confidence: votingResult.overallConfidence,
          agreement: votingResult.agreementLevel,
        },
        conflicts: votingResult.conflicts.length,
      },
    };
  }

  /**
   * 获取交叉验证配置
   */
  getConfig(nodeId: string): CrossValidationConfig | undefined {
    return CROSS_VALIDATION_CONFIGS.find(c => c.nodeId === nodeId);
  }

  /**
   * 获取所有交叉验证配置
   */
  getAllConfigs(): CrossValidationConfig[] {
    return CROSS_VALIDATION_CONFIGS;
  }
}

// ============================================================
// 单例
// ============================================================

let globalValidator: CrossValidator | null = null;

/**
 * 获取全局交叉验证器
 */
export function getCrossValidator(): CrossValidator {
  if (!globalValidator) {
    globalValidator = new CrossValidator();
  }
  return globalValidator;
}
