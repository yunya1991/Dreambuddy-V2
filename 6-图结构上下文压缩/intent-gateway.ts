/**
 * 意图识别网关 v2 (Intent Gateway)
 *
 * 位置: 6-图结构上下文压缩/intent-gateway.ts
 *
 * 核心能力：
 *   1. 可扩展意图处理器插件 (IntentHandler) — 外部模块可随时注册新意图
 *   2. 置信度状态机 — detecting → clarifying → confirmed
 *      低置信度时自动生成澄清问题，不猜测意图
 *   3. clarify(answer) 二次确认 — 接收用户回答后重新推断并锁定
 *   4. 意图切换检测 + OKR 目标管理
 *
 * OKR 映射：
 *   B 层根节点 = Long-term Objective（意图目标，跨多轮持久）
 *   A 层步骤   = Key Results / Mid-term tasks（当轮 Planner 计划）
 *   C 层记录   = Short-term execution（当步执行记录）
 */

import { detectIntent, type IntentMatch } from './skills/graph-compressor/core/auto-graph-generator.ts';
import type { CompressItem } from './contract.ts';

// ============================================================
// OKR 类型
// ============================================================

export type OKRHorizon = 'long' | 'mid' | 'short';

// ============================================================
// 意图处理器插件协议（可扩展点）
// ============================================================

/**
 * 意图处理器插件
 *
 * 任何模块都可以实现并注册，添加新的意图类型：
 *   gateway.register({ id: 'my-intent', ... })
 */
export interface IntentHandler {
  /** 唯一标识，与 detectIntent 返回的 intent 字段对应 */
  id: string;

  /** 可读名称，用于展示和日志 */
  name: string;

  /**
   * 关键词列表（用于快速匹配，可选）
   * 注册后会自动补充到内置关键词引擎
   */
  keywords?: string[];

  /**
   * 自定义打分函数（可选，优先级高于关键词）
   * 返回 0-1 的置信度；返回 0 表示不匹配此意图
   */
  score?: (userMessage: string, history: string[]) => number;

  /** Long-term Objective 描述 */
  objective: string;

  /** 推荐的 Blueprint 模板 ID */
  recommendedBlueprint: string;

  /**
   * 澄清问题生成器（可选）
   * 当置信度低于阈值时，会调用此函数生成追问
   * @param candidates 当前置信度排名前几的候选意图
   */
  clarifyQuestion?: (candidates: CandidateIntent[]) => ClarifyQuestion;
}

/** 候选意图（用于澄清问题生成） */
export interface CandidateIntent {
  id: string;
  name: string;
  confidence: number;
  keywords: string[];
}

/** 澄清问题 */
export interface ClarifyQuestion {
  /** 向用户提问的自然语言文本 */
  question: string;
  /** 选项（可选，有时用来引导用户选择） */
  options?: Array<{ label: string; intentId: string }>;
  /** 提示词（帮助用户理解） */
  hint?: string;
}

// ============================================================
// 网关内部状态
// ============================================================

export type GatewayState = 'detecting' | 'clarifying' | 'confirmed';

// ============================================================
// 网关输出类型
// ============================================================

/**
 * 网关处理结果
 *
 * 两种情况：
 *   state='confirmed' → 意图已确认，goal 包含完整目标，blueprintItem 可写入 B 层
 *   state='clarifying' → 置信度不足，clarifyQuestion 包含需要追问用户的问题
 */
export interface IntentGatewayResult {
  /** 当前状态 */
  state: GatewayState;
  /** 当前活跃的意图目标（confirmed 时一定有，clarifying 时可能是临时候选） */
  goal: IntentGoal;
  /** 是否是新意图 */
  isNewIntent: boolean;
  /** 上一个意图（切换时） */
  previousGoal?: IntentGoal;
  /** B 层节点（confirmed 时可用） */
  blueprintItem: CompressItem;
  /** 澄清问题（clarifying 状态时才有） */
  clarifyQuestion?: ClarifyQuestion;
  /** 候选意图列表（clarifying 状态时辅助展示） */
  candidates?: CandidateIntent[];
  /** 摘要文本（日志/调试） */
  summary: string;
}

