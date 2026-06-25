/**
 * ChainPlanner - 零Token链路规划器
 *
 * 位置: 6-图结构上下文压缩/planner/chain-planner.ts
 *
 * 四维规划（全部本地计算，零Token消耗）：
 *   1. Token预算过滤：剪掉超预算的高成本节点
 *   2. 知识库命中提升：有高分策略时升级为快速路径
 *   3. 历史表现过滤：当前Regime+标的组合的节点命中率
 *   4. 标的覆盖检查：小币/冷门标的标记可能无数据的节点
 *
 * 参考Python实现: experiments/ab-trading/core/chain_planner.py
 */

import {
  ThinkingStepDefinition,
  S_CHAIN_STEPS,
  C_CHAIN_STEPS,
  F_CHAIN_STEPS,
  getStepDefinition,
} from './step-types.ts';
import { SkillChain, IntentType } from './skill-types.ts';
import { ComplexityLevel, PlannerContext } from './planner-types.ts';

// ============================================================
// 节点成本表（Token估算，规划时用于预算校验）
// ============================================================

const NODE_COST_TABLE: Record<string, number> = {
  // 零成本节点（纯规则/本地计算）
  'C1': 0,
  'C2': 50,
  'F2': 0,
  'F3': 0,
  // 低成本节点
  'S1': 2000,
  'S2': 800,
  'S3': 1200,
  'S4': 800,
  'S5': 1000,
  'C3': 300,
  'C4': 800,
  'C5': 1500,
  'F1': 500,
  'F4': 400,
  'F5': 500,
};

// ============================================================
// 主流动性标的（有较好数据覆盖的 Tavily/链上数据）
// ============================================================

const LIQUID_SYMBOLS = new Set([
  'BTC', 'ETH', 'SOL', 'BNB', 'AVAX', 'LINK', 'MATIC',
  'XRP', 'ADA', 'DOGE', 'DOT', 'LTC', 'TRX', 'ATOM',
]);

// 资金费率敏感节点（小币可能无数据）
const FUNDING_SENSITIVE_NODES = new Set(['F2', 'F3']);

// 链上数据敏感节点（小币可能无数据）
const ONCHAIN_SENSITIVE_NODES = new Set(['F4']);

// ============================================================
// 类型定义
// ============================================================

export interface ChainPlanResult {
  plannedSteps: ThinkingStepDefinition[];
  prunedNodes: Array<{ stepId: string; reason: string }>;
  addedNodes: Array<{ stepId: string; reason: string }>;
  budgetMode: 'full' | 'standard' | 'lean';
  estimatedTokens: number;
  planRationale: string;
  knowledgeHit?: {
    id: string;
    name: string;
    score: number;
    summary: string;
  };
  shortcutTaken: boolean;
  primaryChain: SkillChain;
  dynamicInsertionsEnabled: boolean;
}

export interface KnowledgeHit {
  id: string;
  name: string;
  score: number;
  summary: string;
  category?: string;
}

export interface HistoricalPerformance {
  [stepId: string]: {
    hitRate: number;      // 0-1，历史命中率
    sampleSize: number;   // 样本数量
    avgConfidence: number; // 平均置信度
  };
}

// ============================================================
// ChainPlanner 主类
// ============================================================

export class ChainPlanner {
  private tokenBudget: number;
  private defaultBudget = 8000;

  constructor(tokenBudget?: number) {
    this.tokenBudget = tokenBudget || this.defaultBudget;
  }

  // ============================================================
  // 主入口：四维规划
  // ============================================================

