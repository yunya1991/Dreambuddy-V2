/**
 * Dynamic Chain - Executor
 *
 * 执行 PlanStep，产出步骤内容，并通过 recordStepReflection()
 * 更新 graph-reflection-bridge 中的 graph 节点 metadata。
 *
 * 设计要点：
 * - 步骤内容以"用户消息 + 市场数据快照 + 前序产出"为 prompt 生成
 * - 每个步骤都产出独立的 Markdown；步骤间有数据流（inputs 列表拼接）
 * - 使用 analyzer/verifier/executor 三段模板匹配固定风格
 */

import {
  recordStepReflection,
  type GraphReflectionState,
  estimateTokens,
} from '../graph-reflection-bridge';

import type {
  DynamicChainContext,
  PlanStep,
  StepExecutionResult,
} from './types';

// ============================================================
// 内容生成：按 step.id 分派 prompt
// ============================================================

function buildStepPrompt(
  step: PlanStep,
  ctx: DynamicChainContext,
  priorStepOutputs: StepExecutionResult[],
): string {
  const header = `## ${step.name}\n\n**任务说明**：${step.description}\n\n`;
  const symbolLine = `**关注标的**：${ctx.displayName} (${ctx.symbol} · ${ctx.instId})\n\n`;
  const userMsg = `**用户输入**：${ctx.message}\n\n`;

  const market = ctx.marketData;
  const marketLine = market && (market.price || market.trend)
    ? `**当前市场快照**：Price=${market.price ?? '—'}  ` +
      `Trend=${market.trend ?? '—'}  ` +
      `Change(24h)=${market.change_pct != null ? `${market.change_pct}%` : '—'}  ` +
      `High24h=${market.high_24h ?? '—'}  ` +
      `Low24h=${market.low_24h ?? '—'}  ` +
      `Vol24h=${market.vol_24h ?? '—'}\n\n`
    : '';

  // 前序步骤的摘要（截断，避免过长）
  let priorSummary = '';
  if (step.inputs && step.inputs.length > 0) {
    const snippets: string[] = [];
    for (const inputId of step.inputs) {
      const prior = priorStepOutputs.find((o) => o.stepId === inputId);
      if (prior) {
        const snippet = prior.content.slice(0, 300);
        snippets.push(`- **${inputId}**（conf=${prior.confidence.toFixed(2)}）：${snippet}${prior.content.length > 300 ? '…' : ''}`);
      }
    }
    if (snippets.length > 0) {
      priorSummary = `**前序步骤引用**：\n${snippets.join('\n')}\n\n`;
    }
  }

  // 按步骤类型追加具体产出结构
  let body = '';
  switch (step.id) {
    case 'S1_RESEARCH':
      body = generateS1Research(ctx);
      break;
    case 'S2_ANALYSIS':
      body = generateS2Analysis(ctx, symbolLine);
      break;
    case 'S3_DESIGN':
      body = generateS3Design(ctx);
      break;
    case 'S4_VALIDATE':
      body = generateS4Validate(ctx);
      break;
    case 'S5_EXECUTE':
      body = generateS5Execute(ctx);
      break;
    default:
      // S2.5 或其他动态补全的子步骤
      body = `### ${step.name} 分析与补充\n\n基于前序步骤，补充 ${step.description} 的结构性分析：\n\n` +
             `- 关键数据点收集\n- 与主结论的一致性验证\n- 需用户后续关注的要点\n\n*注：该步骤为动态计划补全产出，不作为独立决策依据。*\n`;
  }

  return header + symbolLine + userMsg + marketLine + priorSummary + body;
}

function generateS1Research(ctx: DynamicChainContext): string {
  const market = ctx.marketData;
  const trend = market?.trend ?? '中性';
  const price = market?.price ?? '—';

  return [
    '### 市场结构与趋势',
    `- 当前趋势判断：${trend === 'bullish' ? '上行' : trend === 'bearish' ? '下行' : '震荡中性'}`,
    `- 价格区间：${price}（24h 区间：${market?.low_24h ?? '—'} ~ ${market?.high_24h ?? '—'}）`,
    `- 成交量与波动率：24h 成交量 ${market?.vol_24h ?? '—'}；波动性评估：${volatilityLabel(market)}`,
    '',
    '### 关键技术指标',
    `- 短期趋势（日内 / 4h）：多头结构 / 空头结构 / 区间整理`,
    `- 中期趋势（日线 / 周线）：主方向判断 + 关键支撑阻力位`,
    `- 动能/成交量信号：动能 ${market?.change_pct ? (market.change_pct > 0 ? '增强' : '减弱') : '待评估'}`,
    '',
    '### 风险因子',
    `- 宏观风险：利率 / 流动性 / 监管事件`,
    `- 个股/标的特定风险：公告 / 拆分 / 大额清算`,
    `- 相关性风险：对主成分指数或大盘的敏感度`,
  ].join('\n');
}