/** 意图目标节点 */
export interface IntentGoal {
  id: string;
  intent: string;
  name: string;
  objective: string;
  horizon: OKRHorizon;
  confidence: number;
  /** 是否经过澄清确认（true=用户主动确认，false=自动推断） */
  clarified: boolean;
  triggerKeywords: string[];
  recommendedBlueprint: string;
  createdAt: number;
  updatedAt: number;
  completedRounds: number;
  active: boolean;
}

// ============================================================
// 内置意图处理器（可被外部覆盖/扩展）
// ============================================================

const BUILT_IN_HANDLERS: IntentHandler[] = [
  {
    id: 'trading',
    name: '交易执行',
    keywords: ['买入', '卖出', '入场', '离场', '止损', '做多', '做空', '开仓', '加仓', '平仓', '下单', 'buy', 'sell', 'position', 'entry', 'exit'],
    objective: '执行加密货币交易决策（入场/出场/风控）',
    recommendedBlueprint: 'classic-trading',
  },
  {
    id: 'analysis',
    name: '行情分析',
    keywords: ['分析', '研究', '调研', '行情', '趋势', '市场', '数据', '指标', '技术面', '基本面', 'macd', 'rsi', '布林带', 'analysis', 'market', 'trend'],
    objective: '对市场行情和资产进行深度分析研究',
    recommendedBlueprint: 'deep-analysis',
  },
  {
    id: 'strategy',
    name: '策略研究',
    keywords: ['策略', '设计', '优化', '回测', '参数', '规则', '信号', '触发', 'strategy', 'backtest', 'design', 'optimize'],
    objective: '设计、验证和优化交易策略',
    recommendedBlueprint: 'strategy-research',
  },
  {
    id: 'risk',
    name: '风险管理',
    keywords: ['风险', '风控', '止损', '止盈', '资金管理', '保证金', '杠杆', '夏普', '最大回撤', '胜率', 'risk', 'stop-loss'],
    objective: '识别和管理交易风险（止损/仓位/资金管理）',
    recommendedBlueprint: 'risk-management',
  },
  {
    id: 'coding',
    name: '代码开发',
    keywords: ['代码', '实现', '开发', 'bug', '修复', '组件', '模块', 'code', 'implement', 'dev', 'fix', 'build'],
    objective: '开发和调试代码功能模块',
    recommendedBlueprint: 'coding-task',
  },
  {
    id: 'design',
    name: '系统设计',
    keywords: ['设计', '架构', '方案', '规划', '结构', '模型', 'design', 'architecture', 'structure', 'model'],
    objective: '设计系统架构和技术方案',
    recommendedBlueprint: 'system-design',
  },
  {
    id: 'compression',
    name: '上下文压缩',
    keywords: ['压缩', '总结', '摘要', '上下文', '图压缩', 'compress', 'summary', 'context'],
    objective: '管理和压缩对话上下文',
    recommendedBlueprint: 'context-compression',
  },
  {
    id: 'scheduling',
    name: '任务调度',
    keywords: ['调度', 'skip', '跳过', '决策', '优先级', '调度器', 'schedule', 'priority', 'skip-gate'],
    objective: '编排和调度执行任务流',
    recommendedBlueprint: 'scheduler-orchestration',
  },
  {
    id: 'general',
    name: '通用任务',
    keywords: [],
    objective: '通用任务处理',
    recommendedBlueprint: 'default-template',
    clarifyQuestion: (candidates) => ({
      question: `我注意到您的请求比较广泛，请问您希望我重点帮您做什么？`,
      options: candidates.slice(0, 4).map(c => ({ label: c.name, intentId: c.id })),
      hint: '选择最符合您需求的方向，我会据此制定更精准的计划',
    }),
  },
];

// ============================================================
// 意图处理器注册表（全局单例）
// ============================================================