  plan(
    intent: IntentType,
    complexity: ComplexityLevel,
    primaryChain: SkillChain,
    context: Partial<PlannerContext> = {}
  ): ChainPlanResult {
    const startTime = Date.now();
    const prunedNodes: ChainPlanResult['prunedNodes'] = [];
    const addedNodes: ChainPlanResult['addedNodes'] = [];

    // 1. 获取基础步骤列表
    let steps = this.getBaseSteps(primaryChain, complexity);

    // 2. 维度一：知识库命中检查（可能触发快捷路径）
    const knowledgeHit = this.checkKnowledgeHit(context);
    if (knowledgeHit && knowledgeHit.score >= 75) {
      const shortcutResult = this.tryShortcut(steps, knowledgeHit, primaryChain);
      if (shortcutResult.shortcutTaken) {
        steps = shortcutResult.steps;
        addedNodes.push({
          stepId: 'SHORTCUT',
          reason: `知识库命中「${knowledgeHit.name}」(评分${knowledgeHit.score})，启用快捷路径`,
        });
      }
    }

    // 3. 维度二：历史表现过滤（低命中率节点降级或标记）
    const historicalPerf = this.getHistoricalPerformance(context);
    if (historicalPerf) {
      const filtered = this.filterByHistory(steps, historicalPerf);
      steps = filtered.steps;
      prunedNodes.push(...filtered.pruned);
    }

    // 4. 维度三：标的覆盖检查（小币/冷门标的标记无数据节点）
    const symbol = context.symbol?.toUpperCase() || '';
    if (symbol && !LIQUID_SYMBOLS.has(symbol)) {
      const coverageResult = this.checkSymbolCoverage(steps, symbol);
      steps = coverageResult.steps;
      prunedNodes.push(...coverageResult.pruned);
    }

    // 5. 维度四：Token预算过滤（最后做，确保核心步骤优先）
    const budgetResult = this.filterByBudget(steps, this.tokenBudget);
    steps = budgetResult.steps;
    prunedNodes.push(...budgetResult.pruned);

    // 6. 计算预算模式
    const totalTokens = this.calculateTotalCost(steps);
    const budgetMode = this.determineBudgetMode(totalTokens, this.tokenBudget);

    // 7. 生成规划理由
    const planRationale = this.generateRationale(
      primaryChain,
      complexity,
      steps,
      prunedNodes,
      addedNodes,
      knowledgeHit,
      totalTokens,
      budgetMode,
      symbol
    );

    // 8. 判断是否启用动态插入
    const dynamicInsertionsEnabled = this.shouldEnableDynamicInsertions(
      complexity,
      intent,
      context
    );

    return {
      plannedSteps: steps,
      prunedNodes,
      addedNodes,
      budgetMode,
      estimatedTokens: totalTokens,
      planRationale,
      knowledgeHit,
      shortcutTaken: addedNodes.some(n => n.stepId === 'SHORTCUT'),
      primaryChain,
      dynamicInsertionsEnabled,
    };
  }

  // ============================================================
  // 基础步骤获取
  // ============================================================

  private getBaseSteps(
    primaryChain: SkillChain,
    complexity: ComplexityLevel
  ): ThinkingStepDefinition[] {
    let steps: ThinkingStepDefinition[];

    switch (primaryChain) {
      case 'A':
        steps = [...S_CHAIN_STEPS];
        break;
      case 'C':
        steps = [...C_CHAIN_STEPS];
        break;
      case 'F':
        steps = [...F_CHAIN_STEPS];
        break;
      default:
        steps = [...S_CHAIN_STEPS];
    }

    // 根据复杂度裁剪
    switch (complexity) {
      case 'quick':
        return steps.slice(0, 2);
      case 'standard':
        return steps.slice(0, 4);
      case 'deep':
        return steps;
      default:
        return steps.slice(0, 3);
    }
  }

  // ============================================================
  // 维度一：知识库命中检查
  // ============================================================

  private checkKnowledgeHit(
    context: Partial<PlannerContext>
  ): KnowledgeHit | undefined {
    const hits = context.priorHistory?.previousConclusions
      ?.map((c, i) => ({
        id: `hist_${i}`,
        name: `历史结论 #${i + 1}`,
        score: context.priorHistory?.previousConfidences?.[i] || 60,
        summary: c,
      }))
      .filter(h => h.score >= 70);

    if (hits && hits.length > 0) {
      return hits.sort((a, b) => b.score - a.score)[0];
    }

    return undefined;
  }

  private tryShortcut(
    steps: ThinkingStepDefinition[],
    knowledgeHit: KnowledgeHit,
    primaryChain: SkillChain
  ): { steps: ThinkingStepDefinition[]; shortcutTaken: boolean } {
    // 如果知识库命中的是策略类，且评分足够高，可跳过S1/S2直接进入S3
    if (primaryChain === 'A' && knowledgeHit.score >= 80 && steps.length > 3) {
      const shortcutSteps = steps.filter(s =>
        s.id === 'S3' || s.id === 'S4' || s.id === 'S5'
      );
      if (shortcutSteps.length >= 2) {
        return { steps: shortcutSteps, shortcutTaken: true };
      }
    }
    return { steps, shortcutTaken: false };
  }

  // ============================================================
  // 维度二：历史表现过滤
  // ============================================================

