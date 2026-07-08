/**
 * 意图澄清引擎 - 借鉴 Claude Code Superpower 的 "多问后做" 模式
 *
 * 位置: 6-图结构上下文压缩/planner/intent-clarification-engine.ts
 *
 * 设计依据: Claude Code Superpower 插件五步流程
 *   1. Brainstorming（探索意图）
 *   2. Clarifying Questions（逐个追问，多选优先）
 *   3. Architecture Design（方案确认）
 *
 * 核心规则（HARD-GATE）:
 *   - 意图模糊时，必须先澄清再执行，不允许直接跳到实现
 *   - 每次只问一个问题（one-at-a-time）
 *   - 优先多选题，降低用户认知负担
 *   - 澄清问题由 LLM 基于上下文动态生成，非固定模板
 */

import { IntentType, ComplexityLevel } from './planner-types';
import { ExecutionContext, SkillChain, ThinkStage } from './skill-types';
import { SkillsRegistry } from './skills-registry';

// ============================================================
// 类型定义
// ============================================================

/** 意图模糊度级别 */
export type AmbiguityLevel = 'clear' | 'moderate' | 'ambiguous';

/** 澄清问题类型 */
export type ClarificationQuestionType = 'multiple_choice' | 'open_ended';

/** 澄清问题 */
export interface ClarificationQuestion {
  /** 问题 ID */
  id: string;
  /** 问题类型 */
  type: ClarificationQuestionType;
  /** 问题文本 */
  question: string;
  /** 多选选项（type=multiple_choice 时有值） */
  options?: ClarificationOption[];
  /** 此问题要澄清的维度 */
  dimension: 'purpose' | 'scope' | 'depth' | 'constraint' | 'success_criteria';
  /** 问题优先级（1=最高） */
  priority: number;
}

/** 澄清选项 */
export interface ClarificationOption {
  key: string;
  label: string;
  /** 选择此选项后推断的意图 */
  inferredIntent?: IntentType;
  /** 选择此选项后推断的实体 */
  inferredEntities?: Record<string, string>;
  /** 选择此选项后的简短说明 */
  hint?: string;
}

/** 澄清评估结果 */
export interface ClarificationAssessment {
  /** 模糊度级别 */
  ambiguity: AmbiguityLevel;
  /** 模糊度评分 0-100（越高越模糊） */
  ambiguityScore: number;
  /** 是否需要澄清 */
  needsClarification: boolean;
  /** 需要澄清的维度列表（按优先级排序） */
  clarificationDimensions: ClarificationQuestion['dimension'][];
  /** 检测到的模糊原因 */
  ambiguityReasons: string[];
  /** 建议的默认解读（如果不澄清） */
  defaultInterpretation?: {
    intent: IntentType;
    entities: Record<string, string>;
    confidence: number;
  };
}

/** LLM 桥接接口（用于动态生成澄清问题） */
export interface ClarificationLLMBridge {
  /** 调用 LLM 生成澄清问题 */
  generateQuestion(
    userMessage: string,
    assessment: ClarificationAssessment,
    context?: Partial<ExecutionContext>
  ): Promise<ClarificationQuestion>;
}

// ============================================================
// 意图澄清引擎
// ============================================================

/**
 * 意图澄清引擎
 *
 * 工作流程（借鉴 Superpower）:
 *   1. 评估意图模糊度
 *   2. 如果模糊 → 生成澄清问题（LLM 驱动，one-at-a-time）
 *   3. 用户回答后收敛
 *   4. 重复 2-3 直到意图清晰或达到最大轮次
 *   5. 意图清晰后 → 形成可执行方案
 */
export class IntentClarificationEngine {
  private registry: SkillsRegistry;
  private llmBridge?: ClarificationLLMBridge;
  private maxRounds: number;

  constructor(
    registry: SkillsRegistry,
    llmBridge?: ClarificationLLMBridge,
    maxRounds: number = 3
  ) {
    this.registry = registry;
    this.llmBridge = llmBridge;
    this.maxRounds = maxRounds;
  }

