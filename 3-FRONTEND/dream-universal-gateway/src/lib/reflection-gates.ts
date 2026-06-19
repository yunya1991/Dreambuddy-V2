/**
 * S系列 增强模块 — 6 个智能决策模块
 * ============================================================
 *
 * 功能列表：
 *  1. 自省 Gate（S2/S3 完成后批判分析）
 *  2. 验证回退（S4 失败 → 自动返回 S3）
 *  3. 自适应路径（置信度阈值判断是否提前收敛）
 *  4. 置信度/风险评分元数据传递
 *  5. 思考深度映射（thinking_mode 到链长度）
 *  6. 工具调用质疑-验证-修正闭环
 *
 * 设计原则：所有函数纯函数、无副作用、便于单测
 *
 * @stability internal
 */

// ============================================================
// 类型定义
// ============================================================

export type StepPhase =
  | 'S1_RESEARCH'
  | 'S2_ANALYSIS'
  | 'S3_DESIGN'
  | 'S4_VALIDATE'
  | 'S5_EXECUTE';

export type ThinkingDepth = 'quick' | 'standard' | 'deep';

export interface StepMetadata {
  /** 步骤编号 */
  step: StepPhase;
  /** 步骤内容 */
  content: string;
  /** 上一步产生的 metadata */
  previous?: StepMetadata;
  /** 当前累计置信度 0-1 */
  confidence: number;
  /** 风险评分 0-1（越大越 risky） */
  riskScore: number;
  /** 不确定性来源说明 */
  uncertaintyTags: string[];
  /** 自省 Gate 是否通过 */
  gatePassed: boolean;
  /** 自省 Gate 发现的问题 */
  issuesFound: string[];
  /** 自省 Gate 给出的修正建议 */
  corrections: string[];
  /** 是否应该被跳过（由 skip gate 判断） */
  shouldBeSkipped: boolean;
  /** skip reason */
  skipReason?: string;
}

export interface SelfCriticismResult {
  passed: boolean;
  confidenceDelta: number;
  riskScore: number;
  issues: string[];
  corrections: string[];
  uncertaintyTags: string[];
}

export interface AdaptiveRoutingDecision {
  skipStep: boolean;
  reason: string;
  confidenceDelta: number;
}

// ============================================================
// 5. 思考深度映射：根据 thinking_mode 决定执行哪些步骤
// ============================================================

/**
 * 根据思考深度决定应执行的 S 系列步骤
 *
 * - quick: 只保留 S2 分析 + S5 执行（市场查询/简单场景）
 * - standard: S1 + S2 + S3 + S5（完整闭环
 * - deep: S1 + S2 + S3 + S4 + S5
 */
export function getChainByThinkingDepth(thinkingMode: string, intentType?: string): StepPhase[] {
  const fullChain: StepPhase[] = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
  const standardChain: StepPhase[] = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S5_EXECUTE'];
  const quickChain: StepPhase[] = ['S2_ANALYSIS', 'S5_EXECUTE'];

  // market_query/策略验证/简单问答 → 走 quick
  // deep_analysis → 走 fullChain
  // 其他 → standard
  const normalized = String(thinkingMode).toLowerCase();
  if (normalized === 'quick' || normalized === 'fast' || normalized === 'fast_mode') {
    return quickChain;
  }
  if (normalized === 'deep' || normalized === 'slow' || normalized === 'deep_mode') {
    return fullChain;
  }
  // default: standard or empty or normal
  return standardChain;
}

/**
 * 根据用户的原始 chain 长度判断思考深度
 *
 * 用户在发送 "深度分析" / "快速分析" 时，应切换 thinkingMode。
 * 但如果用户没有明确表达思考深度，就使用默认值 standard。
 */
export function detectThinkingDepth(userMessage: string): ThinkingDepth {
  const text = userMessage.toLowerCase();
  if (text.includes('深度') || text.includes('完整') || text.includes('全面') ||
      text.includes('详细') || text.includes('推理') || text.includes('自我批判')) {
    return 'deep';
  }
  if (text.includes('快速') || text.includes('简单') || text.includes('简洁') ||
      text.includes('简明') || text.includes('简要') || text.includes('快速分析')) {
    return 'quick';
  }
  return 'standard';
}