  private getHistoricalPerformance(
    context: Partial<PlannerContext>
  ): HistoricalPerformance | undefined {
    // 模拟历史表现数据（实际应从记忆系统读取）
    // 这里返回空，让上层通过 priorHistory 注入
    return undefined;
  }

  private filterByHistory(
    steps: ThinkingStepDefinition[],
    perf: HistoricalPerformance
  ): { steps: ThinkingStepDefinition[]; pruned: ChainPlanResult['prunedNodes'] } {
    const pruned: ChainPlanResult['prunedNodes'] = [];
    const filtered: ThinkingStepDefinition[] = [];

    for (const step of steps) {
      const stepPerf = perf[step.id];
      if (stepPerf && stepPerf.hitRate < 0.3 && stepPerf.sampleSize >= 5) {
        pruned.push({
          stepId: step.id,
          reason: `历史命中率${Math.round(stepPerf.hitRate * 100)}%（${stepPerf.sampleSize}样本），低于30%阈值`,
        });
      } else {
        filtered.push(step);
      }
    }

    return { steps: filtered, pruned };
  }

  // ============================================================
  // 维度三：标的覆盖检查
  // ============================================================

  private checkSymbolCoverage(
    steps: ThinkingStepDefinition[],
    symbol: string
  ): { steps: ThinkingStepDefinition[]; pruned: ChainPlanResult['prunedNodes'] } {
    const pruned: ChainPlanResult['prunedNodes'] = [];
    const filtered: ThinkingStepDefinition[] = [];

    for (const step of steps) {
      const stepId = step.id;
      let shouldPrune = false;
      let reason = '';

      if (FUNDING_SENSITIVE_NODES.has(stepId)) {
        shouldPrune = true;
        reason = `小币种${symbol}可能无资金费率数据`;
      } else if (ONCHAIN_SENSITIVE_NODES.has(stepId)) {
        shouldPrune = true;
        reason = `小币种${symbol}链上数据覆盖不足`;
      }

      if (shouldPrune) {
        pruned.push({ stepId, reason });
      } else {
        filtered.push(step);
      }
    }

    return { steps: filtered, pruned };
  }

  // ============================================================
  // 维度四：Token预算过滤
  // ============================================================

  private filterByBudget(
    steps: ThinkingStepDefinition[],
    budget: number
  ): { steps: ThinkingStepDefinition[]; pruned: ChainPlanResult['prunedNodes'] } {
    const pruned: ChainPlanResult['prunedNodes'] = [];
    const kept: ThinkingStepDefinition[] = [];
    let currentCost = 0;

    // 按优先级排序：越靠后的步骤优先级越低（核心步骤在前）
    const prioritized = [...steps];

    for (const step of prioritized) {
      const cost = NODE_COST_TABLE[step.id] ?? 1000;

      if (currentCost + cost <= budget) {
        kept.push(step);
        currentCost += cost;
      } else {
        // 如果是核心步骤（前3步），尝试保留，剪掉后面的非核心
        if (kept.length < 2) {
          kept.push(step);
          currentCost += cost;
        } else {
          pruned.push({
            stepId: step.id,
            reason: `预算不足（需${cost}Token，剩余${budget - currentCost}）`,
          });
        }
      }
    }

    return { steps: kept, pruned };
  }

  private calculateTotalCost(steps: ThinkingStepDefinition[]): number {
    return steps.reduce((sum, s) => sum + (NODE_COST_TABLE[s.id] ?? 1000), 0);
  }

  private determineBudgetMode(
    totalTokens: number,
    budget: number
  ): 'full' | 'standard' | 'lean' {
    const ratio = totalTokens / budget;
    if (ratio >= 0.8) return 'full';
    if (ratio >= 0.4) return 'standard';
    return 'lean';
  }

  // ============================================================
  // 动态插入判断
  // ============================================================

  private shouldEnableDynamicInsertions(
    complexity: ComplexityLevel,
    intent: IntentType,
    context: Partial<PlannerContext>
  ): boolean {
    // 深度分析和复杂场景启用动态插入
    if (complexity === 'deep') return true;
    if (intent === 'deep_analysis') return true;
    if (intent === 'scenario_sim') return true;
    if (intent === 'strategy_verify') return true;

    // hybrid模式下启用
    if (context.tradingMode === 'hybrid') return true;

    return false;
  }

  // ============================================================
  // 生成规划理由
  // ============================================================