class IntentHandlerRegistry {
  private handlers = new Map<string, IntentHandler>();

  constructor(handlers = BUILT_IN_HANDLERS) {
    handlers.forEach(h => this.handlers.set(h.id, h));
  }

  /** 注册新意图处理器（id 已存在则覆盖） */
  register(handler: IntentHandler): void {
    this.handlers.set(handler.id, handler);
  }

  /** 批量注册 */
  registerAll(handlers: IntentHandler[]): void {
    handlers.forEach(h => this.register(h));
  }

  get(id: string): IntentHandler | undefined {
    return this.handlers.get(id);
  }

  getAll(): IntentHandler[] {
    return Array.from(this.handlers.values());
  }

  /**
   * 对用户消息进行全量打分，返回排序后的候选意图列表
   * 优先使用 handler.score()，其次用关键词匹配
   */
  score(userMessage: string, history: string[]): CandidateIntent[] {
    const lower = userMessage.toLowerCase();
    const candidates: CandidateIntent[] = [];

    for (const handler of this.handlers.values()) {
      let confidence = 0;

      if (handler.score) {
        // 自定义打分函数优先
        confidence = handler.score(userMessage, history);
      } else if (handler.keywords && handler.keywords.length > 0) {
        // 关键词匹配打分
        const hits = handler.keywords.filter(kw => lower.includes(kw.toLowerCase()));
        confidence = hits.length > 0 ? Math.min(1, hits.length / Math.max(3, handler.keywords.length * 0.3)) : 0;
      }

      if (confidence > 0 || handler.id === 'general') {
        candidates.push({
          id: handler.id,
          name: handler.name,
          confidence,
          keywords: (handler.keywords ?? []).filter(kw => lower.includes(kw.toLowerCase())),
        });
      }
    }

    return candidates
      .sort((a, b) => b.confidence - a.confidence)
      .filter(c => c.id !== 'general' || candidates.every(x => x.id === 'general' || x.confidence === 0));
  }
}

export const intentRegistry = new IntentHandlerRegistry();

// ============================================================
// Intent Gateway 类
// ============================================================

/** 置信度阈值配置 */
export interface GatewayThresholds {
  /** 低于此值触发澄清流程（默认 0.25） */
  clarifyBelow: number;
  /** 高于此值直接确认（默认 0.4） */
  confirmAbove: number;
}

const DEFAULT_THRESHOLDS: GatewayThresholds = {
  clarifyBelow: 0.25,
  confirmAbove: 0.40,
};

export class IntentGateway {
  private currentGoal: IntentGoal | null = null;
  private goalHistory: IntentGoal[] = [];
  private state: GatewayState = 'detecting';
  private pendingCandidates: CandidateIntent[] = [];
  private thresholds: GatewayThresholds;

  constructor(_sessionId: string, thresholds?: Partial<GatewayThresholds>) {
    this.thresholds = { ...DEFAULT_THRESHOLDS, ...thresholds };
  }

  // ──────────────────────────────────────────────────────────
  // 主入口：处理用户消息
  // ──────────────────────────────────────────────────────────

