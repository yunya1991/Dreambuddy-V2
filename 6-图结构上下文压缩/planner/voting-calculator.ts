/**
 * 投票计算器
 *
 * 位置: 6-图结构上下文压缩/planner/voting-calculator.ts
 *
 * 功能:
 * - 计算三链加权投票
 * - 检测冲突
 * - 生成决策建议
 *
 * 核心理念: 在关键节点进行 S/C/F 三链加权投票
 */

import {
  ChainWeights,
  SignalDirection,
} from './cross-validation-types.ts';
import {
  SkillChain,
  SkillResult,
} from './skill-types.ts';
import {
  DEFAULT_VOTING_CONFIG,
  VotingConfig,
  ChainSignal,
  VoteConsensus,
  Conflict,
  AgreementLevel,
} from './cross-validation-types.ts';

// ============================================================
// 投票结果
// ============================================================

/**
 * 投票结果
 */
export interface VotingResult {
  /** 共识方向 */
  direction: SignalDirection;

  /** 综合置信度 */
  overallConfidence: number;

  /** 一致性等级 */
  agreementLevel: AgreementLevel;

  /** 投票详情 */
  votes: Array<{
    chain: SkillChain;
    weight: number;
    rawConfidence: number;
    weightedContribution: number;
    directionScore: number;
  }>;

  /** 检测到的冲突 */
  conflicts: Conflict[];
}

// ============================================================
// 投票计算器
// ============================================================

/**
 * 投票计算器
 */
export class VotingCalculator {
  private config: VotingConfig;

  constructor(config: VotingConfig = DEFAULT_VOTING_CONFIG) {
    this.config = config;
  }

  /**
   * 计算加权投票
   */
  calculate(signals: ChainSignal[]): VotingResult {
    // 过滤掉 'wait' 信号（不参与投票）
    const activeSignals = signals.filter(s => s.direction !== 'wait');

    if (activeSignals.length === 0) {
      return {
        direction: 'wait',
        overallConfidence: 0,
        agreementLevel: 'conflict',
        votes: [],
        conflicts: [],
      };
    }

    // 1. 计算方向分数
    const directionScores = activeSignals.map(signal => ({
      chain: signal.chain,
      weight: this.getChainWeight(signal.chain),
      rawConfidence: signal.confidence,
      directionScore: this.getDirectionScore(signal.direction),
    }));

    // 2. 计算加权贡献
    const votes = directionScores.map(v => ({
      ...v,
      weightedContribution: v.weight * v.directionScore * (v.rawConfidence / 100),
    }));

    // 3. 计算综合方向
    const weightedSum = votes.reduce((sum, v) => sum + v.weightedContribution, 0);
    const totalWeight = votes.reduce((sum, v) => sum + v.weight * (v.rawConfidence / 100), 0);

    let direction: SignalDirection;
    if (weightedSum > 0.3) {
      direction = 'long';
    } else if (weightedSum < -0.3) {
      direction = 'short';
    } else {
      direction = 'neutral';
    }

    // 4. 计算综合置信度
    const confidences = activeSignals.map(s => s.confidence);
    const avgConfidence = confidences.reduce((a, b) => a + b, 0) / confidences.length;
    const variance = confidences.reduce((sum, c) => sum + Math.pow(c - avgConfidence, 2), 0) / confidences.length;
    const stdDev = Math.sqrt(variance);

    const overallConfidence = Math.round(avgConfidence * (1 - stdDev / 150));

    // 5. 计算一致性等级
    const agreementLevel = this.calculateAgreementLevel(activeSignals, stdDev, avgConfidence);

    // 6. 检测冲突
    const conflicts = this.detectConflicts(activeSignals, direction, weightedSum);

    return {
      direction,
      overallConfidence: Math.max(0, overallConfidence),
      agreementLevel,
      votes,
      conflicts,
    };
  }

  /**
   * 获取链权重
   */
  private getChainWeight(chain: SkillChain): number {
    switch (chain) {
      case 'S':
        return this.config.weights.s_chain;
      case 'C':
        return this.config.weights.c_chain;
      case 'F':
        return this.config.weights.f_chain;
    }
  }

  /**
   * 获取方向分数
   */
  private getDirectionScore(direction: SignalDirection): number {
    return this.config.directionMapping[direction];
  }