  private generateRationale(
    primaryChain: SkillChain,
    complexity: ComplexityLevel,
    steps: ThinkingStepDefinition[],
    pruned: ChainPlanResult['prunedNodes'],
    added: ChainPlanResult['addedNodes'],
    knowledgeHit: KnowledgeHit | undefined,
    totalTokens: number,
    budgetMode: string,
    symbol?: string
  ): string {
    const lines: string[] = [];

    lines.push(`【ChainPlanner 规划报告】`);
    lines.push(`主链: ${primaryChain === 'A' ? 'S链(AI交易)' : primaryChain === 'C' ? 'C链(经典量化)' : 'F链(基本面)'}`);
    lines.push(`复杂度: ${complexity === 'quick' ? '快速' : complexity === 'standard' ? '标准' : '深度'}`);
    lines.push(`预算模式: ${budgetMode} (预计 ${totalTokens} Token)`);
    lines.push(`规划步骤数: ${steps.length}`);

    if (knowledgeHit) {
      lines.push(`知识库命中: ${knowledgeHit.name} (${knowledgeHit.score}分)`);
    }

    if (symbol) {
      const isLiquid = LIQUID_SYMBOLS.has(symbol.toUpperCase());
      lines.push(`标的覆盖: ${symbol} ${isLiquid ? '（主流币，数据完整）' : '（小币种，部分数据可能缺失）'}`);
    }

    if (pruned.length > 0) {
      lines.push('');
      lines.push('剪枝节点:');
      pruned.forEach(p => {
        lines.push(`  - ${p.stepId}: ${p.reason}`);
      });
    }

    if (added.length > 0) {
      lines.push('');
      lines.push('追加节点:');
      added.forEach(a => {
        lines.push(`  - ${a.stepId}: ${a.reason}`);
      });
    }

    lines.push('');
    lines.push('执行序列:');
    steps.forEach((s, i) => {
      lines.push(`  ${i + 1}. ${s.id} - ${s.label}`);
    });

    return lines.join('\n');
  }
}

// ============================================================
// 便捷函数
// ============================================================

export function planChain(
  intent: IntentType,
  complexity: ComplexityLevel,
  primaryChain: SkillChain,
  context?: Partial<PlannerContext>,
  tokenBudget?: number
): ChainPlanResult {
  const planner = new ChainPlanner(tokenBudget);
  return planner.plan(intent, complexity, primaryChain, context);
}

// ============================================================
// 动态插入规划（用于执行过程中动态追加其他链节点）
// ============================================================

export interface DynamicInsertionPlan {
  insertions: Array<{
    stepId: string;
    chain: SkillChain;
    insertAfter: string;  // 在哪个步骤之后插入
    reason: string;
    priority: 'high' | 'medium' | 'low';
    cost: number;
  }>;
  totalAdditionalCost: number;
  recommendation: 'insert' | 'skip';
  rationale: string;
}

export class DynamicInsertionPlanner {
  private chainPlanner: ChainPlanner;

  constructor(tokenBudget?: number) {
    this.chainPlanner = new ChainPlanner(tokenBudget);
  }

  /**
   * 规划动态插入：当主链某步骤置信度不足时，决定插入哪些其他链的步骤
   */
  planInsertions(
    lowConfidenceStepId: string,
    currentConfidence: number,
    primaryChain: SkillChain,
    gapType: string,
    remainingBudget: number,
    executedSteps: string[]
  ): DynamicInsertionPlan {
    const insertions: DynamicInsertionPlan['insertions'] = [];
    let totalCost = 0;

    // 根据缺口类型决定插入什么链的什么步骤
    const candidates = this.getInsertionCandidates(gapType, primaryChain);

    // 过滤掉已经执行过的步骤
    const availableCandidates = candidates.filter(
      c => !executedSteps.includes(c.stepId)
    );

    // 按预算排序插入
    for (const candidate of availableCandidates) {
      if (totalCost + candidate.cost <= remainingBudget) {
        insertions.push({
          ...candidate,
          insertAfter: lowConfidenceStepId,
        });
        totalCost += candidate.cost;
      }
    }

    // 生成建议
    const recommendation = insertions.length > 0 ? 'insert' : 'skip';
    const rationale = this.generateInsertionRationale(
      lowConfidenceStepId,
      currentConfidence,
      gapType,
      insertions,
      remainingBudget
    );

    return {
      insertions,
      totalAdditionalCost: totalCost,
      recommendation,
      rationale,
    };
  }