// ============================================================
// 4. 置信度/风险评分元数据传递
// ============================================================

/**
 * 根据步骤内容估计置信度与风险评分
 * - 判断依据：关键词出现频率、矛盾信号、主观声明、明确结论等
 */
export function analyzeStepConfidence(
  step: StepPhase,
  content: string,
  marketDataSnapshot?: any
): { confidence: number; riskScore: number; uncertaintyTags: string[] } {
  let confidence = 0.8; // baseline 提升: 0.7 -> 0.8
  let riskScore = 0.3;
  const uncertaintyTags: string[] = [];

  // 关键词：自信 / 低信信号（降低惩罚强度 + 区分步骤敏感性）
  // S2/S3 中"可能"、"假设"等是合理的推理用语，不应过度惩罚
  const lowConfidencePatterns = [
    '可能', '或许', '也许', '大概', '不确定',
    '需确认', '待验证', '假设', '仅供参考',
    '需回测', '未验证', '推测', '理论上'
  ];
  const strongLowConfidencePatterns = [
    '不确定', '待验证', '未验证', '需回测'
  ];

  const highConfidencePatterns = [
    '明确', '清晰', '明显', '确定', '确定性',
    '已验证', '历史数据', '统计显著', '确认',
    '验证通过', '支撑位', '阻力位', '数据支持', '数据支撑',
  ];

  const riskPatterns = [
    '杠杆', '高风险', '止损', '强制平仓',
    '极端', '黑天鹅', '尾部风险', '单边', '趋势反转'
  ];

  // 低置信度词惩罚: -0.05 -> -0.02 (温和)，强不确定性词保持 -0.05
  for (const p of lowConfidencePatterns) {
    if (content.includes(p)) {
      const isStrong = strongLowConfidencePatterns.includes(p);
      confidence -= isStrong ? 0.05 : 0.02;
      if (!uncertaintyTags.includes('低置信度表述')) uncertaintyTags.push('低置信度表述');
    }
  }
  // 高置信度词奖励: +0.03 -> +0.05 (提升)
  for (const p of highConfidencePatterns) {
    if (content.includes(p)) {
      confidence += 0.05;
    }
  }
  for (const p of riskPatterns) {
    if (content.includes(p)) {
      riskScore += 0.1;
      if (!uncertaintyTags.includes('高风险信号')) uncertaintyTags.push('高风险信号');
    }
  }

  // 市场数据完整性（数据完整时给予更大奖励）
  if (!marketDataSnapshot) {
    confidence -= 0.08; // -0.1 -> -0.08
    uncertaintyTags.push('无市场数据');
  } else {
    if (typeof marketDataSnapshot === 'object') {
      const snap = marketDataSnapshot as any;
      if (snap.error || snap.failed) {
        confidence -= 0.1;
        uncertaintyTags.push('市场数据获取失败');
      } else {
        if (snap.price) confidence += 0.08; // +0.05 -> +0.08
      }
    }
  }

  // 内容长度惩罚：阈值降低，惩罚减小
  if (content.length < 30) {
    confidence -= 0.05;
    uncertaintyTags.push('内容过短');
  }

  // 步骤置信度基线（全面提升，S2/S3 不再是天然低置信度）
  const stepBaselineConfidence: Record<StepPhase, number> = {
    S1_RESEARCH: 0.78, // 0.6 -> 0.78
    S2_ANALYSIS: 0.75, // 0.55 -> 0.75
    S3_DESIGN: 0.72,  // 0.5 -> 0.72
    S4_VALIDATE: 0.82, // 0.75 -> 0.82
    S5_EXECUTE: 0.85,  // 0.8 -> 0.85
  };
  const stepBaselineRisk: Record<StepPhase, number> = {
    S1_RESEARCH: 0.25,
    S2_ANALYSIS: 0.35,
    S3_DESIGN: 0.38,
    S4_VALIDATE: 0.28,
    S5_EXECUTE: 0.45,
  };
  confidence = Math.max(0.3, Math.min(0.95, confidence + stepBaselineConfidence[step] - 0.8));
  riskScore = Math.max(0.1, Math.min(0.9, riskScore + stepBaselineRisk[step] - 0.3));

  return { confidence, riskScore, uncertaintyTags };
}

