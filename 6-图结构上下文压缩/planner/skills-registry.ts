/**
 * 技能注册表 - 所有可用技能的中心索引
 *
 * 位置: 6-图结构上下文压缩/planner/skills-registry.ts
 *
 * 功能:
 * - 注册技能
 * - 查询技能
 * - 推荐技能
 * - 获取技能状态
 *
 * 核心理念: 所有技能都有统一的契约，可以被动态调度
 */

import {
  SkillCapability,
  SkillMetadata,
  SkillRecommendation,
  SkillQueryParams,
  SkillChain,
  ThinkStage,
  ExecutionContext,
  SkillStatus,
  SkillResult,
  createFallbackResult,
} from './skill-types';

// ============================================================
// 技能注册表
// ============================================================

/**
 * 技能注册表
 * 统一管理所有可用的技能
 */
export class SkillsRegistry {
  /** 技能存储 */
  private skills: Map<string, SkillCapability> = new Map();

  /** 索引加速 */
  private byChain: Map<SkillChain, Set<string>> = new Map();
  private byCategory: Map<string, Set<string>> = new Map();
  private byStage: Map<ThinkStage, Set<string>> = new Map();
  private byTag: Map<string, Set<string>> = new Map();

  constructor() {
    // 初始化索引
    this.initIndexes();
  }

  private initIndexes(): void {
    // 按链索引
    (['S', 'C', 'F'] as SkillChain[]).forEach(chain => {
      this.byChain.set(chain, new Set());
    });
  }

  // ============================================================
  // 注册与获取
  // ============================================================

  /**
   * 注册技能
   */
  register(skill: SkillCapability): void {
    const { id } = skill.metadata;

    // 检查是否已存在
    if (this.skills.has(id)) {
      console.warn(`[SkillsRegistry] Skill ${id} already registered, overwriting`);
    }

    // 存储技能
    this.skills.set(id, skill);

    // 更新索引
    this.updateIndexes(skill);
  }

  /**
   * 批量注册技能
   */
  registerMany(skills: SkillCapability[]): void {
    skills.forEach(skill => this.register(skill));
  }

  /**
   * 获取技能
   */
  get(skillId: string): SkillCapability | undefined {
    return this.skills.get(skillId);
  }

  /**
   * 获取所有技能
   */
  getAll(): SkillCapability[] {
    return Array.from(this.skills.values());
  }

  /**
   * 检查技能是否存在
   */
  has(skillId: string): boolean {
    return this.skills.has(skillId);
  }

  // ============================================================
  // 查询
  // ============================================================

  /**
   * 条件查询技能
   */
  query(params: SkillQueryParams): SkillCapability[] {
    let results = Array.from(this.skills.values());

    // 按链过滤
    if (params.chain) {
      const chains = Array.isArray(params.chain) ? params.chain : [params.chain];
      results = results.filter(s => chains.includes(s.metadata.chain));
    }

    // 按分类过滤
    if (params.category) {
      const categories = Array.isArray(params.category) ? params.category : [params.category];
      results = results.filter(s => categories.includes(s.metadata.category));
    }

    // 按阶段过滤
    if (params.stage) {
      const stages = Array.isArray(params.stage) ? params.stage : [params.stage];
      results = results.filter(s =>
        s.metadata.applicableStages.some(st => stages.includes(st))
      );
    }

    // 按意图过滤
    if (params.intent) {
      const intents = Array.isArray(params.intent) ? params.intent : [params.intent];
      results = results.filter(s =>
        s.metadata.applicableIntents.some(i => intents.includes(i))
      );
    }

    // 按标签过滤
    if (params.tag) {
      const tags = Array.isArray(params.tag) ? params.tag : [params.tag];
      results = results.filter(s =>
        tags.some(t => s.metadata.tags.includes(t))
      );
    }

    // 按历史准确率过滤
    if (params.minAccuracy !== undefined) {
      results = results.filter(s =>
        (s.metadata.historicalAccuracy || 0) >= params.minAccuracy!
      );
    }

    // 按 token 消耗过滤
    if (params.maxTokens !== undefined) {
      results = results.filter(s =>
        s.metadata.estimatedTokens <= params.maxTokens!
      );
    }

    return results;
  }

  /**
   * 根据技能 ID 列表获取
   */
  getByIds(skillIds: string[]): SkillCapability[] {
    return skillIds
      .map(id => this.skills.get(id))
      .filter((s): s is SkillCapability => s !== undefined);
  }