  private getInsertionCandidates(
    gapType: string,
    primaryChain: SkillChain
  ): Array<{ stepId: string; chain: SkillChain; reason: string; priority: 'high' | 'medium' | 'low'; cost: number }> {
    const candidates: Array<{
      stepId: string;
      chain: SkillChain;
      reason: string;
      priority: 'high' | 'medium' | 'low';
      cost: number;
    }> = [];

    // 根据缺口类型推荐不同链的步骤
    switch (gapType) {
      case 'missing-data':
        // 数据缺失 → 补充其他链的数据维度
        if (primaryChain !== 'C') {
          candidates.push({
            stepId: 'C1',
            chain: 'C',
            reason: '数据缺口：补充技术面扫描数据',
            priority: 'high',
            cost: 0,
          });
          candidates.push({
            stepId: 'C2',
            chain: 'C',
            reason: '数据缺口：补充Regime识别',
            priority: 'high',
            cost: 50,
          });
        }
        if (primaryChain !== 'F') {
          candidates.push({
            stepId: 'F1',
            chain: 'F',
            reason: '数据缺口：补充新闻面数据',
            priority: 'medium',
            cost: 500,
          });
        }
        break;

      case 'logical-conflict':
        // 逻辑冲突 → 引入第三方链做仲裁
        if (primaryChain !== 'C') {
          candidates.push({
            stepId: 'C3',
            chain: 'C',
            reason: '逻辑冲突：用量化策略匹配做交叉验证',
            priority: 'high',
            cost: 300,
          });
        }
        if (primaryChain !== 'F') {
          candidates.push({
            stepId: 'F5',
            chain: 'F',
            reason: '逻辑冲突：用基本面分析做交叉验证',
            priority: 'medium',
            cost: 500,
          });
        }
        break;

      case 'low-confidence':
        // 置信度低 → 追加更多分析维度
        if (primaryChain !== 'C') {
          candidates.push({
            stepId: 'C3',
            chain: 'C',
            reason: '置信度不足：补充量化策略验证',
            priority: 'medium',
            cost: 300,
          });
        }
        if (primaryChain !== 'F') {
          candidates.push({
            stepId: 'F2',
            chain: 'F',
            reason: '置信度不足：补充资金流分析',
            priority: 'medium',
            cost: 0,
          });
        }
        break;

      case 'risk-uncertainty':
        // 风险不确定 → 增加风险相关分析
        if (primaryChain !== 'F') {
          candidates.push({
            stepId: 'F3',
            chain: 'F',
            reason: '风险不确定：补充市场情绪分析',
            priority: 'high',
            cost: 0,
          });
        }
        if (primaryChain !== 'C') {
          candidates.push({
            stepId: 'C4',
            chain: 'C',
            reason: '风险不确定：补充回测验证',
            priority: 'medium',
            cost: 800,
          });
        }
        break;

      default:
        // 默认：优先插入低成本高价值的步骤
        if (primaryChain !== 'C') {
          candidates.push({
            stepId: 'C1',
            chain: 'C',
            reason: '默认补充：技术面扫描（零成本）',
            priority: 'low',
            cost: 0,
          });
        }
        if (primaryChain !== 'F') {
          candidates.push({
            stepId: 'F2',
            chain: 'F',
            reason: '默认补充：资金流分析（零成本）',
            priority: 'low',
            cost: 0,
          });
        }
    }

    // 按优先级排序
    const priorityOrder = { high: 0, medium: 1, low: 2 };
    return candidates.sort(
      (a, b) => priorityOrder[a.priority] - priorityOrder[b.priority]
    );
  }

  private generateInsertionRationale(
    lowConfidenceStep: string,
    confidence: number,
    gapType: string,
    insertions: DynamicInsertionPlan['insertions'],
    remainingBudget: number
  ): string {
    const lines: string[] = [];

    lines.push(`【动态插入规划】`);
    lines.push(`触发步骤: ${lowConfidenceStep} (置信度 ${confidence}%)`);
    lines.push(`缺口类型: ${gapType}`);
    lines.push(`剩余预算: ${remainingBudget} Token`);
    lines.push('');

    if (insertions.length > 0) {
      lines.push(`建议插入 ${insertions.length} 个步骤:`);
      insertions.forEach((ins, i) => {
        lines.push(`  ${i + 1}. [${ins.chain}链] ${ins.stepId} - ${ins.reason}`);
      });
      lines.push('');
      lines.push(`额外Token消耗: ${insertions.reduce((s, i) => s + i.cost, 0)}`);
    } else {
      lines.push('建议：不插入，继续主链执行');
      lines.push('原因：预算不足或无合适插入节点');
    }

    return lines.join('\n');
  }
}