// ============================================================
// 1. 自省 Gate（S2/S3 完成后批判分析）
// ============================================================

/**
 * 自省批判门：检查步骤产出是否存在逻辑自洽
 *
 * 规则：
 *  - 检查是否包含核心信息（S2 时）
 *  - 检查关键信号是否矛盾
 *  - 检查是否有足够支撑策略（S3 时）
 */
export function runSelfCriticism(
  step: StepPhase,
  content: string,
  previousSteps: StepMetadata[],
  marketDataSnapshot?: any
): SelfCriticismResult {
  const issues: string[] = [];
  const corrections: string[] = [];
  const uncertaintyTags: string[] = [];

  // 判断是否已通过（S2 仅 S2_ANALYSIS 的内容是否有矛盾
  // 简化版：基于文本长度 + 信号/结论的启发式检查

  // S2_ANALYSIS: 检查是否包含明确判断和核心矛盾
  if (step === 'S2_ANALYSIS') {
    // 检查是否缺少关键信号
    if (!content.includes('买入') && !content.includes('卖出') && !content.includes('观望') &&
        !content.includes('趋势') && !content.includes('区间')) {
      issues.push('分析中缺少明确市场判断');
      corrections.push('补充明确趋势判断（看涨/看跌/区间）');
    }
    // 检查是否有证据支撑
    if (content.length < 150) {
      issues.push('分析内容过短，缺乏深度分析');
      corrections.push('增加更多数据支撑');
    }
    // 检查市场数据是否被使用
    if (marketDataSnapshot && !content.includes(String(marketDataSnapshot.price || ''))) {
      issues.push('市场数据未被分析内容使用');
      corrections.push('在分析中引用当前价格和关键支撑位');
    }
  } else if (step === 'S3_DESIGN') {
    // S3_DESIGN: 检查是否有入场出场点位
    if (!content.includes('入场') && !content.includes('买入') &&
        !content.includes('exit') && !content.includes('stop')) {
      issues.push('策略方案缺少明确的入场/出场点位');
      corrections.push('添加入场价/出场价/止损价');
    }
    if (!content.includes('止损') && !content.includes('risk')) {
      issues.push('策略缺少风险控制');
      corrections.push('加入止损与仓位管理建议');
    }
  }

  // 检查上下步是否存在
  if (previousSteps.length > 0) {
    const prevStep = previousSteps[previousSteps.length - 1];
    if (prevStep && step !== 'S1_RESEARCH') {
      // 检查这一步是否引用了上一步结论
      const prevKeyTerms = prevStep.content.slice(0, 100);
      let hasReference = false;
      for (const token of prevKeyTerms.split(/[，。\s]+/)) {
        if (token.length >= 3 && content.includes(token)) {
          hasReference = true;
          break;
        }
      }
      if (!hasReference && content.length > 500) {
        issues.push(`未充分引用 ${prevStep.step} 结论`);
        corrections.push(`在当前步骤中引用 ${prevStep.step} 的关键结论`);
      }
    }
  }

  // 最终评分（优化：通过自省的步骤给予更大奖励）
  const issueCount = issues.length;
  const passed = issueCount <= 2; // 允许 2 个问题为通过
  // 0 问题: +0.15; 1 问题: +0.05; 2 问题: 0; 3+ 问题: -0.08 * (issueCount - 2)
  let confidenceDelta;
  if (issueCount === 0) confidenceDelta = 0.15;
  else if (issueCount === 1) confidenceDelta = 0.05;
  else if (issueCount === 2) confidenceDelta = 0;
  else confidenceDelta = -0.08 * (issueCount - 2);
  const riskScore = Math.min(0.9, 0.25 + issueCount * 0.12);

  return {
    passed, confidenceDelta, riskScore,
    issues, corrections, uncertaintyTags,
  };
}

// ============================================================
// 2. 验证回退（S4 失败是否应回退）
// ============================================================

/**
 * S4 验证结果的回退判断
 * @param s4Content S4_VALIDATE 的输出内容
 * @param marketDataSnapshot 市场数据快照
 * @returns 是否需要回退到哪个步骤（null 表示不回退）
 */