  // ============================================================
  // 推荐
  // ============================================================

  /**
   * 基于上下文推荐技能
   *
   * 推荐逻辑:
   * 1. 匹配适用的思维阶段
   * 2. 匹配适用意图
   * 3. 考虑市场条件适配度
   * 4. 考虑历史调用成功率
   * 5. 考虑成本预算
   */
  recommend(context: ExecutionContext): SkillRecommendation[] {
    // 1. 确定适用的阶段
    const stage = this.getStageForIntent(context.intent);

    // 2. 查询候选技能
    let candidates = this.query({
      stage,
      intent: context.intent,
    });

    if (candidates.length === 0) {
      // 放宽条件，查询所有适用阶段的技能
      candidates = this.query({ stage });
    }

    // 3. 成本过滤
    if (context.budgetTokens) {
      candidates = candidates.filter(s =>
        s.metadata.estimatedTokens <= context.budgetTokens!
      );
    }

    // 4. 评分排序
    return candidates
      .map(skill => ({
        skill,
        score: this.calculateRecommendationScore(skill, context),
        reason: this.getRecommendationReason(skill, context),
      }))
      .filter(r => r.score > 0)
      .sort((a, b) => b.score - a.score);
  }

  /**
   * 推荐填补缺口的技能
   */
  recommendGapFilling(
    gapType: string,
    context: ExecutionContext
  ): SkillRecommendation[] {
    // 根据缺口类型推荐技能
    const tagMap: Record<string, string[]> = {
      'missing-data': ['research', 'intelligence'],
      'missing-skill': ['execution', 'research'],
      'logical-conflict': ['governance', 'intelligence'],
      'insufficient-evidence': ['research', 'intelligence'],
    };

    const categories = tagMap[gapType] || [];

    let candidates = this.query({
      category: categories as any,
      stage: context.priorOutputs ? undefined : 'analysis',
    });

    // 成本过滤
    if (context.budgetTokens) {
      candidates = candidates.filter(s =>
        s.metadata.estimatedTokens <= context.budgetTokens! * 0.3 // 缺口填补消耗较少
      );
    }

    return candidates
      .map(skill => ({
        skill,
        score: this.calculateRecommendationScore(skill, context) * 0.8, // 降权
        reason: `填补 ${gapType} 类型的缺口`,
      }))
      .filter(r => r.score > 0)
      .sort((a, b) => b.score - a.score);
  }

  // ============================================================
  // 执行
  // ============================================================

  /**
   * 调用技能
   */
  async invoke(
    skillId: string,
    inputs: Record<string, unknown>,
    context: ExecutionContext
  ): Promise<SkillResult> {
    const skill = this.skills.get(skillId);

    if (!skill) {
      return createFallbackResult(skillId, `技能 ${skillId} 不存在`);
    }

    // 验证输入
    if (skill.validate) {
      const validation = skill.validate(inputs);
      if (!validation.valid) {
        return createFallbackResult(
          skillId,
          `输入验证失败: ${validation.errors?.join(', ')}`
        );
      }
    }

    // 执行技能
    try {
      const startTime = Date.now();
      const result = await skill.execute(inputs, context);
      const endTime = Date.now();

      return {
        ...result,
        latencyMs: endTime - startTime,
      };
    } catch (error) {
      // 尝试降级
      if (skill.getFallback) {
        try {
          return await skill.getFallback(inputs);
        } catch {
          return createFallbackResult(
            skillId,
            `技能执行失败: ${error instanceof Error ? error.message : 'Unknown error'}`
          );
        }
      }

      return createFallbackResult(
        skillId,
        `技能执行失败: ${error instanceof Error ? error.message : 'Unknown error'}`
      );
    }
  }

  /**
   * 批量调用技能
   */
  async invokeMany(
    skillCalls: Array<{ skillId: string; inputs: Record<string, unknown> }>,
    context: ExecutionContext
  ): Promise<SkillResult[]> {
    return Promise.all(
      skillCalls.map(call => this.invoke(call.skillId, call.inputs, context))
    );
  }

  // ============================================================
  // 状态
  // ============================================================

  /**
   * 获取技能状态
   */
  async getStatus(skillId: string): Promise<SkillStatus> {
    const skill = this.skills.get(skillId);

    if (!skill) {
      return {
        healthy: false,
        message: `技能 ${skillId} 不存在`,
      };
    }

    if (skill.getStatus) {
      return skill.getStatus();
    }

    return {
      healthy: true,
      message: '技能正常',
    };
  }