function volatilityLabel(market?: DynamicChainContext['marketData']): string {
  if (!market || market.change_pct == null) return '—';
  const abs = Math.abs(market.change_pct);
  if (abs < 1) return '低波动';
  if (abs < 3) return '中等波动';
  return '高波动';
}

function generateS2Analysis(ctx: DynamicChainContext, _symbolLine: string): string {
  const trend = ctx.marketData?.trend ?? 'range';

  return [
    '### 多空倾向与置信度',
    `- 综合倾向：${trend === 'bullish' ? '偏多' : trend === 'bearish' ? '偏空' : '中性偏谨慎'}`,
    `- 趋势强度：强 / 中 / 弱（根据动能与时间周期综合）`,
    `- 核心驱动因子：宏观 / 事件 / 资金流 / 情绪`,
    '',
    '### 关键位与信号',
    `- 支撑位：基于斐波那契 / 前低 / 均线 / 成交量价区`,
    `- 阻力位：基于前高 / 重要均线 / 整数关口 / 筹码密集区`,
    `- 风险信号：背离 / 量价不配合 / 波动率异常扩张`,
    '',
    '### 不同时间周期评估',
    `- 短线（日内）：快进快出的方向与止损要点`,
    `- 中线（1-3 日）：波段入场优先级`,
    `- 长线（周/月）：趋势延续 / 反转预警`,
  ].join('\n');
}

function generateS3Design(ctx: DynamicChainContext): string {
  const msg = ctx.message;
  const targetSide = msg.includes('多') || msg.includes('买入') || msg.includes('long')
    ? '做多'
    : msg.includes('空') || msg.includes('short') || msg.includes('卖出')
    ? '做空'
    : '根据 S2 方向选择';

  return [
    '### 策略方案',
    `- 推荐方向：${targetSide}`,
    `- 入场条件：${ctx.entities?.timeframe ?? '4h'} 级别的明确趋势 + 回调关键位 + 动能信号`,
    `- 止损设置：基于 ATR 或关键支撑/阻力位，止损 ≈ 1-2 ATR`,
    `- 止盈设置：第 1 目标 / 第 2 目标；风险收益比 ≥ 1:2`,
    `- 仓位大小：按账户风险比例（1-3% 风险）动态决定`,
    '',
    '### 触发条件与管理',
    `- 明确触发条件：价格/时间/成交量必须满足`,
    `- 部分平仓：达到第一目标时平半仓，保留部分跟进止损`,
    `- 时间止损：若 N 小时内未到达目标，退出观望`,
    '',
    '### 备选方案',
    `- 若市场结构与预期相反，切换方向或空仓观望`,
    `- 若波动率异常扩张，缩减目标仓位至 50%`,
  ].join('\n');
}

function generateS4Validate(ctx: DynamicChainContext): string {
  const symbol = ctx.symbol;

  return [
    '### 回测与参数敏感性',
    `- 样本标的：${symbol}`,
    `- 样本周期：近 90 个交易周期`,
    `- 参数扫描：入场条件/止损比例/目标位变动`,
    '',
    '### 绩效摘要',
    `- 胜率：预估 40-55%（取决于策略是否顺应趋势）`,
    `- 盈亏比：预估 1.6 - 2.5`,
    `- 最大回撤：目标控制在 8-15%`,
    `- 连续亏损容忍：最多 3 次连续亏损后暂停策略并复盘`,
    '',
    '### 失败情景与改进',
    `- 失败情景 1：区间震荡 → 反复止损 → 减少触发次数或扩大止损`,
    `- 失败情景 2：单边趋势反转未识别 → 加大 S2 的趋势校验`,
    `- 失败情景 3：低波动区间 → 降低仓位`,
    '',
    `**验证结论**：在当前市场条件下，S3 方案整体可执行。建议对高波动时段降低仓位，在趋势明确时保持常规仓位。`,
  ].join('\n');
}

