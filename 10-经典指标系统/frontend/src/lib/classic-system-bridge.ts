/**
 * Classic System Bridge - 策略输出转换器
 *
 * 将 Dreambuddy-v2 S思维链（S1-S5）输出转换为
 * classic-indicators-ml-system 可理解的治理接口格式
 *
 * 流程:
 *   S1_调研 → S2_分析 → S3_设计 → S4_验证 → S5_执行
 *                                                ↓
 *              Classic System: Draft → Gate → Approval → Apply → Audit
 */

// S系列步骤输出格式定义
export interface S1ResearchOutput {
  symbol: string;
  displayName: string;
  price: number;
  priceChange24h: number;
  support: string;
  resistance: string;
  indicators: {
    rsi: number;
    macd: { value: number; signal: number; histogram: number };
    trend: "bullish" | "bearish" | "neutral";
  };
  sentiment?: {
    fearGreedIndex?: number;
    fundingRate?: number;
  };
  summary: string;
}

export interface S2AnalysisOutput {
  trend: {
    shortTerm: "bullish" | "bearish" | "neutral";
    mediumTerm: "bullish" | "bearish" | "neutral";
    longTerm: "bullish" | "bearish" | "neutral";
  };
  keyLevels: {
    entryRange: string;
    stopLoss: string;
    takeProfit: string;
  };
  risks: string[];
  confidence: number;
  conclusion: string;
}

export interface S3DesignOutput {
  strategyName: string;
  entryPlan: {
    entryPoint: string;
    positionSize: number;
    addRules?: string;
  };
  riskManagement: {
    stopLoss: string;
    takeProfit: string;
    riskRewardRatio: string;
  };
  scenarios: Array<{
    scenario: string;
    probability: number;
    outcome: string;
  }>;
  confidence: number;
}

export interface S4ValidateOutput {
  backtest: {
    period: string;
    winRate: number;
    profitFactor: number;
    maxDrawdown: number;
    sharpeRatio: number;
  };
  riskAssessment: {
    var95: number;
    maxDailyLoss: number;
    consecutiveLosses: number;
  };
  verdict: string;
  recommend: boolean;
}

export interface S5ExecuteOutput {
  checklist: string[];
  alerts: Array<{ price: string; action: string }>;
  warnings: string[];
  trackingPlan: string;
}

/**
 * 完整策略链输入
 */
export interface CompleteStrategyChain {
  scope: string;
  sessionId?: string;
  traceId?: string;
  s1?: S1ResearchOutput;
  s2?: S2AnalysisOutput;
  s3?: S3DesignOutput;
  s4?: S4ValidateOutput;
  s5?: S5ExecuteOutput;
  summary?: string;
}

/**
 * classic-system 策略注入草案格式
 */
export interface ClassicDraftPayload {
  strategy_name: string;
  trace_id: string;
  candidate: {
    scope: string;
    session_id?: string;
    symbol?: string;
    display_name?: string;
  };
  changeset: {
    reason: string;
    description: string;
    version: string;
    param_overrides: Record<string, any>;
  };
  doc_refs: Array<{ doc_path: string; section: string; rule: string }>;
  evidence: Array<Record<string, any>>;
  gate_result: {
    checks: Record<string, boolean>;
    metrics: Record<string, number>;
    risks: string[];
    pass: boolean;
    warnings: string[];
    timestamp: number;
  };
}

/**
 * 生成标准化策略名称
 */
export function generateStrategyName(chain: CompleteStrategyChain): string {
  const scope = (chain.scope || "GENERAL").toUpperCase().replace(/[^A-Z0-9]/g, "_");
  const dir = chain.s2?.trend?.shortTerm?.toUpperCase() || "NEUTRAL";
  const stamp = Date.now().toString(36).slice(-4);
  return `${scope}_Trend_${dir}_v${stamp}`;
}

/**
 * 生成策略变更描述
 */
export function generateChangesetDescription(chain: CompleteStrategyChain): string {
  const parts: string[] = [];
  if (chain.s1) parts.push(`调研: ${chain.s1.symbol} @ ${chain.s1.price}`);
  if (chain.s2) parts.push(`分析: 置信度${chain.s2.confidence}%`);
  if (chain.s3) parts.push(`设计: RR=${chain.s3.riskManagement.riskRewardRatio}`);
  if (chain.s4) parts.push(`验证: 胜率${chain.s4.backtest.winRate}%`);
  return parts.join("; ");
}

