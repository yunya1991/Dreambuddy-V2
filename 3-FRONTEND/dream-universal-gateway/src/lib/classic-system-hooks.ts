/**
 * Dreambuddy-v2 → Classic System 集成钩子
 * 
 * 功能：
 * 1. S5 Execute 钩子：策略完成后自动推送到 classic-system 治理流程
 * 2. S1/S2 知识库查询：在研究阶段获取经典系统已有策略作为参考
 * 3. 监控数据：获取审批/回滚状态用于监控界面
 */

const CLASSIC_BASE = process.env.NEXT_PUBLIC_CLASSIC_SYSTEM_URL || "http://127.0.0.1:8092";

async function classicRequest<T = any>(endpoint: string, options: RequestInit = {}): Promise<T> {
  try {
    const response = await fetch(`${CLASSIC_BASE}${endpoint}`, {
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
    return await response.json();
  } catch (error) {
    console.error(`[ClassicHook] Request failed: ${endpoint}`, error);
    return { ok: false, error: error instanceof Error ? error.message : "request_failed" } as T;
  }
}

export interface ClassicResponse<T = any> {
  ok: boolean;
  ts?: number;
  error?: string;
  data?: T;
  [key: string]: any;
}

export interface PipelineState {
  phase: string;
  success: boolean;
  message: string;
  data?: any;
  timestamp: number;
}

export interface PipelineResult {
  success: boolean;
  strategyName: string;
  traceId: string;
  changesetId?: string;
  approvalId?: string;
  steps: PipelineState[];
  error?: string;
}

// S步骤输出类型
export interface S1ResearchOutput {
  symbol: string;
  displayName: string;
  price: number;
  priceChange24h: number;
  support: string;
  resistance: string;
  indicators: { rsi: number; macd: { value: number; signal: number; histogram: number }; trend: string };
  sentiment?: { fearGreedIndex?: number; fundingRate?: number };
  summary: string;
}

export interface S2AnalysisOutput {
  trend: { shortTerm: string; mediumTerm: string; longTerm: string };
  keyLevels: { entryRange: string; stopLoss: string; takeProfit: string };
  risks: string[];
  confidence: number;
  conclusion: string;
}

export interface S3DesignOutput {
  strategyName: string;
  entryPlan: { entryPoint: string; positionSize: number };
  riskManagement: { stopLoss: string; takeProfit: string; riskRewardRatio: string };
  scenarios: Array<{ scenario: string; probability: number; outcome: string }>;
  confidence: number;
}

export interface S4ValidateOutput {
  backtest: { period: string; winRate: number; profitFactor: number; maxDrawdown: number; sharpeRatio: number };
  riskAssessment: { var95: number; maxDailyLoss: number; consecutiveLosses: number };
  verdict: string;
  recommend: boolean;
}

export interface CompleteStrategyChain {
  scope: string;
  sessionId?: string;
  traceId?: string;
  s1?: S1ResearchOutput;
  s2?: S2AnalysisOutput;
  s3?: S3DesignOutput;
  s4?: S4ValidateOutput;
  summary?: string;
}

// 转换函数
function generateStrategyName(chain: CompleteStrategyChain): string {
  const scope = (chain.scope || "GENERAL").toUpperCase().replace(/[^A-Z0-9]/g, "_");
  const dir = chain.s2?.trend?.shortTerm?.toUpperCase() || "NEUTRAL";
  const stamp = Date.now().toString(36).slice(-4);
  return `${scope}_Trend_${dir}_v${stamp}`;
}

function transformToClassicDraft(chain: CompleteStrategyChain) {
  const strategyName = chain.s3?.strategyName || generateStrategyName(chain);
  const traceId = chain.traceId || `dream-${Date.now().toString(36)}`;
  const risks: string[] = [];
  const checks: Record<string, boolean> = {};

  if (chain.s2) {
    const { shortTerm, mediumTerm, longTerm } = chain.s2.trend;
    checks.trend_consistency = shortTerm === mediumTerm && mediumTerm === longTerm;
    if (!checks.trend_consistency) risks.push("多周期趋势不一致");
  }
  if (chain.s4) {
    checks.backtest_pass = chain.s4.recommend;
    if (!chain.s4.recommend) risks.push("回测验证未通过");
  }
  if (chain.s2?.confidence !== undefined) {
    checks.confidence_threshold = chain.s2.confidence >= 60;
    if (chain.s2.confidence < 60) risks.push("分析置信度低于60%");
  }

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
      reason: chain.s1 ? `基于${chain.s1.displayName || chain.scope}行情分析` : "Dreambuddy策略研究输出",
      description: `调研: ${chain.s1?.symbol || chain.scope}, 置信度${chain.s2?.confidence || 0}%`,
      version: `v1.0-${Date.now().toString(36)}`,
      param_overrides: chain.s2?.keyLevels || {},
    },
    doc_refs: chain.s1 ? [{
      doc_path: `${chain.s1.displayName || chain.scope}_Research.md`,
      section: "Technical Analysis",
      rule: `RSI=${chain.s1.indicators.rsi}`,
    }] : [],
    evidence: chain.s1 ? [{
      type: "metric", source: "live_metrics",
      excerpt: `Price=${chain.s1.price}, RSI=${chain.s1.indicators.rsi}`,
    }] : [],
    gate_result: {
      checks,
      metrics: { win_rate: chain.s4?.backtest.winRate || 0, confidence: chain.s2?.confidence || 0 },
      risks,
      pass: risks.length === 0,
      warnings: risks.length > 0 ? [`共发现${risks.length}项风险`] : [],
      timestamp: Date.now(),
    },
  };
}