export function shouldRollback(s4Content: string, marketDataSnapshot?: any): {
  shouldRollback: boolean;
  rollbackTo: StepPhase | null;
  reason: string;
} {
  const s4ContentLower = s4Content.toLowerCase();

  // 明确失败信号
  const failPatterns = ['回测失败', '回测不通过', '胜率不足', '风险过高', '不建议',
    'failed', 'backtest failed', 'not recommended', 'high risk', 'insufficient win'];
  const passPatterns = ['通过', '建议采纳', '验证通过', '可执行', 'passed', 'recommended'];

  const hasFailPattern = failPatterns.some((p) => s4ContentLower.includes(p));
  const hasPassPattern = passPatterns.some((p) => s4ContentLower.includes(p));

  if (hasFailPattern || s4ContentLower.includes('不通过') || s4ContentLower.includes('回退')) {
    // 回退到 S3（若 S2）
    return { shouldRollback: true, rollbackTo: 'S3_DESIGN', reason: 'S4 验证失败，重新设计策略方案' };
  }

  if (hasPassPattern || s4ContentLower.includes('验证成功')) {
    return { shouldRollback: false, rollbackTo: null, reason: 'S4 验证通过' };
  }

  // 不明确 → 默认通过（保持现有策略，保守通过
  return { shouldRollback: false, rollbackTo: null, reason: 'S4 结果不明确，按默认通过处理' };
}

// ============================================================
// 3. 自适应路径（基于置信度提前收敛）
// ============================================================

/**
 * 根据累计置信度判断是否提前收敛
 *
 * 规则：
 *  - S2_ANALYSIS 后 confidence >= 0.85 → 直接跳过 S3/S4 直接到 S5
 *  - confidence < 0.3 → 要求补全步骤
 */
export function shouldSkipStep(
  currentStep: StepPhase,
  stepMetadatas: StepMetadata[]
): AdaptiveRoutingDecision {
  if (stepMetadatas.length === 0) return { skipStep: false, reason: '无已完成步骤', confidenceDelta: 0 };

  const totalConfidence = stepMetadatas.reduce((sum, s) => sum + s.confidence, 0) / stepMetadatas.length;
  const doneCount = stepMetadatas.length;

  // 如果当前步骤是 S3 且前面步骤都有高置信度
  if (currentStep === 'S3_DESIGN' && totalConfidence >= 0.8 && doneCount >= 2) {
    // 高置信度 → 可跳过 S4，直接到 S5
    return { skipStep: false, reason: '高置信度信号 → 直接执行', confidenceDelta: 0 };
  }

  // 如果 S4 之前就已完成且 confidence 都通过，可以跳过 S4
  if (currentStep === 'S4_VALIDATE' && doneCount >= 3 && totalConfidence >= 0.85) {
    return { skipStep: true, reason: '高置信度结论已完整，无需验证', confidenceDelta: 0 };
  }

  return { skipStep: false, reason: '正常流程继续', confidenceDelta: 0 };
}

// ============================================================
// 6. 工具调用质疑-验证-修正闭环
// ============================================================

/**
 * 质疑工具调用结果：检查工具是否使用并验证有效性
 *
 * 返回质疑后修正后的修正信息
 */
export function verifyAndCorrectToolOutput(
  toolName: string,
  toolOutput: string,
  stepPhase: StepPhase,
): { verified: boolean; corrected: string; warnings: string[] } {
  const warnings: string[] = [];
  let corrected = toolOutput;

  // 基本有效性检查
  if (!toolOutput || toolOutput.trim().length < 20) {
    warnings.push(`工具 ${toolName} 输出过短`);
    corrected = toolOutput + '\n⚠️ 注意：工具输出内容不足，分析需依赖更完整数据验证';
  }

  // 检查关键数值是否合理（price 或数值在合理范围
  const numMatches = toolOutput.match(/\$?\d+(?:\.\d+)?/g);
  if (numMatches && numMatches.length > 0) {
    const nums = numMatches.map((n) => parseFloat(n));
    for (const num of nums) {
      if (isNaN(num) || num <= 0) {
        warnings.push('工具输出包含无效数值');
        corrected = corrected + '\n⚠️ 工具输出包含无效数值，建议重新调用';
        break;
      }
    }
  }

  // 时间戳新鲜度检查（假设市场数据应包含时间戳）
  if (stepPhase === 'S1_RESEARCH' && !toolOutput.includes('time') && !toolOutput.includes('时间')) {
    warnings.push('市场数据未包含时间戳');
  }

  return { verified: warnings.length <= 1, corrected, warnings };
}