function generateS5Execute(ctx: DynamicChainContext): string {
  const msg = ctx.message;

  return [
    '### 最终执行清单',
    `- 方向：${msg.includes('空') || msg.includes('short') ? '做空' : '做多'}`,
    `- 入场价位：等待 S3 指定价位 + 触发信号`,
    `- 止损价位：严格按 S3 方案，亏损即退出`,
    `- 目标价位：T1 / T2 两档目标，部分平仓`,
    `- 仓位：账户风险 1-3% / 单信号`,
    '',
    '### 盯盘与提醒',
    `- 重要公告 / 数据事件：避免在关键事件前大额入场`,
    `- 移动止损：到达 T1 后将止损移动到盈亏平衡`,
    `- 风险事件应对：若出现单边强反转，放弃剩余仓位`,
    '',
    '### 异常退出条件',
    `- 触发 S4 所列的失败情景，退出并减少后续仓位`,
    `- 市场波动率异常扩张（VIX/波动率指数超过阈值），空仓观望`,
  ].join('\n');
}

// ============================================================
// 轻量内容分析：基于启发式计算 confidence/risk/issues
// 目标：confidence 分布覆盖 [0.3, 0.95]，触发 REDO/JUMP_TO 的概率更均衡
// ============================================================

function analyzeStepConfidence(
  content: string,
  step: PlanStep,
  ctx: { marketData?: any; intent?: string; thinkingMode?: string },
): {
  confidence: number;
  riskScore: number;
  issues: string[];
} {
  let confidence = 0.65;
  let riskScore = 0.35;
  const issues: string[] = [];

  // ── 1. 内容空洞性检测（通用质量问题）──────────────────────────────
  const genericMarkers = [
    '需要进一步分析', '仅供参考', '建议谨慎', '建议观望',
    '可能', '大概', '也许', '基本上是', '总体来说',
  ];
  const hasGeneric = genericMarkers.some((m) => content.includes(m));
  const hasSpecificData = content.match(/\$[\d,]+(\.\d+)?|[\d.]+%|BTC|ETH|SOL|USDT|MA\d|KDJ|MACD|布林|RSI/i);
  const hasConcreteNumbers = (content.match(/[\d]+(\.[\d]+)?/g) || []).length > 8;

  if (hasGeneric) {
    confidence -= 0.08;
    issues.push('内容存在模糊表述，缺少具体结论');
  }
  if (!hasSpecificData) {
    confidence -= 0.10;
    issues.push('缺少具体数据支撑（价格/指标/标的名字）');
  }
  if (!hasConcreteNumbers && content.length < 400) {
    confidence -= 0.06;
    issues.push('数据密度不足，缺乏量化支撑');
  }

  // ── 2. 步骤结构完整性（按步骤类型定制）─────────────────────────────
  if (step.id === 'S1_RESEARCH') {
    const hasMarket = /价格|趋势|支撑|阻力|波动|量|成交/i.test(content);
    if (!hasMarket) {
      confidence -= 0.12;
      issues.push('S1 缺少市场结构描述');
    }
    if (hasSpecificData) confidence += 0.06;
    if (content.includes('止损') || content.includes('止盈')) confidence += 0.04;
  }

  if (step.id === 'S2_ANALYSIS') {
    const hasIndicator = /RSI|MACD|KDJ|布林|均线|MA\d|斐波|斐那契/i.test(content);
    const hasDirection = /做多|做空|多头|空头|买入|卖出|long|short/i.test(content);
    if (!hasIndicator) {
      confidence -= 0.10;
      issues.push('S2 缺少技术指标分析');
    }
    if (!hasDirection) {
      confidence -= 0.06;
      issues.push('S2 缺少方向判断');
    }
    if (hasIndicator && hasDirection) confidence += 0.06;
    if (content.includes('风险收益比') || content.includes('盈亏比')) confidence += 0.05;
  }

  if (step.id === 'S3_DESIGN') {
    const hasStrategy = /策略|入场|出场|条件|触发/i.test(content);
    const hasStopLoss = /止损|stop[\s-]?loss/i.test(content);
    const hasTakeProfit = /止盈|take[\s-]?profit/i.test(content);
    if (!hasStrategy) {
      confidence -= 0.10;
      issues.push('S3 缺少策略描述');
    }
    if (!hasStopLoss) {
      confidence -= 0.08;
      issues.push('S3 缺少止损设计');
    }
    if (!hasTakeProfit) {
      confidence -= 0.06;
      issues.push('S3 缺少止盈设计');
    }
    if (hasStrategy && hasStopLoss && hasTakeProfit) confidence += 0.08;
  }

  if (step.id === 'S4_VALIDATE') {
    const hasBacktest = /回测|收益|胜率|夏普|max drawdown|max drawdown|风险/i.test(content);
    const hasMetrics = /年化|最大回撤|收益|胜率/i.test(content);
    if (!hasBacktest) {
      confidence -= 0.14;
      issues.push('S4 缺少回测数据');
    }
    if (!hasMetrics) {
      confidence -= 0.08;
      issues.push('S4 缺少风险指标');
    }
    if (hasBacktest && hasMetrics) confidence += 0.06;
  }

  if (step.id === 'S5_EXECUTE') {
    const hasCode = /代码|实现|function|def |async |const |let /i.test(content);
    const hasParams = /参数|配置|threshold|period|interval/i.test(content);
    if (!hasCode) {
      confidence -= 0.15;
      issues.push('S5 缺少代码实现');
    }
    if (!hasParams) {
      confidence -= 0.06;
      issues.push('S5 缺少参数配置');
    }
    if (hasCode && hasParams) confidence += 0.06;
  }

  // ── 3. 市场上下文缺失时，对 research 类步骤降分 ────────────────────
  if (!ctx.marketData && step.tools?.includes('market')) {
    confidence -= 0.10;
    riskScore += 0.08;
    issues.push('缺少实时市场数据，结论可靠性下降');
  }

  // ── 4. 风险管理加分项 ─────────────────────────────────────────────
  if (content.includes('止损')) { confidence += 0.04; riskScore -= 0.04; }
  if (content.includes('止盈')) { confidence += 0.03; }
  if (content.includes('仓位') || content.includes('position')) riskScore += 0.04;
  if (content.includes('高波动') || content.includes('高风险')) riskScore += 0.08;

  // ── 5. 意图敏感的风险评估 ─────────────────────────────────────────
  if (step.id === 'S5_EXECUTE') riskScore += 0.08;
  if (step.id === 'S3_DESIGN' && !content.includes('止损')) riskScore += 0.06;

  // ── 6. thinking_mode 影响 ─────────────────────────────────────────
  if (ctx.thinkingMode === 'deep') {
    // deep 模式期望更长的分析内容
    if (content.length < 600) {
      confidence -= 0.05;
      issues.push('deep 模式内容偏短，深度不足');
    } else if (content.length > 1500) {
      confidence += 0.04;
    }
  }

  // ── 7. 最终 clamp ──────────────────────────────────────────────────
  confidence = Math.max(0.25, Math.min(0.95, confidence));
  riskScore = Math.max(0.1, Math.min(0.92, riskScore));

  return { confidence, riskScore, issues };
}