/**
 * 生成变更理由
 */
export function generateReason(chain: CompleteStrategyChain): string {
  const reasons: string[] = [];
  if (chain.s1) reasons.push(`基于${chain.s1.displayName || chain.scope}行情分析`);
  if (chain.s2) reasons.push(`趋势${chain.s2.trend.shortTerm}, 置信${chain.s2.confidence}%`);
  if (chain.s4) reasons.push(`回测胜率${chain.s4.backtest.winRate}%`);
  return reasons.join("；") || "Dreambuddy策略研究输出";
}

/**
 * 从策略链生成参数覆盖配置
 */
export function generateParamOverrides(chain: CompleteStrategyChain): Record<string, any> {
  const overrides: Record<string, any> = {};
  const s3 = chain.s3;
  if (!s3) return overrides;

  if (s3.entryPlan) {
    overrides.entry_point = s3.entryPlan.entryPoint;
    overrides.position_size = s3.entryPlan.positionSize;
  }
  if (s3.riskManagement) {
    overrides.stop_loss = s3.riskManagement.stopLoss;
    overrides.take_profit = s3.riskManagement.takeProfit;
    overrides.risk_reward_ratio = s3.riskManagement.riskRewardRatio;
  }
  if (s3.scenarios && s3.scenarios.length > 0) {
    overrides.scenarios = s3.scenarios;
  }
  if (chain.s2) {
    overrides.trend_short = chain.s2.trend.shortTerm;
    overrides.trend_medium = chain.s2.trend.mediumTerm;
    overrides.trend_long = chain.s2.trend.longTerm;
    overrides.trend_confidence = chain.s2.confidence;
    overrides.key_levels = chain.s2.keyLevels;
    overrides.risks = chain.s2.risks;
  }
  if (chain.s4) {
    overrides.backtest = chain.s4.backtest;
    overrides.risk_assessment = chain.s4.riskAssessment;
    overrides.recommend = chain.s4.recommend;
  }
  return overrides;
}

/**
 * 生成文档引用（审计溯源）
 */
export function generateDocRefs(chain: CompleteStrategyChain): Array<{
  doc_path: string;
  section: string;
  rule: string;
}> {
  const refs: Array<{ doc_path: string; section: string; rule: string }> = [];
  if (chain.s1) {
    refs.push({
      doc_path: `${chain.s1.displayName || chain.scope}_Research.md`,
      section: "Technical Analysis",
      rule: `RSI=${chain.s1.indicators.rsi}, MACD=${chain.s1.indicators.macd.value}`,
    });
  }
  if (chain.s2) {
    refs.push({
      doc_path: `${chain.scope}_Trend_Analysis.md`,
      section: "Trend Assessment",
      rule: `Short:${chain.s2.trend.shortTerm}, Med:${chain.s2.trend.mediumTerm}`,
    });
  }
  if (chain.s3) {
    refs.push({
      doc_path: `${generateStrategyName(chain)}_Design.md`,
      section: "Risk Management",
      rule: `RR=${chain.s3.riskManagement.riskRewardRatio}`,
    });
  }
  if (chain.s4) {
    refs.push({
      doc_path: `${chain.scope}_Validation.md`,
      section: "Backtest Results",
      rule: `WinRate=${chain.s4.backtest.winRate}%, Sharpe=${chain.s4.backtest.sharpeRatio}`,
    });
  }
  return refs;
}

/**
 * 生成决策证据链
 */
export function generateEvidence(chain: CompleteStrategyChain): Array<Record<string, any>> {
  const evidence: Array<Record<string, any>> = [];
  if (chain.s1) {
    evidence.push({
      type: "metric", source: "live_metrics",
      excerpt: `Price=${chain.s1.price}, RSI=${chain.s1.indicators.rsi}`,
    });
  }
  if (chain.s1?.sentiment) {
    evidence.push({
      type: "sentiment", source: "market_sentiment",
      excerpt: `FGI=${chain.s1.sentiment.fearGreedIndex ?? "N/A"}`,
    });
  }
  if (chain.s2) {
    evidence.push({
      type: "analysis", source: "trend_assessment",
      excerpt: `Trend: Short=${chain.s2.trend.shortTerm}, Med=${chain.s2.trend.mediumTerm}`,
    });
  }
  if (chain.s4) {
    evidence.push({
      type: "backtest", source: "historical_simulation",
      excerpt: `WinRate=${chain.s4.backtest.winRate}%, Sharpe=${chain.s4.backtest.sharpeRatio}`,
    });
  }
  return evidence;
}