  /**
   * 获取所有技能元信息
   */
  getManifest(): SkillMetadata[] {
    return Array.from(this.skills.values()).map(s => s.metadata);
  }

  // ============================================================
  // 私有方法
  // ============================================================

  private updateIndexes(skill: SkillCapability): void {
    const { metadata } = skill;

    // 按链索引
    const chainSet = this.byChain.get(metadata.chain);
    if (chainSet) chainSet.add(metadata.id);

    // 按分类索引
    if (!this.byCategory.has(metadata.category)) {
      this.byCategory.set(metadata.category, new Set());
    }
    this.byCategory.get(metadata.category)!.add(metadata.id);

    // 按阶段索引
    metadata.applicableStages.forEach(stage => {
      if (!this.byStage.has(stage)) {
        this.byStage.set(stage, new Set());
      }
      this.byStage.get(stage)!.add(metadata.id);
    });

    // 按标签索引
    metadata.tags.forEach(tag => {
      if (!this.byTag.has(tag)) {
        this.byTag.set(tag, new Set());
      }
      this.byTag.get(tag)!.add(metadata.id);
    });
  }

  private calculateRecommendationScore(
    skill: SkillCapability,
    context: ExecutionContext
  ): number {
    let score = 0;
    const { metadata } = skill;

    // 1. 历史准确率权重 (30%)
    if (metadata.historicalAccuracy) {
      score += (metadata.historicalAccuracy / 100) * 30;
    } else {
      score += 15; // 默认给 50% 的历史准确率分
    }

    // 2. 成本效率权重 (20%)
    if (context.budgetTokens) {
      const costEfficiency = Math.max(
        0,
        1 - metadata.estimatedTokens / context.budgetTokens
      );
      score += costEfficiency * 20;
    } else {
      score += 10;
    }

    // 3. 链权重匹配 (30%)
    const chainWeightKey = `${metadata.chain.toLowerCase()}_chain` as keyof typeof context.chainWeights;
    const chainWeight = context.chainWeights?.[chainWeightKey] || 0.33;
    score += chainWeight * 30;

    // 4. 市场条件匹配 (20%)
    if (
      metadata.marketConditions &&
      metadata.marketConditions.length > 0 &&
      context.marketCondition
    ) {
      if (metadata.marketConditions.includes(context.marketCondition)) {
        score += 20;
      } else {
        score += 5; // 不匹配但不是完全不适用
      }
    } else {
      score += 10; // 没有市场条件偏好
    }

    return Math.min(100, score);
  }

  private getRecommendationReason(
    skill: SkillCapability,
    context: ExecutionContext
  ): string {
    const reasons: string[] = [];

    if (skill.metadata.historicalAccuracy && skill.metadata.historicalAccuracy > 70) {
      reasons.push(`历史准确率 ${skill.metadata.historicalAccuracy}%`);
    }

    if (skill.metadata.estimatedTokens < 500) {
      reasons.push('低资源消耗');
    }

    if (context.chainWeights) {
      const chainWeightKey = `${skill.metadata.chain.toLowerCase()}_chain`;
      const weight = context.chainWeights[chainWeightKey as keyof typeof context.chainWeights];
      if (weight > 0.4) {
        reasons.push(`链权重 ${Math.round(weight * 100)}%`);
      }
    }

    return reasons.length > 0 ? reasons.join(', ') : '推荐使用';
  }

  private getStageForIntent(intent: string): ThinkStage {
    const intentToStage: Record<string, ThinkStage> = {
      market_query: 'research',
      deep_analysis: 'analysis',
      scenario_sim: 'analysis',
      strategy_verify: 'validate',
      execute_trade: 'execute',
      risk_alert: 'analysis',
      simple_qa: 'research',
    };

    return intentToStage[intent] || 'analysis';
  }
}

// ============================================================
// 单例
// ============================================================

let globalRegistry: SkillsRegistry | null = null;

/**
 * 获取全局技能注册表
 */
export function getSkillsRegistry(): SkillsRegistry {
  if (!globalRegistry) {
    globalRegistry = new SkillsRegistry();
  }
  return globalRegistry;
}

/**
 * 创建新的技能注册表
 */
export function createSkillsRegistry(): SkillsRegistry {
  return new SkillsRegistry();
}