  /**
   * 处理用户消息 → 返回 confirmed 结果 或 clarifying（含追问）
   *
   * 状态机：
   *   detecting  → 对消息打分
   *     topConf >= confirmAbove  → confirmed
   *     topConf <  clarifyBelow  → clarifying（生成追问）
   *     中间区间                  → 尝试用 detectIntent 增强，再判断
   */
  process(
    userMessage: string,
    previousMessages: Array<{ role: string; content: string }> = []
  ): IntentGatewayResult {
    const history = previousMessages.map(m => m.content);

    // 1. 全量打分
    const candidates = intentRegistry.score(userMessage, history);
    const top = candidates[0] ?? { id: 'general', name: '通用任务', confidence: 0, keywords: [] };

    // 2. 增强：使用内置 detectIntent 补充（处理中文语义）
    const msgWindow = [
      ...previousMessages.slice(-4).map((m, i) => ({ id: `ctx_${i}`, role: m.role as 'user' | 'assistant', content: m.content })),
      { id: 'current', role: 'user' as const, content: userMessage },
    ];
    const builtin: IntentMatch = detectIntent(msgWindow);

    // 3. 融合置信度：取两者较高值，builtin 权重 0.4
    let topConfidence = Math.max(top.confidence, builtin.confidence * 0.4);
    let topIntentId = topConfidence === top.confidence ? top.id : builtin.intent;
    // 如果两者都指向同一意图，置信度相加（上限 1）
    if (top.id === builtin.intent) {
      topConfidence = Math.min(1, top.confidence + builtin.confidence * 0.3);
      topIntentId = top.id;
    }

    // 4. 决策
    if (topConfidence >= this.thresholds.confirmAbove) {
      // 直接确认
      return this.confirm(topIntentId, topConfidence, top.keywords, false, candidates);
    }

    if (topConfidence < this.thresholds.clarifyBelow) {
      // 置信度太低，触发澄清
      this.state = 'clarifying';
      this.pendingCandidates = candidates.slice(0, 4);
      return this.buildClarifyResult(userMessage, candidates);
    }

    // 中间区间：尝试判断是否有明确的"第一名领先第二名"
    const second = candidates[1];
    const gap = second ? topConfidence - second.confidence : topConfidence;
    if (gap >= 0.15) {
      // 领先足够，直接确认
      return this.confirm(topIntentId, topConfidence, top.keywords, false, candidates);
    }

    // 竞争太激烈，澄清
    this.state = 'clarifying';
    this.pendingCandidates = candidates.slice(0, 4);
    return this.buildClarifyResult(userMessage, candidates);
  }

  /**
   * 接收用户对澄清问题的回答，重新推断并锁定意图
   *
   * @param answer 用户回答（自然语言或直接选项 intentId）
   * @param selectedIntentId 如果前端提供了明确的选项 ID，直接用
   */
  clarify(
    answer: string,
    selectedIntentId?: string
  ): IntentGatewayResult {
    if (this.state !== 'clarifying') {
      // 不在澄清状态，当普通消息处理
      return this.process(answer);
    }

    // 优先使用直接选择的 intentId
    if (selectedIntentId && intentRegistry.get(selectedIntentId)) {
      this.state = 'confirmed';
      return this.confirm(selectedIntentId, 0.95, [], true, this.pendingCandidates);
    }

    // 用用户回答重新打分
    const candidates = intentRegistry.score(answer, []);

    // 结合之前的候选，加权投票
    const mergedScores = new Map<string, number>();
    this.pendingCandidates.forEach(c => mergedScores.set(c.id, c.confidence * 0.4));
    candidates.forEach(c => {
      const prev = mergedScores.get(c.id) ?? 0;
      mergedScores.set(c.id, prev + c.confidence * 0.6);
    });

    const sorted = Array.from(mergedScores.entries())
      .sort((a, b) => b[1] - a[1]);
    const [winId, winConf] = sorted[0] ?? ['general', 0.3];

    this.state = 'confirmed';
    return this.confirm(winId, Math.min(1, winConf + 0.2), [], true, candidates);
  }

  // ──────────────────────────────────────────────────────────
  // 内部方法
  // ──────────────────────────────────────────────────────────