/**
 * S5 Execute 完成后自动推送策略到 classic-system
 */
export async function onStrategyExecuteComplete(
  chain: CompleteStrategyChain,
  options: { onProgress?: (state: PipelineState) => void } = {}
): Promise<PipelineResult> {
  console.log(`[Hook/S5] 策略执行完成: ${chain.scope}`);
  const payload = transformToClassicDraft(chain);
  const steps: PipelineState[] = [];

  const notify = (state: PipelineState) => {
    steps.push(state);
    options.onProgress?.(state);
  };

  try {
    // 阶段1: Draft创建
    const draftResult = await classicRequest<ClassicResponse>("/agent/changeset/draft", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    notify({ phase: "draft", success: draftResult?.ok ?? false, message: draftResult?.ok ? `Draft已创建: ${payload.strategy_name}` : "Draft创建失败", timestamp: Date.now() });
    if (!draftResult?.ok) return { success: false, strategyName: payload.strategy_name, traceId: payload.trace_id, steps, error: "Draft创建失败" };

    // 阶段2: Gate评估
    const gateResult = await classicRequest<ClassicResponse>("/evaluation/gate/check", {
      method: "POST",
      body: JSON.stringify({ changeset_id: payload.trace_id, strategy_name: payload.strategy_name, gate_checks: payload.gate_result.checks, risks: payload.gate_result.risks }),
    });
    notify({ phase: "gate", success: gateResult?.ok ?? false, message: gateResult?.ok ? "Gate评估通过" : "Gate评估未通过", timestamp: Date.now() });

    // 阶段3: 审批请求
    const approvalResult = await classicRequest<ClassicResponse>("/agent/approvals/request", {
      method: "POST",
      body: JSON.stringify({ strategy_name: payload.strategy_name, changeset_id: payload.trace_id, request_type: "strategy_deployment", reason: payload.changeset.reason, gate_pass: gateResult?.ok ?? true }),
    });
    notify({ phase: "approval", success: approvalResult?.ok ?? false, message: approvalResult?.ok ? "审批请求已提交" : "审批请求提交失败", timestamp: Date.now() });

    // 阶段4: Apply变更
    const applyResult = await classicRequest<ClassicResponse>("/governance/changeset/apply", {
      method: "POST",
      body: JSON.stringify({ strategy_name: payload.strategy_name, changeset_id: payload.trace_id, mode: approvalResult?.ok ? "apply" : "dry_run" }),
    });
    notify({ phase: "apply", success: applyResult?.ok ?? false, message: applyResult?.ok ? "策略已应用" : "策略应用失败", timestamp: Date.now() });

    // 阶段5: 审计记录
    const auditResult = await classicRequest<ClassicResponse>("/agent/audit/record", {
      method: "POST",
      body: JSON.stringify({ strategy_name: payload.strategy_name, trace_id: payload.trace_id, action: "strategy_deployment", status: "success" }),
    });
    notify({ phase: "audit", success: auditResult?.ok ?? false, message: "审计记录完成", timestamp: Date.now() });

    console.log(`[Hook/S5] ✅ 策略推送完成: ${payload.strategy_name}`);
    return { success: steps.slice(0, -1).every(s => s.success), strategyName: payload.strategy_name, traceId: payload.trace_id, steps };
  } catch (error: any) {
    return { success: false, strategyName: payload.strategy_name, traceId: payload.trace_id, steps, error: error.message };
  }
}

/**
 * 查询策略库作为知识参考
 */
export async function queryStrategyKnowledge(scope: string): Promise<{ strategies: any[]; error?: string }> {
  try {
    const result = await classicRequest<ClassicResponse>(`/strategy/inject/list?scope=${encodeURIComponent(scope)}`);
    if (result?.ok && result?.strategies) return { strategies: result.strategies };
    return { strategies: [], error: result?.error || "查询失败" };
  } catch (error) {
    return { strategies: [], error: error instanceof Error ? error.message : "查询异常" };
  }
}

/**
 * 获取监控数据
 */
export async function fetchSystemMonitorData() {
  const [approvalsRes, rollbackRes, healthRes] = await Promise.allSettled([
    classicRequest<ClassicResponse>("/agent/approvals/list"),
    classicRequest<ClassicResponse>("/evaluation/rollback/list"),
    classicRequest<ClassicResponse>("/agent/api/health"),
  ]);
  return {
    approvals: approvalsRes.status === "fulfilled" ? approvalsRes.value?.approvals || [] : [],
    rollbackPoints: rollbackRes.status === "fulfilled" ? rollbackRes.value?.points || [] : [],
    health: healthRes.status === "fulfilled" ? healthRes.value : { ok: false },
  };
}