  /**
   * 计算一致性等级
   */
  private calculateAgreementLevel(
    signals: ChainSignal[],
    stdDev: number,
    avgConfidence: number
  ): AgreementLevel {
    // 检查方向一致性
    const directions = signals.map(s => s.direction);
    const uniqueDirections = new Set(directions);

    if (uniqueDirections.size > 2) {
      return 'conflict'; // 多方向冲突
    }

    if (uniqueDirections.size === 2) {
      // 两方向冲突
      if (avgConfidence > 75 && stdDev < 15) {
        return 'moderate'; // 虽然有分歧但置信度较高
      }
      return 'weak';
    }

    // 方向一致，检查置信度方差
    if (stdDev < 10 && avgConfidence > 75) {
      return 'strong';
    }

    if (stdDev < 20 && avgConfidence > 60) {
      return 'moderate';
    }

    if (stdDev < 30) {
      return 'weak';
    }

    return 'conflict';
  }

  /**
   * 检测冲突
   */
  private detectConflicts(
    signals: ChainSignal[],
    consensusDirection: SignalDirection,
    weightedSum: number
  ): Conflict[] {
    const conflicts: Conflict[] = [];

    // 1. 方向冲突检测
    const directionGroups = new Map<SignalDirection, SkillChain[]>();
    signals.forEach(s => {
      const group = directionGroups.get(s.direction) || [];
      group.push(s.chain);
      directionGroups.set(s.direction, group);
    });

    if (directionGroups.size > 1) {
      const groups = Array.from(directionGroups.entries());
      groups.forEach(([dir, chains]) => {
        if (dir !== consensusDirection && dir !== 'wait') {
          conflicts.push({
            id: `direction-conflict-${chains.join('-')}`,
            type: 'direction_conflict',
            involvedChains: chains,
            description: `${chains.join(', ')} 链支持 ${dir}，与其他链冲突`,
            resolution: `加权投票结果为 ${consensusDirection}，已按权重计算`,
          });
        }
      });
    }

    // 2. 置信度差距检测
    const confidences = signals.map(s => s.confidence);
    const maxConfidence = Math.max(...confidences);
    const minConfidence = Math.min(...confidences);
    const gap = maxConfidence - minConfidence;

    if (gap > 40) {
      const highConfChain = signals.find(s => s.confidence === maxConfidence);
      const lowConfChain = signals.find(s => s.confidence === minConfidence);

      if (highConfChain && lowConfChain) {
        conflicts.push({
          id: 'confidence-gap',
          type: 'confidence_gap',
          involvedChains: [highConfChain.chain, lowConfChain.chain],
          description: `${highConfChain.chain} 链置信度 ${maxConfidence}% 与 ${lowConfChain.chain} 链置信度 ${minConfidence}% 差距过大`,
          resolution: '已考虑置信度差距，使用加权平均计算',
        });
      }
    }

    return conflicts;
  }

  /**
   * 解决冲突
   */
  resolve(
    votingResult: VotingResult,
    fallback: 'majority_vote' | 'highest_confidence' | 'weighted_average' | 'manual_override'
  ): SignalDirection {
    switch (fallback) {
      case 'majority_vote':
        // 简单多数
        return this.majorityVote(votingResult);

      case 'highest_confidence':
        // 最高置信度
        return this.highestConfidence(votingResult);

      case 'weighted_average':
        // 加权平均（默认）
        return votingResult.direction;

      case 'manual_override':
        // 需要人工确认
        return 'neutral';
    }
  }

  /**
   * 简单多数投票
   */
  private majorityVote(votingResult: VotingResult): SignalDirection {
    const directionCounts = new Map<SignalDirection, number>();

    votingResult.votes.forEach(v => {
      const dir = this.scoreToDirection(v.directionScore);
      const count = directionCounts.get(dir) || 0;
      directionCounts.set(dir, count + 1);
    });

    let maxCount = 0;
    let winner: SignalDirection = 'neutral';

    directionCounts.forEach((count, dir) => {
      if (count > maxCount) {
        maxCount = count;
        winner = dir;
      }
    });

    return winner;
  }

  /**
   * 最高置信度
   */
  private highestConfidence(votingResult: VotingResult): SignalDirection {
    let maxConfidence = 0;
    let winner: SignalDirection = 'neutral';

    votingResult.votes.forEach(v => {
      if (v.rawConfidence > maxConfidence) {
        maxConfidence = v.rawConfidence;
        winner = this.scoreToDirection(v.directionScore);
      }
    });

    return winner;
  }

  /**
   * 分数转方向
   */
  private scoreToDirection(score: number): SignalDirection {
    if (score > 0.3) return 'long';
    if (score < -0.3) return 'short';
    return 'neutral';
  }
}

// ============================================================
// 单例
// ============================================================

let globalCalculator: VotingCalculator | null = null;

/**
 * 获取全局投票计算器
 */
export function getVotingCalculator(): VotingCalculator {
  if (!globalCalculator) {
    globalCalculator = new VotingCalculator();
  }
  return globalCalculator;
}
