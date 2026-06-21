/**
 * 技能选择器
 *
 * 位置: 6-图结构上下文压缩/planner/skill-selector.ts
 *
 * 功能:
 * - 基于上下文动态选择最适合的技能
 * - 考虑并行能力
 * - 考虑成本约束
 *
 * 核心理念: AI 在每个思维步骤内，动态决定调用哪些技能
 */

import {
  SkillCapability,
  SkillRecommendation,
  ExecutionContext,
  SkillChain,
} from './skill-types';
import {
  ThinkingStepDefinition,
  PlannedSkillCall,
} from './planner-types';
import { SkillsRegistry } from './skills-registry';

// ============================================================
// 技能选择器
// ============================================================

/**
 * 技能选择器
 */
export class SkillSelector {
  private registry: SkillsRegistry;

  constructor(registry: SkillsRegistry) {
    this.registry = registry;
  }

  /**
   * 为步骤选择技能
   *
   * @param stepDef 步骤定义
   * @param context 执行上下文
   * @param priorResults 前序技能的产出（用于避免重复调用）
   * @returns 选中的技能列表（带优先级和调用模式）
   */
  select(
    stepDef: ThinkingStepDefinition,
    context: ExecutionContext,
    priorResults?: Map<string, SkillCapability>
  ): PlannedSkillCall[] {
    // 1. 获取推荐技能
    const recommendations = this.registry.recommend(context);

    // 2. 过滤
    const filtered = this.filterRecommendations(
      recommendations,
      stepDef,
      context,
      priorResults
    );

    // 3. 排序和分组
    const grouped = this.groupByParallelism(filtered, stepDef);

    return grouped;
  }

  /**
   * 选择填补缺口的技能
   */
  selectGapFilling(
    gapType: string,
    context: ExecutionContext,
    currentSkills: Set<string>
  ): PlannedSkillCall[] {
    const recommendations = this.registry.recommendGapFilling(gapType, context);

    // 过滤掉已调用的技能
    const filtered = recommendations
      .filter(r => !currentSkills.has(r.skill.metadata.id))
      .slice(0, 2); // 最多选择2个

    return filtered.map((r, index) => ({
      skillId: r.skill.metadata.id,
      priority: index + 1,
      invocationMode: 'parallel',
      estimatedTokens: r.skill.metadata.estimatedTokens,
      estimatedLatencyMs: r.skill.metadata.estimatedLatencyMs,
    }));
  }

  // ============================================================
  // 私有方法
  // ============================================================

  /**
   * 过滤推荐结果
   */
  private filterRecommendations(
    recommendations: SkillRecommendation[],
    stepDef: ThinkingStepDefinition,
    context: ExecutionContext,
    priorResults?: Map<string, SkillCapability>
  ): SkillRecommendation[] {
    const result: SkillRecommendation[] = [];
    const usedCategories = new Set<string>();

    for (const rec of recommendations) {
      const skill = rec.skill;
      const { metadata } = skill;

      // 1. 检查是否已调用
      if (priorResults?.has(metadata.id)) {
        continue;
      }

      // 2. 检查是否在预算内
      if (context.budgetTokens && metadata.estimatedTokens > context.budgetTokens * 0.5) {
        continue;
      }

      // 3. 检查延迟
      if (context.maxLatencyMs && metadata.estimatedLatencyMs > context.maxLatencyMs) {
        continue;
      }

      // 4. 检查是否被禁止
      if (context.userPreferences && metadata.tags.some(t => t === 'banned')) {
        continue;
      }

      // 5. 优先选择推荐类别
      if (stepDef.recommendedSkillCategories?.includes(metadata.category)) {
        if (!usedCategories.has(metadata.category)) {
          result.push(rec);
          usedCategories.add(metadata.category);
        }
      }

      // 6. 如果还没有达到推荐数量，添加其他
      if (result.length < 3 && !usedCategories.has(metadata.category)) {
        result.push(rec);
        usedCategories.add(metadata.category);
      }

      // 7. 检查是否有必须调用的技能
      if (stepDef.requiredSkills?.includes(metadata.id)) {
        // 将必须调用的技能放在最前面
        const idx = result.findIndex(r => r.skill.metadata.id === metadata.id);
        if (idx > 0) {
          result.splice(idx, 1);
          result.unshift(rec);
        }
      }

      if (result.length >= 5) break; // 最多5个
    }

    return result;
  }