  /**
   * 评估意图模糊度
   *
   * 规则（借鉴 Superpower 的触发条件）:
   *   - 意图置信度低 → 模糊
   *   - 缺少关键实体（如 symbol）→ 模糊
   *   - 消息过短或过于泛化 → 模糊
   *   - 意图类型为 need_clarification → 模糊
   *   - 存在多个互斥合理解读 → 模糊
   */
  assessAmbiguity(
    userMessage: string,
    intent: IntentType,
    intentConfidence: number,
    entities: Record<string, string>,
    availableSkills?: string[]
  ): ClarificationAssessment {
    const reasons: string[] = [];
    let score = 0;

    // 1. 意图置信度检测
    if (intentConfidence < 0.6) {
      score += 30;
      reasons.push(`意图置信度低（${(intentConfidence * 100).toFixed(0)}% < 60%）`);
    } else if (intentConfidence < 0.8) {
      score += 15;
      reasons.push(`意图置信度中等（${(intentConfidence * 100).toFixed(0)}%），存在解读空间`);
    }

    // 2. 关键实体缺失检测
    const hasSymbol = !!entities.symbol;
    const hasTimeframe = !!entities.timeframe;
    if (!hasSymbol && this.intentNeedsSymbol(intent)) {
      score += 25;
      reasons.push('缺少交易标的（symbol），无法确定分析对象');
    }
    if (!hasTimeframe && this.intentNeedsTimeframe(intent)) {
      score += 10;
      reasons.push('缺少时间框架，将使用默认值');
    }

    // 3. 消息长度和泛化度检测
    const messageLength = userMessage.trim().length;
    if (messageLength < 10) {
      score += 20;
      reasons.push(`消息过短（${messageLength}字符），意图可能不完整`);
    }
    const vagueKeywords = ['分析', '看看', '怎么样', '如何', '帮我看', '说说', 'analyze', 'check', 'how about'];
    const hasVagueKeyword = vagueKeywords.some(kw => userMessage.toLowerCase().includes(kw));
    if (hasVagueKeyword && messageLength < 30) {
      score += 15;
      reasons.push('包含泛化关键词且缺少具体方向');
    }

    // 4. 多解读检测：消息可能匹配多种意图
    const possibleIntents = this.detectMultipleInterpretations(userMessage, entities);
    if (possibleIntents.length > 1) {
      score += 20;
      reasons.push(`存在 ${possibleIntents.length} 种合理解读：${possibleIntents.join('、')}`);
    }

    // 5. 节点覆盖检测：注册表中是否有足够节点处理此意图
    if (availableSkills !== undefined) {
      const coverage = this.checkNodeCoverage(intent, availableSkills);
      if (coverage.gapCount > 0) {
        score += 10;
        reasons.push(`注册表中缺少 ${coverage.gapCount} 个关键能力节点`);
      }
    }

    // 6. need_clarification 意图直接判定为模糊
    if (intent === 'need_clarification' as any) {
      score = Math.max(score, 60);
      reasons.push('意图识别引擎已标记需要澄清');
    }

    score = Math.min(score, 100);

    const ambiguity: AmbiguityLevel =
      score >= 50 ? 'ambiguous' : score >= 25 ? 'moderate' : 'clear';

    const needsClarification = ambiguity !== 'clear';
    const clarificationDimensions = this.determineClarificationDimensions(reasons);

    const defaultInterpretation = ambiguity !== 'ambiguous'
      ? {
          intent,
          entities,
          confidence: Math.max(intentConfidence, 0.5),
        }
      : undefined;

    return {
      ambiguity,
      ambiguityScore: score,
      needsClarification,
      clarificationDimensions,
      ambiguityReasons: reasons,
      defaultInterpretation,
    };
  }