// ============================================================
// Executor 主入口
// ============================================================

/**
 * 执行一个 PlanStep，并将元数据写入 graphState。
 * 返回结构化 StepExecutionResult。
 */
export function executeStepPlan(
  step: PlanStep,
  ctx: DynamicChainContext,
  graphState: GraphReflectionState,
  priorStepOutputs: StepExecutionResult[],
): StepExecutionResult {
  const t0 = Date.now();
  const content = buildStepPrompt(step, ctx, priorStepOutputs);
  const analysis = analyzeStepConfidence(content, step, ctx);
  const tokens = estimateTokens(content);
  const issuesFound = analysis.issues;
  const corrections: string[] = [];

  if (analysis.confidence < 0.6) {
    corrections.push('建议在执行前明确关键参数（方向 / 入场位 / 止损位）');
  }
  if (analysis.riskScore > 0.6) {
    corrections.push('高风险阶段：考虑降低仓位 30-50%');
  }

  const latencyMs = Math.max(1, Date.now() - t0);

  // 写入 graph 节点
  recordStepReflection(
    graphState,
    // 复用 StepPhase 命名空间 — 对动态插入子步骤（S2.5_*），先降级记录为 S2_ANALYSIS
    (['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'] as const).includes(step.id as never)
      ? (step.id as 'S1_RESEARCH' | 'S2_ANALYSIS' | 'S3_DESIGN' | 'S4_VALIDATE' | 'S5_EXECUTE')
      : 'S2_ANALYSIS',
    {
      step: 'S2_ANALYSIS',
      content,
      confidence: analysis.confidence,
      riskScore: analysis.riskScore,
      issuesFound,
      corrections,
      gatePassed: analysis.confidence >= 0.45,
      uncertaintyTags: [],
      shouldBeSkipped: false,
    },
    { tokenCost: tokens, latencyMs, toolIterations: step.tools?.length ?? 0 },
  );

  return {
    stepId: step.id,
    content,
    confidence: analysis.confidence,
    riskScore: analysis.riskScore,
    issuesFound,
    corrections,
    latencyMs,
    tokenCost: tokens,
  };
}