  /**
   * 按并行能力分组
   */
  private groupByParallelism(
    recommendations: SkillRecommendation[],
    stepDef: ThinkingStepDefinition
  ): PlannedSkillCall[] {
    const result: PlannedSkillCall[] = [];
    const parallelGroup: SkillRecommendation[] = [];
    const dependencies = new Map<string, string[]>();

    for (const rec of recommendations) {
      const skill = rec.skill;

      // 检查技能是否有依赖
      const skillDeps = this.getSkillDependencies(skill);
      if (skillDeps.length > 0) {
        // 有依赖，串行执行
        dependencies.set(skill.metadata.id, skillDeps);
        result.push({
          skillId: skill.metadata.id,
          priority: rec.score,
          invocationMode: 'sequential',
          dependsOn: skillDeps,
          estimatedTokens: skill.metadata.estimatedTokens,
          estimatedLatencyMs: skill.metadata.estimatedLatencyMs,
        });
      } else {
        // 无依赖，可以并行
        parallelGroup.push(rec);
      }
    }

    // 将可并行的技能添加到结果
    if (parallelGroup.length > 0) {
      // 按优先级排序
      parallelGroup.sort((a, b) => b.score - a.score);

      // 第一个并行（最高优先级）
      result.unshift({
        skillId: parallelGroup[0].skill.metadata.id,
        priority: parallelGroup[0].score,
        invocationMode: 'parallel',
        estimatedTokens: parallelGroup[0].skill.metadata.estimatedTokens,
        estimatedLatencyMs: parallelGroup[0].skill.metadata.estimatedLatencyMs,
      });

      // 其余并行
      for (let i = 1; i < parallelGroup.length; i++) {
        result.push({
          skillId: parallelGroup[i].skill.metadata.id,
          priority: parallelGroup[i].score,
          invocationMode: 'parallel',
          estimatedTokens: parallelGroup[i].skill.metadata.estimatedTokens,
          estimatedLatencyMs: parallelGroup[i].skill.metadata.estimatedLatencyMs,
        });
      }
    }

    return result;
  }

  /**
   * 获取技能的依赖
   */
  private getSkillDependencies(skill: SkillCapability): string[] {
    // 目前基于技能元信息推断依赖
    // 未来可以从技能定义中显式声明

    const dependencies: string[] = [];

    // 一些技能需要先执行基础技能
    const dependencyRules: Record<string, string[]> = {
      'dream-strategy-designer': ['dream-strategy-research'],
      'dream-backtest': ['dream-strategy-parser'],
      'dream-pretrade-gatekeeper': ['dream-signal-scoring-spec', 'dream-risk-position-sizing'],
      'dream-tactical-executor': ['dream-pretrade-gatekeeper'],
    };

    const deps = dependencyRules[skill.metadata.id];
    if (deps) {
      // 检查依赖的技能是否在注册表中
      for (const dep of deps) {
        if (this.registry.has(dep)) {
          dependencies.push(dep);
        }
      }
    }

    return dependencies;
  }

  /**
   * 优化技能组合（减少冗余）
   */
  optimizeSkillSet(
    selected: PlannedSkillCall[],
    context: ExecutionContext
  ): PlannedSkillCall[] {
    // 1. 成本检查
    const totalCost = selected.reduce((sum, s) => sum + s.estimatedTokens, 0);

    if (context.budgetTokens && totalCost > context.budgetTokens) {
      // 超出预算，移除低优先级技能
      const sorted = [...selected].sort((a, b) => a.priority - b.priority);
      const result: PlannedSkillCall[] = [];
      let cost = 0;

      for (const skill of sorted) {
        if (cost + skill.estimatedTokens <= context.budgetTokens!) {
          result.push(skill);
          cost += skill.estimatedTokens;
        } else {
          break;
        }
      }

      return result;
    }

    return selected;
  }
}