  private confirm(
    intentId: string,
    confidence: number,
    keywords: string[],
    clarified: boolean,
    _candidates: CandidateIntent[]
  ): IntentGatewayResult {
    const handler = intentRegistry.get(intentId) ?? intentRegistry.get('general')!;

    const isNewIntent = !this.currentGoal || this.currentGoal.intent !== intentId;
    const previousGoal = isNewIntent ? (this.currentGoal ?? undefined) : undefined;

    if (isNewIntent || !this.currentGoal) {
      if (this.currentGoal) {
        this.currentGoal.active = false;
        this.goalHistory.push({ ...this.currentGoal });
      }
      this.currentGoal = {
        id: `goal_${intentId}_${Date.now()}`,
        intent: intentId,
        name: handler.name,
        objective: handler.objective,
        horizon: 'long',
        confidence,
        clarified,
        triggerKeywords: keywords,
        recommendedBlueprint: handler.recommendedBlueprint,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        completedRounds: 0,
        active: true,
      };
    } else {
      this.currentGoal.confidence = Math.max(this.currentGoal.confidence, confidence);
      if (clarified) this.currentGoal.clarified = true;
      const newKws = keywords.filter(k => !this.currentGoal!.triggerKeywords.includes(k));
      this.currentGoal.triggerKeywords.push(...newKws);
      this.currentGoal.updatedAt = Date.now();
    }

    this.state = 'confirmed';
    this.pendingCandidates = [];

    const goal = this.currentGoal;
    const blueprintItem = this.buildBlueprintItem(goal);
    const summary = isNewIntent
      ? `[意图网关/confirmed${clarified ? '/clarified' : ''}] 意图: ${handler.name}（${(confidence * 100).toFixed(0)}%）→ "${goal.objective}"${previousGoal ? ` ← 切换自: ${previousGoal.name}` : ''}`
      : `[意图网关/confirmed] 意图延续: ${handler.name}（第 ${goal.completedRounds + 1} 轮）`;

    return { state: 'confirmed', goal, isNewIntent, previousGoal, blueprintItem, summary };
  }

  private buildClarifyResult(
    userMessage: string,
    candidates: CandidateIntent[]
  ): IntentGatewayResult {
    // 找最相关的 handler 生成澄清问题
    const topHandler = candidates.length > 0 ? intentRegistry.get(candidates[0].id) : undefined;
    const generalHandler = intentRegistry.get('general')!;

    // 优先用 topHandler 的澄清生成器，其次用 general，最后兜底
    let clarifyQuestion: ClarifyQuestion;
    const topClarify = topHandler?.clarifyQuestion ?? generalHandler.clarifyQuestion;

    if (topClarify) {
      clarifyQuestion = topClarify(candidates.slice(0, 4));
    } else {
      // 兜底：生成通用澄清问题
      clarifyQuestion = this.buildDefaultClarifyQuestion(userMessage, candidates);
    }

    // 临时目标节点（不写入 goalHistory，等确认后才真正激活）
    const tempGoal: IntentGoal = this.currentGoal ?? {
      id: `goal_pending_${Date.now()}`,
      intent: 'pending',
      name: '待确认',
      objective: '正在识别您的意图，请稍后确认',
      horizon: 'long',
      confidence: candidates[0]?.confidence ?? 0,
      clarified: false,
      triggerKeywords: candidates[0]?.keywords ?? [],
      recommendedBlueprint: 'default-template',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      completedRounds: 0,
      active: false,
    };

    const blueprintItem = this.buildBlueprintItem(tempGoal);
    const summary = `[意图网关/clarifying] 置信度不足（top=${((candidates[0]?.confidence ?? 0) * 100).toFixed(0)}%），需要澄清 → "${clarifyQuestion.question}"`;

    return {
      state: 'clarifying',
      goal: tempGoal,
      isNewIntent: !this.currentGoal,
      blueprintItem,
      clarifyQuestion,
      candidates: candidates.slice(0, 4),
      summary,
    };
  }

  private buildDefaultClarifyQuestion(
    _userMessage: string,
    candidates: CandidateIntent[]
  ): ClarifyQuestion {
    const hasCandidates = candidates.filter(c => c.confidence > 0);

    if (hasCandidates.length === 0) {
      return {
        question: '我没有完全理解您的需求，您能更具体地描述一下想做什么吗？',
        hint: '例如：分析行情、执行交易、设计策略、管理风险等',
      };
    }

    if (hasCandidates.length === 1) {
      const c = hasCandidates[0];
      return {
        question: `您是指「${c.name}」相关的任务吗？还是有其他意图？`,
        options: [
          { label: `是的，${c.name}`, intentId: c.id },
          { label: '不是，我来描述一下', intentId: 'general' },
        ],
      };
    }

    return {
      question: '我检测到您的请求可能涉及以下几个方向，请问您主要想做哪方面？',
      options: hasCandidates.slice(0, 4).map(c => ({
        label: c.name,
        intentId: c.id,
      })),
      hint: '选择最符合的方向，或者直接告诉我具体需求',
    };
  }