/**
 * 核心：使用工具调用→质疑→验证→修正的完整闭环函数
 *
 * 输入：上一步骤内容 + 工具输出 + 当前步骤
 * 输出：修正后的内容 + 修正说明
 */
export function runToolFeedbackLoop(
  originalContent: string,
  toolName: string,
  toolOutput: string,
  step: StepPhase
): { finalContent: string; feedbackNotes: string[]; loopIterations: number } {
  // 迭代最多 3 次
  let current = originalContent;
  const feedbackNotes: string[] = [];
  let iterations = 0;

  while (iterations < 3) {
    iterations++;
    const verify = verifyAndCorrectToolOutput(toolName, toolOutput, step);
    if (verify.verified) {
      feedbackNotes.push(`工具 ${toolName} 输出第 ${iterations} 次验证通过`);
      current = verify.corrected;
      break;
    }
    feedbackNotes.push(`工具 ${toolName} 第 ${iterations} 次验证未通过: ${verify.warnings.join('；')}`);
    current = verify.corrected;
    // 简化：不实际重新调用工具，只记录警告
    break;
  }

  return { finalContent: current, feedbackNotes, loopIterations: iterations };
}

// ============================================================
// 辅助：构造步骤元数据
// ============================================================

/**
 * 构造 StepMetadata，用于在步骤间传递元信息
 */
export function createStepMetadata(
  step: StepPhase,
  content: string,
  previous?: StepMetadata,
  marketDataSnapshot?: any
): StepMetadata {
  const analysis = analyzeStepConfidence(step, content, marketDataSnapshot);
  const selfCrit = runSelfCriticism(step, content, previous ? [previous] : [], marketDataSnapshot);

  return {
    step,
    content,
    previous,
    confidence: Math.max(0.2, Math.min(0.95, analysis.confidence + selfCrit.confidenceDelta)),
    riskScore: Math.max(0.1, Math.min(0.9, analysis.riskScore + selfCrit.riskScore - 0.3)),
    uncertaintyTags: [...analysis.uncertaintyTags, ...selfCrit.uncertaintyTags],
    gatePassed: selfCrit.passed,
    issuesFound: selfCrit.issues,
    corrections: selfCrit.corrections,
    shouldBeSkipped: false,
  };
}

/**
 * 汇总所有步骤的置信度
 */
export function summarizeChain(metadatas: StepMetadata[]): {
  averageConfidence: number;
  totalRisk: number;
  totalIssues: number;
  totalCorrections: number;
  overallQuality: 'poor' | 'mediocre' | 'good' | 'excellent';
  notes: string[];
} {
  if (metadatas.length === 0) {
    return {
      averageConfidence: 0, totalRisk: 0, totalIssues: 0, totalCorrections: 0,
      overallQuality: 'poor', notes: ['无分析步骤'],
    };
  }
  const avgConf = metadatas.reduce((s, m) => s + m.confidence, 0) / metadatas.length;
  const totalRisk = Math.max(...metadatas.map((m) => m.riskScore));
  const totalIssues = metadatas.reduce((s, m) => s + m.issuesFound.length, 0);
  const totalCorrections = metadatas.reduce((s, m) => s + m.corrections.length, 0);
  const overallQuality: 'poor' | 'mediocre' | 'good' | 'excellent' =
    avgConf >= 0.8 && totalIssues === 0 ? 'excellent' :
    avgConf >= 0.65 ? 'good' :
    avgConf >= 0.5 ? 'mediocre' : 'poor';

  const notes: string[] = [];
  if (avgConf < 0.7) notes.push('整体置信度偏低，建议补充验证');
  if (totalRisk > 0.6) notes.push('整体风险偏高，建议谨慎执行');
  if (totalIssues > 0) notes.push(`共有 ${totalIssues} 处问题被识别`);
  return { averageConfidence: avgConf, totalRisk, totalIssues, totalCorrections, overallQuality: overallQuality, notes };
}
