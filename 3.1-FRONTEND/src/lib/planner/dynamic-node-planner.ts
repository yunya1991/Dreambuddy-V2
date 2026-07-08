/**
 * 动态节点规划器 - Dreambuddy OS 动态决策核心
 *
 * 位置: 6-图结构上下文压缩/planner/dynamic-node-planner.ts
 *
 * 核心理念:
 *   A 层不是固定 5 维度的流水线，而是由 OS 动态决策的图编排层
 *   根据意图、复杂度、置信度、资源预算动态选择节点
 *
 * 设计依据: WORKBUDDY_OS_MODULAR_ARCHITECTURE.md §6
 *   "从固定流水线到动态思维图"
 *   意图 → 初始节点集 → 执行 → 置信度评估 → 动态追加/跳过 → 最终结果
 */

import {
  ThinkingStepDefinition,
  ConfidenceThresholds,
} from './step-types.ts';
import {
  SkillChain,
  ThinkStage,
  ExecutionContext,
} from './skill-types.ts';
import {
  IntentType,
  ComplexityLevel,
} from './planner-types.ts';
import { SkillsRegistry } from './skills-registry';

// ============================================================
// 意图 → 初始节点配置映射
// ============================================================

/**
 * 意图对应的初始节点选择策略
 *
 * 设计原则（调研主流大模型后确立）：
 *   - 分析类（market_query / deep_analysis / risk_alert）：轻量编排，直接出结果
 *   - 策略类（scenario_sim / strategy_verify / execute_trade）：完整链路，5阶段思维链
 *   - 简单类（simple_qa / command / config）：最少节点，快速响应
 *
 * 核心区别：useFullPipeline
 *   true  → 使用完整的 research→analysis→design→validate→execute 5阶段链路
 *   false → 根据意图动态选择 1-3 个节点直接分析，不走完整流水线
 */
export interface IntentNodeStrategy {
  intent: IntentType;
  description: string;
  /** 目标置信度阈值（达到此值可提前终止） */
  targetConfidence: number;
  /** 最小节点数 */
  minNodes: number;
  /** 最大节点数（防止无限扩展） */
  maxNodes: number;
  /** 初始节点选择模式 */
  initialMode: 'core_only' | 'cross_chain' | 'full_spectrum';
  /** 优先的链 */
  primaryChains: SkillChain[];
  /** 优先的阶段（按优先级排序） */
  preferredStages: ThinkStage[];
  /** 必须包含的技能 ID（如果在注册表中存在） */
  requiredSkillIds?: string[];
  /** 是否使用完整5阶段思维链（仅策略开发/交易执行类为 true） */
  useFullPipeline: boolean;
}