  private buildBlueprintItem(goal: IntentGoal): CompressItem {
    return {
      id: `intent_blueprint_${goal.id}`,
      type: 'other',
      content: `[B层-总目标/Long OKR] intent=${goal.intent} name="${goal.name}" objective="${goal.objective}" conf=${(goal.confidence * 100).toFixed(0)}% clarified=${goal.clarified}`,
      tokens: 60,
      timestamp: goal.createdAt,
      meta: {
        layer: 'B',
        horizon: 'long',
        intentGoalId: goal.id,
        intent: goal.intent,
        intentName: goal.name,
        objective: goal.objective,
        confidence: goal.confidence,
        clarified: goal.clarified,
        isOKRRoot: true,
        blueprintTemplate: goal.recommendedBlueprint,
      },
    };
  }

  // ──────────────────────────────────────────────────────────
  // 公开 API
  // ──────────────────────────────────────────────────────────

  getCurrentState(): GatewayState { return this.state; }
  getCurrentGoal(): IntentGoal | null { return this.currentGoal; }
  getGoalHistory(): IntentGoal[] { return [...this.goalHistory, ...(this.currentGoal ? [this.currentGoal] : [])]; }

  completeRound(): void {
    if (this.currentGoal) {
      this.currentGoal.completedRounds++;
      this.currentGoal.updatedAt = Date.now();
    }
  }

  getOKRSummary(): string {
    const goal = this.currentGoal;
    if (!goal) return '（无活跃目标）';
    const history = this.goalHistory.slice(-3);
    const lines = [
      `## OKR 总目标（Long-term Objective）`,
      `- **意图**: ${goal.name}（${goal.intent}）`,
      `- **置信度**: ${(goal.confidence * 100).toFixed(0)}%${goal.clarified ? ' ✓已澄清确认' : ''}`,
      `- **目标**: ${goal.objective}`,
      `- **已完成轮次**: ${goal.completedRounds}`,
      `- **状态**: ${this.state}`,
    ];
    if (history.length > 0) {
      lines.push(`\n## 历史目标变更`);
      history.forEach(h => lines.push(`- [${new Date(h.createdAt).toLocaleTimeString()}] ${h.name}: ${h.objective} (${h.completedRounds}轮)`));
    }
    return lines.join('\n');
  }
}

// ============================================================
// 工厂函数（按 sessionId 缓存单例）
// ============================================================

const gatewayCache = new Map<string, IntentGateway>();

export function getIntentGateway(
  sessionId: string,
  thresholds?: Partial<GatewayThresholds>
): IntentGateway {
  if (!gatewayCache.has(sessionId)) {
    gatewayCache.set(sessionId, new IntentGateway(sessionId, thresholds));
  }
  return gatewayCache.get(sessionId)!;
}

export function clearIntentGateway(sessionId: string): void {
  gatewayCache.delete(sessionId);
}

/**
 * 全局注册新意图处理器（供外部模块调用）
 *
 * 示例：
 *   import { registerIntent } from './intent-gateway.ts';
 *   registerIntent({
 *     id: 'portfolio',
 *     name: '组合管理',
 *     keywords: ['持仓', '组合', '再平衡', 'portfolio'],
 *     objective: '管理用户资产组合与再平衡',
 *     recommendedBlueprint: 'portfolio-management',
 *   });
 */
export function registerIntent(handler: IntentHandler): void {
  intentRegistry.register(handler);
}

export function registerIntents(handlers: IntentHandler[]): void {
  intentRegistry.registerAll(handlers);
}