/**
 * 生成 Gate 检查结果（策略链自评估）
 */
export function generateGateResult(chain: CompleteStrategyChain): {
  checks: Record<string, boolean>;
  metrics: Record<string, number>;
  risks: string[];
  pass: boolean;
  warnings: string[];
  timestamp: number;
} {
  const risks: string[] = [];
  const checks: Record<string, boolean> = {};
  const metrics: Record<string, number> = {};

  if (chain.s2) {
    const { shortTerm, mediumTerm, longTerm } = chain.s2.trend;
    const allAgree = shortTerm === mediumTerm && mediumTerm === longTerm;
    checks.trend_consistency = allAgree;
    if (!allAgree) risks.push("多周期趋势不一致");
  }
  if (chain.s3?.riskManagement?.riskRewardRatio) {
    const rrMatch = String(chain.s3.riskManagement.riskRewardRatio).match(/\d+(?:\.\d+)?/);
    if (rrMatch) {
      const rr = parseFloat(rrMatch[0]);
      checks.min_risk_reward = rr >= 1.5;
      metrics.risk_reward_ratio = rr;
      if (rr < 1.5) risks.push("风险收益比低于1.5");
    }
  }
  if (chain.s4) {
    checks.backtest_pass = chain.s4.recommend;
    metrics.win_rate = chain.s4.backtest.winRate;
    metrics.sharpe_ratio = chain.s4.backtest.sharpeRatio;
    metrics.max_drawdown = chain.s4.backtest.maxDrawdown;
    if (!chain.s4.recommend) risks.push("回测验证未通过");
  }
  if (chain.s2?.confidence !== undefined) {
    checks.confidence_threshold = chain.s2.confidence >= 60;
    metrics.confidence = chain.s2.confidence;
    if (chain.s2.confidence < 60) risks.push("分析置信度低于60%");
  }

  return {
    checks, metrics, risks,
    pass: risks.length === 0,
    warnings: risks.length > 0 ? [`共发现${risks.length}项风险，需人工复核`] : [],
    timestamp: Date.now(),
  };
}

/**
 * 主转换函数：将完整策略链转换为 classic-system Draft 格式
 */
export function transformToClassicDraft(chain: CompleteStrategyChain): ClassicDraftPayload {
  const strategyName = chain.s3?.strategyName || generateStrategyName(chain);
  const traceId = chain.traceId || `dream-${Date.now().toString(36)}`;

  return {
    strategy_name: strategyName,
    trace_id: traceId,
    candidate: {
      scope: chain.scope,
      session_id: chain.sessionId,
      symbol: chain.s1?.symbol,
      display_name: chain.s1?.displayName,
    },
    changeset: {
      reason: generateReason(chain),
      description: generateChangesetDescription(chain),
      version: `v1.0-${Date.now().toString(36)}`,
      param_overrides: generateParamOverrides(chain),
    },
    doc_refs: generateDocRefs(chain),
    evidence: generateEvidence(chain),
    gate_result: generateGateResult(chain),
  };
}

/**
 * 生成回测运行配置
 */
export function generateBacktestConfig(chain: CompleteStrategyChain): {
  config: string;
  strategy: string;
  strategy_name: string;
  timeout_sec: number;
  trace_id: string;
  env: Record<string, string>;
} {
  const strategyName = chain.s3?.strategyName || generateStrategyName(chain);
  return {
    config: "user_data/config_local_backtest.json",
    strategy: strategyName,
    strategy_name: strategyName,
    timeout_sec: 1800,
    trace_id: chain.traceId || `dream-${Date.now().toString(36)}`,
    env: {
      STRATEGY_SCOPE: chain.scope,
      STRATEGY_NAME: strategyName,
      CONFIDENCE: String(chain.s2?.confidence || 75),
    },
  };
}