const INTENT_STRATEGIES: Record<IntentType, IntentNodeStrategy> = {
  // ── 轻量分析类：直接出结果，不走完整流水线 ──
  simple_qa: {
    intent: 'simple_qa',
    description: '简单问答 - 直接回答',
    targetConfidence: 70,
    minNodes: 1,
    maxNodes: 2,
    initialMode: 'core_only',
    primaryChains: ['A'],
    preferredStages: ['analysis'],
    useFullPipeline: false,
  },
  market_query: {
    intent: 'market_query',
    description: '行情查询 - 快速获取数据',
    targetConfidence: 72,
    minNodes: 2,
    maxNodes: 4,
    initialMode: 'cross_chain',
    primaryChains: ['C', 'F', 'A'],
    preferredStages: ['research', 'analysis'],
    useFullPipeline: false,
  },
  deep_analysis: {
    intent: 'deep_analysis',
    description: '深度分析 - 多维度直接分析，结尾给深化选项',
    targetConfidence: 80,
    minNodes: 5,
    maxNodes: 7,
    initialMode: 'cross_chain',
    primaryChains: ['C', 'F', 'A'],
    preferredStages: ['research', 'analysis'],
    useFullPipeline: false,
  },
  risk_alert: {
    intent: 'risk_alert',
    description: '风险告警 - 快速评估',
    targetConfidence: 75,
    minNodes: 2,
    maxNodes: 4,
    initialMode: 'core_only',
    primaryChains: ['A', 'C'],
    preferredStages: ['analysis', 'validate'],
    useFullPipeline: false,
  },
  artifact_query: {
    intent: 'artifact_query',
    description: '知识查询',
    targetConfidence: 70,
    minNodes: 1,
    maxNodes: 3,
    initialMode: 'core_only',
    primaryChains: ['A'],
    preferredStages: ['research', 'analysis'],
    useFullPipeline: false,
  },

  // ── 策略开发类：使用完整5阶段思维链 ──
  scenario_sim: {
    intent: 'scenario_sim',
    description: '情景模拟 - 完整推演验证链路',
    targetConfidence: 82,
    minNodes: 3,
    maxNodes: 8,
    initialMode: 'cross_chain',
    primaryChains: ['A', 'C'],
    preferredStages: ['analysis', 'design', 'validate'],
    useFullPipeline: true,
  },
  strategy_verify: {
    intent: 'strategy_verify',
    description: '策略验证 - 完整回测检验链路',
    targetConfidence: 85,
    minNodes: 3,
    maxNodes: 8,
    initialMode: 'cross_chain',
    primaryChains: ['C', 'A'],
    preferredStages: ['validate', 'analysis', 'design'],
    useFullPipeline: true,
  },
  execute_trade: {
    intent: 'execute_trade',
    description: '执行交易 - 完整决策闭环',
    targetConfidence: 88,
    minNodes: 4,
    maxNodes: 10,
    initialMode: 'full_spectrum',
    primaryChains: ['A', 'C'],
    preferredStages: ['analysis', 'design', 'validate', 'execute'],
    requiredSkillIds: ['dream-pretrade-gatekeeper', 'dream-regime-detector'],
    useFullPipeline: true,
  },

  // ── 系统类：最少节点 ──
  system_config: {
    intent: 'system_config',
    description: '系统配置',
    targetConfidence: 60,
    minNodes: 1,
    maxNodes: 2,
    initialMode: 'core_only',
    primaryChains: ['A'],
    preferredStages: ['execute'],
    useFullPipeline: false,
  },
  credits_query: {
    intent: 'credits_query',
    description: '积分查询',
    targetConfidence: 60,
    minNodes: 1,
    maxNodes: 2,
    initialMode: 'core_only',
    primaryChains: ['A'],
    preferredStages: ['research'],
    useFullPipeline: false,
  },
  command: {
    intent: 'command',
    description: '命令执行',
    targetConfidence: 70,
    minNodes: 1,
    maxNodes: 3,
    initialMode: 'core_only',
    primaryChains: ['A'],
    preferredStages: ['execute'],
    useFullPipeline: false,
  },
};

// ============================================================
// 复杂度 → 节点数量映射
// ============================================================

const COMPLEXITY_NODE_COUNT: Record<ComplexityLevel, { min: number; max: number }> = {
  quick: { min: 1, max: 3 },
  standard: { min: 3, max: 6 },
  deep: { min: 5, max: 12 },
};

// ============================================================
// 动态节点规划器
// ============================================================

/**
 * 动态节点规划器
 *
 * 替代固定 5 阶段（S1-S5）的生成逻辑
 * 根据意图、复杂度、注册表动态选择初始节点集
 */
export class DynamicNodePlanner {
  private registry: SkillsRegistry;

  constructor(registry: SkillsRegistry) {
    this.registry = registry;
  }

  /**
   * 判断意图是否需要完整5阶段思维链
   * 仅策略开发/交易执行类返回 true
   */
  shouldUseFullPipeline(intent: IntentType): boolean {
    const strategy = INTENT_STRATEGIES[intent];
    return strategy?.useFullPipeline ?? false;
  }

