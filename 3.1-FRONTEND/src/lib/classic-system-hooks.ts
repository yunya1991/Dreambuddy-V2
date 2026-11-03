/**
 * Dreambuddy-v2 → Classic System 集成钩子
 * 
 * 功能：
 * 1. S5 Execute 钩子：策略完成后自动推送到 classic-system 治理流程
 * 2. S1/S2 知识库查询：在研究阶段获取经典系统已有策略作为参考
 * 3. 监控数据：获取审批/回滚状态用于监控界面
 */

import { syncStrategyToClassic, type StrategySync } from "@/lib/classic-system-bridge";

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

  const strategyName = payload.strategy_name;
  const traceId = payload.trace_id;
  const symbol = String(payload.candidate.symbol || chain.scope || "BTC").toUpperCase();
  const shortTerm = chain.s2?.trend?.shortTerm || "";
  const direction = /涨|上行|bull|多|up/i.test(shortTerm)
    ? "long"
    : /跌|下行|bear|空|down/i.test(shortTerm)
      ? "short"
      : "neutral";
  const parsePct = (value?: string): number | null => {
    const matched = String(value || "").match(/(\d+(?:\.\d+)?)\s*%/);
    return matched ? Number(matched[1]) / 100 : null;
  };
  const rawPosition = chain.s3?.entryPlan?.positionSize;
  const syncPayload: StrategySync = {
    id: strategyName.replace(/[^A-Za-z0-9_-]/g, "_"),
    name: strategyName,
    description: payload.changeset.description,
    direction,
    symbol,
    tradeType: "spot",
    leverage: 1,
    positionSize: rawPosition === undefined ? undefined : rawPosition > 1 ? rawPosition / 100 : rawPosition,
    stopLoss: parsePct(chain.s3?.riskManagement?.stopLoss || chain.s2?.keyLevels?.stopLoss),
    takeProfit: parsePct(chain.s3?.riskManagement?.takeProfit || chain.s2?.keyLevels?.takeProfit),
    frequency: "1h",
  };

  try {
    // 统一走 M26 策略库 + M27 治理审批（Draft → Gate → Approval → Apply）
    const result = await syncStrategyToClassic(syncPayload);
    const stages = result.data?.stages;

    notify({
      phase: "draft",
      success: stages?.draft.ok ?? false,
      message: stages?.draft.message || (stages?.draft.ok ? "Draft已创建" : "Draft创建失败"),
      timestamp: Date.now(),
    });
    notify({
      phase: "gate",
      success: stages?.gate.ok ?? false,
      message: stages?.gate.message || (stages?.gate.ok ? "Gate评估通过" : "Gate评估未通过"),
      timestamp: Date.now(),
    });
    notify({
      phase: "approval",
      success: stages?.approval.ok ?? false,
      message: stages?.approval.message || (stages?.approval.ok ? "审批请求已提交" : "审批请求提交失败"),
      timestamp: Date.now(),
    });
    notify({
      phase: "apply",
      success: stages?.apply.ok ?? false,
      message: stages?.apply.message || (stages?.apply.ok ? "策略已应用" : "策略应用失败"),
      timestamp: Date.now(),
    });
    // M27 的 Gate/审批链路自动写入审计事件，此处不再单独调用 8092 审计接口
    notify({ phase: "audit", success: true, message: "审计事件已由 M27 治理链路自动记录", timestamp: Date.now() });

    const success =
      Boolean(result.ok) &&
      Boolean(stages) &&
      stages!.draft.ok &&
      stages!.gate.ok &&
      stages!.approval.ok &&
      stages!.apply.ok;

    console.log(`[Hook/S5] ${success ? "✅" : "⚠️"} 策略推送完成: ${strategyName}`);
    return {
      success,
      strategyName,
      traceId,
      changesetId: result.data?.changeset_id || result.data?.draft_id,
      approvalId: result.data?.approval_id,
      steps,
      error: success ? undefined : result.error || "治理链路未全部通过",
    };
  } catch (error: any) {
    return { success: false, strategyName, traceId, steps, error: error.message };
  }
}