  /**
   * 生成澄清问题
   *
   * 借鉴 Superpower 的规则:
   *   - one question at a time（每次只问一个）
   *   - multiple choice preferred（优先多选）
   *   - 聚焦 purpose / scope / depth / constraint / success_criteria
   *
   * 如果有 LLM 桥接器，用 LLM 动态生成
   * 否则用规则模板生成（fallback）
   */
  async generateClarificationQuestion(
    userMessage: string,
    assessment: ClarificationAssessment,
    currentRound: number,
    context?: Partial<ExecutionContext>
  ): Promise<ClarificationQuestion | null> {
    // 超过最大轮次，不再生成问题
    if (currentRound >= this.maxRounds) {
      return null;
    }

    // 如果有 LLM 桥接器，用 LLM 动态生成
    if (this.llmBridge) {
      try {
        return await this.llmBridge.generateQuestion(userMessage, assessment, context);
      } catch {
        // LLM 生成失败，降级到规则模板
      }
    }

    // 规则模板生成（fallback）
    return this.generateRuleBasedQuestion(assessment, currentRound, context);
  }

  /**
   * 检查节点覆盖度
   */
  checkNodeCoverage(
    intent: IntentType,
    availableSkillIds: string[]
  ): { gapCount: number; missingCapabilities: string[] } {
    const allSkills = this.registry.getAll();
    const registeredIds = new Set(allSkills.map(s => s.metadata.id));

    // 检查 availableSkillIds 中有多少在注册表中
    const missing = availableSkillIds.filter(id => !registeredIds.has(id));
    return {
      gapCount: missing.length,
      missingCapabilities: missing,
    };
  }

  // ============================================================
  // 私有方法
  // ============================================================

  private intentNeedsSymbol(intent: IntentType): boolean {
    return ['deep_analysis', 'market_query', 'scenario_sim', 'strategy_verify', 'execute_trade', 'risk_alert'].includes(intent);
  }

  private intentNeedsTimeframe(intent: IntentType): boolean {
    return ['deep_analysis', 'scenario_sim', 'strategy_verify', 'execute_trade'].includes(intent);
  }

  private detectMultipleInterpretations(
    message: string,
    entities: Record<string, string>
  ): string[] {
    const interpretations: string[] = [];
    const lowerMsg = message.toLowerCase();

    // 检测"分析"关键词 → 可能是行情查询或深度分析
    if (/分析|走势|趋势|analyze|trend/.test(lowerMsg)) {
      interpretations.push('market_query', 'deep_analysis');
    }

    // 检测"策略/交易"关键词 → 可能是策略验证或执行交易
    if (/策略|交易|买入|卖出|strategy|trade|buy|sell/.test(lowerMsg)) {
      interpretations.push('strategy_verify', 'execute_trade');
    }

    // 检测"模拟/推演"关键词
    if (/模拟|推演|如果|simulate|scenario/.test(lowerMsg)) {
      interpretations.push('scenario_sim');
    }

    // 去重
    return [...new Set(interpretations)];
  }

  private determineClarificationDimensions(
    reasons: string[]
  ): ClarificationQuestion['dimension'][] {
    const dimensions: ClarificationQuestion['dimension'][] = [];

    if (reasons.some(r => r.includes('意图置信度') || r.includes('合理解读'))) {
      dimensions.push('purpose');
    }
    if (reasons.some(r => r.includes('交易标的') || r.includes('时间框架'))) {
      dimensions.push('scope');
    }
    if (reasons.some(r => r.includes('泛化关键词') || r.includes('消息过短'))) {
      dimensions.push('depth');
    }
    if (reasons.some(r => r.includes('能力节点'))) {
      dimensions.push('constraint');
    }

    // 默认至少有 purpose
    if (dimensions.length === 0) {
      dimensions.push('purpose');
    }

    return dimensions;
  }