  /**
   * 生成初始执行节点集
   *
   * 算法：
   * 1. 获取意图对应的策略配置
   * 2. 如果 useFullPipeline=true → 使用完整5阶段链路（策略类）
   * 3. 如果 useFullPipeline=false → 轻量编排，从注册表动态选择1-3个节点（分析类）
   * 4. 按优先级排序（历史准确率 + 置信度范围 + 成本效率）
   * 5. 确保包含必须技能
   */
  generateInitialNodes(
    intent: IntentType,
    complexity: ComplexityLevel,
    context?: Partial<ExecutionContext>
  ): ThinkingStepDefinition[] {
    const strategy = INTENT_STRATEGIES[intent] || INTENT_STRATEGIES.deep_analysis;
    const complexityLimits = COMPLEXITY_NODE_COUNT[complexity];

    const maxNodes = Math.min(strategy.maxNodes, complexityLimits.max);
    const minNodes = Math.max(strategy.minNodes, complexityLimits.min);

    const allSkills = this.registry.getAll();

    const candidates = allSkills.filter(skill => {
      const meta = skill.metadata;

      if (strategy.primaryChains.length > 0) {
        if (!strategy.primaryChains.includes(meta.chain)) {
          return false;
        }
      }

      if (strategy.preferredStages.length > 0) {
        const hasMatchingStage = meta.applicableStages.some(stage =>
          strategy.preferredStages.includes(stage)
        );
        if (!hasMatchingStage) {
          return false;
        }
      }

      if (meta.applicableIntents.length > 0) {
        const hasMatchingIntent = meta.applicableIntents.some(i =>
          i === intent || i === 'all' || i === '*'
        );
        if (!hasMatchingIntent) {
          return false;
        }
      }

      return true;
    });

    const scored = candidates.map(skill => ({
      skill,
      score: this.scoreSkill(skill, strategy, context),
    }));

    scored.sort((a, b) => b.score - a.score);

    const requiredSkills: typeof scored = [];
    const otherSkills: typeof scored = [];

    const requiredSet = new Set(strategy.requiredSkillIds || []);
    for (const item of scored) {
      if (requiredSet.has(item.skill.metadata.id)) {
        requiredSkills.push(item);
      } else {
        otherSkills.push(item);
      }
    }

    const selected: typeof scored = [...requiredSkills];
    let remainingSlots = maxNodes - requiredSkills.length;

    const usedChainCategories = new Set<string>();
    for (const item of requiredSkills) {
      const meta = item.skill.metadata;
      usedChainCategories.add(meta.chain + ':' + meta.category);
    }

    if (strategy.primaryChains.length > 1) {
      const skillsByChain: Record<string, typeof scored> = {};
      for (const chain of strategy.primaryChains) {
        skillsByChain[chain] = [];
      }
      for (const item of otherSkills) {
        const chain = item.skill.metadata.chain;
        if (skillsByChain[chain]) {
          skillsByChain[chain].push(item);
        }
      }

      const totalChains = strategy.primaryChains.length;
      const basePerChain = Math.floor(remainingSlots / totalChains);
      let extraSlots = remainingSlots % totalChains;

      const chainQuotas: Record<string, number> = {};
      for (let i = 0; i < strategy.primaryChains.length; i++) {
        const chain = strategy.primaryChains[i];
        const available = skillsByChain[chain]?.length || 0;
        const extra = i < extraSlots ? 1 : 0;
        chainQuotas[chain] = Math.min(available, Math.max(1, basePerChain + extra));
      }

      const totalQuota = Object.values(chainQuotas).reduce((a, b) => a + b, 0);
      if (totalQuota < remainingSlots) {
        const diff = remainingSlots - totalQuota;
        for (let i = 0; i < strategy.primaryChains.length && diff > 0; i++) {
          const chain = strategy.primaryChains[i];
          const available = (skillsByChain[chain]?.length || 0) - chainQuotas[chain];
          if (available > 0) {
            const add = Math.min(available, diff);
            chainQuotas[chain] += add;
            diff -= add;
          }
        }
      }

      for (const chain of strategy.primaryChains) {
        const quota = chainQuotas[chain] || 0;
        if (quota <= 0) continue;
        const chainSkills = skillsByChain[chain] || [];
        let added = 0;
        for (const item of chainSkills) {
          if (added >= quota) break;
          const meta = item.skill.metadata;
          const key = meta.chain + ':' + meta.category;
          if (usedChainCategories.has(key)) continue;
          selected.push(item);
          usedChainCategories.add(key);
          added++;
          remainingSlots--;
        }
      }
    } else {
      for (const item of otherSkills) {
        if (remainingSlots <= 0) break;
        const meta = item.skill.metadata;
        const key = meta.chain + ':' + meta.category;
        if (usedChainCategories.has(key)) continue;
        selected.push(item);
        usedChainCategories.add(key);
        remainingSlots--;
      }
    }

    if (selected.length < minNodes) {
      const fallbackSkills = allSkills
        .filter(s => !selected.some(sel => sel.skill.metadata.id === s.metadata.id))
        .slice(0, minNodes - selected.length)
        .map(s => ({ skill: s, score: 0 }));
      selected.push(...fallbackSkills);
    }

    const stageForSkill = (skill: typeof allSkills[0]): ThinkStage => {
      const stages = skill.metadata.applicableStages;
      for (const preferred of strategy.preferredStages) {
        if (stages.includes(preferred)) {
          return preferred;
        }
      }
      return stages[0] || 'analysis';
    };

    const usedSkillIds = new Set<string>();
    for (const item of selected) {
      usedSkillIds.add(item.skill.metadata.id);
    }

    // ── 思维链阶段定义 ──────────────────────────────
    // Phase 1: 数据采集（C/F链客观数据）
    // Phase 2: 矛盾识别（A链基于数据分析矛盾）
    // Phase 3: 假设验证（A链验证矛盾判断）
    // Phase 4: 策略形成（A链输出操作建议）
    type ThinkingPhase = 'data_collection' | 'contradiction_identification' | 'hypothesis_validation' | 'strategy_formation';

    const phaseForSkill = (meta: typeof allSkills[0]['metadata']): ThinkingPhase => {
      if (meta.chain === 'C' || meta.chain === 'F') return 'data_collection';
      if (meta.category === 'philosophical_analysis' || meta.category === 'intelligence') return 'contradiction_identification';
      if (meta.category === 'first_principles' || meta.category === 'market_regime' || meta.category === 'screening') return 'hypothesis_validation';
      return 'strategy_formation';
    };

    const phaseOrder: Record<ThinkingPhase, number> = {
      data_collection: 0,
      contradiction_identification: 1,
      hypothesis_validation: 2,
      strategy_formation: 3,
    };

    const phaseQuestions: Record<ThinkingPhase, string> = {
      data_collection: '采集客观数据：技术指标、基本面数据、资金流向',
      contradiction_identification: '基于采集的数据，识别当前市场的主要矛盾和多空分歧',
      hypothesis_validation: '验证矛盾判断：通过第一性原理和市场状态识别确认假设',
      strategy_formation: '形成操作建议：基于验证后的结论，制定具体策略',
    };

    // 按思维链阶段排序
    const phaseSorted = [...selected].sort((a, b) => {
      const phaseA = phaseForSkill(a.skill.metadata);
      const phaseB = phaseForSkill(b.skill.metadata);
      return phaseOrder[phaseA] - phaseOrder[phaseB];
    });

    const stepDefs: ThinkingStepDefinition[] = phaseSorted.map((item, index) => {
      const skill = item.skill;
      const meta = skill.metadata;
      const stage = stageForSkill(skill);
      const phase = phaseForSkill(meta);

      const stepSkillIds: string[] = [meta.id];
      const stepCategories: string[] = [meta.category];

      // 辅助技能：同阶段、不同类别
      const auxiliarySkills = allSkills.filter(s => {
        const sMeta = s.metadata;
        if (usedSkillIds.has(sMeta.id)) return false;
        if (phaseForSkill(sMeta) !== phase) return false;
        if (!sMeta.applicableStages.includes(stage)) return false;
        if (stepCategories.includes(sMeta.category)) return false;
        if (meta.applicableIntents.length > 0) {
          const hasMatchingIntent = sMeta.applicableIntents.some((i: string) =>
            i === intent || i === 'all' || i === '*'
          );
          if (!hasMatchingIntent) return false;
        }
        return true;
      });

      auxiliarySkills.sort((a, b) => {
        const scoreA = this.scoreSkill(a, strategy, context);
        const scoreB = this.scoreSkill(b, strategy, context);
        return scoreB - scoreA;
      });

      const maxAuxPerStep = phase === 'contradiction_identification' || phase === 'hypothesis_validation' ? 2 : 1;
      for (let i = 0; i < Math.min(maxAuxPerStep, auxiliarySkills.length); i++) {
        const aux = auxiliarySkills[i];
        stepSkillIds.push(aux.metadata.id);
        stepCategories.push(aux.metadata.category);
        usedSkillIds.add(aux.metadata.id);
      }

      const skillConfidenceMid = (meta.confidenceRange[0] + meta.confidenceRange[1]) / 2;
      const confidenceHigh = Math.min(80, Math.round(skillConfidenceMid * 0.9));
      const confidenceMedium = Math.round(skillConfidenceMid * 0.7);
      const confidenceLow = Math.round(skillConfidenceMid * 0.5);

      return {
        id: meta.id,
        stage,
        chain: meta.chain,
        label: meta.name,
        icon: this.determineIcon(meta, stage),
        description: meta.description,
        coreQuestion: `[${phase}] ${phaseQuestions[phase]}`,
        expectedOutputs: ['分析结论', '置信度评分'],
        confidenceThresholds: {
          high: confidenceHigh,
          medium: confidenceMedium,
          low: confidenceLow,
        },
        recommendedSkillCategories: stepCategories,
        requiredSkills: stepSkillIds,
        dependsOn: index === 0 ? undefined : [phaseSorted[index - 1].skill.metadata.id],
        allowIteration: true,
        maxIterations: 1,
        isCrossValidationPoint: index > 0 && (index % 2 === 0 || index === phaseSorted.length - 1),
        crossValidationChains: strategy.primaryChains,
      } as ThinkingStepDefinition;
    });

    return stepDefs;
  }

  /**
   * 根据当前执行结果，决定是否需要追加节点
   *
   * @param completedNodes 已完成的节点结果
   * @param currentConfidence 当前综合置信度
   * @param targetConfidence 目标置信度
   * @param executedIds 已执行过的节点ID
   * @param intent 当前意图
   * @returns 需要追加的节点定义（空数组表示无需追加）
   */
  decideNextNodes(
    completedNodes: Array<{ stepId: string; confidence: number; decision: string }>,
    currentConfidence: number,
    targetConfidence: number,
    executedIds: Set<string>,
    intent: IntentType,
    maxTotalNodes: number = 6
  ): ThinkingStepDefinition[] {
    const confidenceGap = targetConfidence - currentConfidence;

    if (confidenceGap <= 0) {
      return [];
    }

    if (confidenceGap <= 5 && completedNodes.length >= 3) {
      return [];
    }

    if (completedNodes.length >= maxTotalNodes) {
      return [];
    }

    const strategy = INTENT_STRATEGIES[intent] || INTENT_STRATEGIES.deep_analysis;
    const allSkills = this.registry.getAll();

    const completedCategories = new Set<string>();
    for (const node of completedNodes) {
      const skill = allSkills.find(s => s.metadata.id === node.stepId);
      if (skill?.metadata?.category) {
        completedCategories.add(skill.metadata.category);
      }
    }

    const candidates = allSkills.filter(skill => {
      const meta = skill.metadata;

      if (executedIds.has(meta.id)) {
        return false;
      }

      if (completedCategories.has(meta.category)) {
        return false;
      }

      if (strategy.primaryChains.length > 0) {
        if (!strategy.primaryChains.includes(meta.chain)) {
          return false;
        }
      }

      if (strategy.preferredStages.length > 0) {
        const hasMatchingStage = meta.applicableStages.some(stage =>
          strategy.preferredStages.includes(stage)
        );
        if (!hasMatchingStage) {
          return false;
        }
      }

      if (meta.applicableIntents.length > 0) {
        const hasMatchingIntent = meta.applicableIntents.some((i: string) =>
          i === intent || i === 'all' || i === '*'
        );
        if (!hasMatchingIntent) {
          return false;
        }
      }

      return true;
    });

    const scored = candidates.map(skill => ({
      skill,
      score: this.scoreSkill(skill, strategy, undefined),
    }));

    scored.sort((a, b) => b.score - a.score);

    const remainingSlots = maxTotalNodes - completedNodes.length;

    const numToAdd = confidenceGap > 15
      ? Math.min(2, scored.length, remainingSlots)
      : confidenceGap > 8
      ? Math.min(2, scored.length, remainingSlots)
      : Math.min(1, scored.length, remainingSlots);

    const toAdd = scored.slice(0, numToAdd);

    return toAdd.map(item => {
      const meta = item.skill.metadata;
      const stage = meta.applicableStages[0] || 'analysis';
      const skillConfidenceMid = (meta.confidenceRange[0] + meta.confidenceRange[1]) / 2;
      const confidenceHigh = Math.min(80, Math.round(skillConfidenceMid * 0.9));
      const confidenceMedium = Math.round(skillConfidenceMid * 0.7);
      const confidenceLow = Math.round(skillConfidenceMid * 0.5);

      return {
        id: meta.id,
        stage,
        chain: meta.chain,
        label: meta.name,
        icon: this.determineIcon(meta, stage),
        description: meta.description,
        coreQuestion: `补充分析：${meta.description}`,
        expectedOutputs: ['补充分析结果', '置信度提升'],
        confidenceThresholds: {
          high: confidenceHigh,
          medium: confidenceMedium,
          low: confidenceLow,
        },
        recommendedSkillCategories: [meta.category],
        requiredSkills: [meta.id],
        allowIteration: true,
        maxIterations: 1,
        isCrossValidationPoint: false,
      } as ThinkingStepDefinition;
    });
  }