  /**
   * 规则模板生成澄清问题（LLM 不可用时的 fallback）
   */
  private generateRuleBasedQuestion(
    assessment: ClarificationAssessment,
    round: number,
    context?: Partial<ExecutionContext>
  ): ClarificationQuestion {
    const dimension = assessment.clarificationDimensions[round] || 'purpose';
    const symbol = context?.symbol || '';

    switch (dimension) {
      case 'purpose':
        return {
          id: `clarify_${round}_purpose`,
          type: 'multiple_choice',
          question: '你主要想了解什么方面？',
          dimension: 'purpose',
          priority: 1,
          options: [
            {
              key: 'market',
              label: `查询${symbol ? ` ${symbol}` : ''}实时行情`,
              inferredIntent: 'market_query' as IntentType,
              hint: '快速获取当前价格和基本指标',
            },
            {
              key: 'analysis',
              label: `深度分析${symbol ? ` ${symbol}` : ''}走势`,
              inferredIntent: 'deep_analysis' as IntentType,
              hint: '多维度技术面+基本面分析',
            },
            {
              key: 'strategy',
              label: `制定${symbol ? ` ${symbol}` : ''}交易策略`,
              inferredIntent: 'strategy_verify' as IntentType,
              hint: '入场/止损/止盈方案设计',
            },
          ],
        };

      case 'scope':
        return {
          id: `clarify_${round}_scope`,
          type: 'multiple_choice',
          question: '关注哪个时间周期？',
          dimension: 'scope',
          priority: 2,
          options: [
            { key: 'short', label: '短线（1h-4h）', hint: '适合日内交易' },
            { key: 'mid', label: '中线（1d-1w）', hint: '适合波段交易' },
            { key: 'long', label: '长线（1w+）', hint: '适合趋势投资' },
          ],
        };

      case 'depth':
        return {
          id: `clarify_${round}_depth`,
          type: 'multiple_choice',
          question: '需要多深入的分析？',
          dimension: 'depth',
          priority: 3,
          options: [
            { key: 'quick', label: '快速概览', hint: '核心指标+趋势判断' },
            { key: 'standard', label: '标准分析', hint: '多维度+交叉验证' },
            { key: 'deep', label: '全面深度', hint: '技术面+基本面+链上+情绪' },
          ],
        };

      case 'constraint':
        return {
          id: `clarify_${round}_constraint`,
          type: 'open_ended',
          question: '有什么特别的约束或偏好需要考虑吗？（如风险承受能力、资金规模等，可跳过）',
          dimension: 'constraint',
          priority: 4,
        };

      default:
        return {
          id: `clarify_${round}_default`,
          type: 'open_ended',
          question: '能再具体描述一下你的需求吗？',
          dimension: 'success_criteria',
          priority: 5,
        };
    }
  }
}

// ============================================================
// 便捷函数
// ============================================================

/**
 * 构建澄清问题的前端展示内容
 */
export function buildClarificationContent(
  question: ClarificationQuestion,
  lang: 'zh' | 'en' = 'zh'
): { content: string; options: any[] } {
  const isZh = lang === 'zh';

  if (question.type === 'open_ended') {
    return {
      content: `🤔 **${question.question}**\n\n> ${isZh ? '请直接回复你的回答' : 'Please reply with your answer'}`,
      options: [],
    };
  }

  const options = question.options || [];
  const optionLines = options.map((opt, i) => {
    const hint = opt.hint ? `\n  _${opt.hint}_` : '';
    return `- [${i + 1}] ${opt.label}${hint}`;
  }).join('\n\n');

  const hint = isZh
    ? '> 请点击选项按钮，或输入数字选择'
    : '> Click option button, or reply number';

  const content = `🤔 **${question.question}**\n\n${optionLines}\n\n${hint}`;

  return {
    content,
    options: options.map((opt, i) => ({
      key: opt.key || `opt_${i + 1}`,
      label: opt.label,
      target_intent: opt.inferredIntent,
      entities: opt.inferredEntities || {},
    })),
  };
}