  /**
   * 获取意图的目标置信度
   */
  getTargetConfidence(intent: IntentType): number {
    return INTENT_STRATEGIES[intent]?.targetConfidence ?? 80;
  }

  /**
   * 获取意图的最大节点数
   */
  getMaxNodes(intent: IntentType, complexity?: ComplexityLevel): number {
    const strategy = INTENT_STRATEGIES[intent] || INTENT_STRATEGIES.deep_analysis;
    const strategyMax = strategy.maxNodes;
    if (!complexity) return strategyMax;
    const complexityLimits = COMPLEXITY_NODE_COUNT[complexity];
    return Math.min(strategyMax, complexityLimits.max);
  }

  /**
   * 判断是否可以提前终止
   */
  canEarlyTerminate(
    currentConfidence: number,
    completedCount: number,
    intent: IntentType,
    complexity: ComplexityLevel
  ): boolean {
    const strategy = INTENT_STRATEGIES[intent] || INTENT_STRATEGIES.deep_analysis;
    const limits = COMPLEXITY_NODE_COUNT[complexity];

    if (completedCount < Math.max(2, limits.min - 1)) {
      return false;
    }

    return currentConfidence >= strategy.targetConfidence;
  }

  // ============================================================
  // 私有方法
  // ============================================================

  private scoreSkill(
    skill: { metadata: any },
    strategy: IntentNodeStrategy,
    _context?: Partial<ExecutionContext>
  ): number {
    const meta = skill.metadata;
    let score = 0;

    const stageMatch = meta.applicableStages.filter((s: ThinkStage) =>
      strategy.preferredStages.includes(s)
    ).length;
    score += stageMatch * 20;

    const chainMatch = strategy.primaryChains.includes(meta.chain) ? 15 : 0;
    score += chainMatch;

    // C/F 链技能有真实 API 数据源，额外加分
    const dataBonus = meta.chain === 'C' ? 25 : meta.chain === 'F' ? 20 : 0;
    score += dataBonus;

    const midConfidence = (meta.confidenceRange[0] + meta.confidenceRange[1]) / 2;
    score += midConfidence * 0.3;

    const costPenalty = (meta.estimatedTokens || 1000) / 1000 * 2;
    score -= costPenalty;

    const latencyPenalty = (meta.estimatedLatencyMs || 30000) / 10000 * 1.5;
    score -= latencyPenalty;

    if (meta.historicalAccuracy) {
      score += meta.historicalAccuracy * 0.2;
    }

    return score;
  }

  private orderByStage(
    steps: ThinkingStepDefinition[],
    preferredOrder: ThinkStage[]
  ): ThinkingStepDefinition[] {
    const stageOrder: Record<string, number> = {};
    preferredOrder.forEach((stage, index) => {
      stageOrder[stage] = index;
    });

    return [...steps].sort((a, b) => {
      const orderA = stageOrder[a.stage] ?? 99;
      const orderB = stageOrder[b.stage] ?? 99;
      if (orderA !== orderB) return orderA - orderB;
      return a.id.localeCompare(b.id);
    });
  }

  private determineIcon(meta: any, stage: ThinkStage): string {
    const stageIcons: Record<ThinkStage, string> = {
      research: '🔍',
      analysis: '🧠',
      design: '📐',
      validate: '✅',
      execute: '⚡',
    };
    return stageIcons[stage] || '⚙️';
  }
}
