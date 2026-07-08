/**
 * Dynamic Chain - Graph-aware Planner
 *
 * 规则引擎：读 graph-reflection-bridge.ts 的 GraphReflectionState
 * - architectureNodes 的 status/confidence/riskScore → 驱动 step 生成
 * - compressionSignal.highValueNodes / compressibleNodes → 驱动 INSERT/REDO
 *
 * 这是 Template-based 规则引擎（不是 LLM Planner），以确保 latency 可控。
 */

import {
  createGraphReflectionState,
  type GraphReflectionState,
} from '../graph-reflection-bridge';

import type {
  DynamicChainContext,
  DynamicChainIntent,
  DynamicPlan,
  PlanStep,
} from './types';

// ============================================================
// 模板：针对每种 intent 定义 base plan 模板
// ============================================================

interface PlanTemplate {
  intent: DynamicChainIntent;
  steps: Array<Omit<PlanStep, 'inputs'>>;
  description: string;
}

const TEMPLATES: Record<DynamicChainIntent, PlanTemplate> = {
  deep_analysis: {
    intent: 'deep_analysis',
    description: '深度市场分析：调研 → 数据分析 → 策略设计 → 快速验证（可选）',
    steps: [
      {
        id: 'S1_RESEARCH',
        name: 'S1 市场调研',
        description: '收集市场结构、主力资金、历史波动与关键技术指标，并给出当前市况摘要',
        estimatedMs: 15000,
        credits: 30,
        tools: ['market'],
      },
      {
        id: 'S2_ANALYSIS',
        name: 'S2 深度分析',
        description: '从趋势结构、关键位、动能、成交量、情绪信号等维度做综合评估，明确多空倾向与置信度',
        estimatedMs: 30000,
        credits: 50,
      },
      {
        id: 'S3_DESIGN',
        name: 'S3 策略设计',
        description: '根据 S2 结论设计具体入场/止损/止盈位、仓位大小、风险收益比、以及备选方案',
        estimatedMs: 45000,
        credits: 60,
        requiresConfirmation: true,
      },
      {
        id: 'S4_VALIDATE',
        name: 'S4 策略验证',
        description: '对 S3 设计方案做回测/参数压力测试，评估胜率、最大回撤、夏普比率等风险指标',
        estimatedMs: 60000,
        credits: 80,
        tools: ['backtest'],
      },
    ],
  },
  scenario_sim: {
    intent: 'scenario_sim',
    description: '情景模拟：调研 → 分析 → 设计 → 回测多情景',
    steps: [
      {
        id: 'S1_RESEARCH',
        name: 'S1 情景基线调研',
        description: '明确用户情景的假设条件（如"加息 25bp"、"BTC 突破 100k"），列出已知变量',
        estimatedMs: 15000,
        credits: 30,
      },
      {
        id: 'S2_ANALYSIS',
        name: 'S2 情景推演分析',
        description: '对用户假设场景做多路径推演，评估每条路径的概率、主要影响因素与风险点',
        estimatedMs: 35000,
        credits: 55,
      },
      {
        id: 'S3_DESIGN',
        name: 'S3 策略设计',
        description: '基于最可能的 1-2 条路径，设计对应的交易策略与仓位管理',
        estimatedMs: 45000,
        credits: 60,
        requiresConfirmation: true,
      },
      {
        id: 'S4_VALIDATE',
        name: 'S4 多情景回测',
        description: '在多种情景假设下运行策略回测，比较不同情景下的绩效差异与风险暴露',
        estimatedMs: 65000,
        credits: 85,
        tools: ['backtest'],
      },
    ],
  },
  strategy_verify: {
    intent: 'strategy_verify',
    description: '策略验证：跳过研究，直接从分析开始 → 设计 → 回测',
    steps: [
      {
        id: 'S2_ANALYSIS',
        name: 'S2 策略基础分析',
        description: '梳理用户给出策略的前提假设、信号规则、参数依赖，指出含糊或过度优化之处',
        estimatedMs: 25000,
        credits: 45,
      },
      {
        id: 'S3_DESIGN',
        name: 'S3 策略细化设计',
        description: '将用户策略转化为可执行规则：明确入场/离场/止损/仓位管理/最大开仓数',
        estimatedMs: 40000,
        credits: 60,
        requiresConfirmation: true,
      },
      {
        id: 'S4_VALIDATE',
        name: 'S4 策略回测与验证',
        description: '给出关键绩效指标（胜率/盈亏比/最大回撤/CAGR），并列出失败情景与改进方向',
        estimatedMs: 60000,
        credits: 80,
        tools: ['backtest'],
      },
    ],
  },
  execute_trade: {
    intent: 'execute_trade',
    description: '交易执行：调研 → 分析 → 设计 → 验证 → 执行清单',
    steps: [
      {
        id: 'S1_RESEARCH',
        name: 'S1 即时市场快照',
        description: '提供当前标的的价格、关键支撑/阻力位、24h 涨跌幅、成交量、最近 10 根 K 线结构',
        estimatedMs: 12000,
        credits: 25,
        tools: ['market'],
      },
      {
        id: 'S2_ANALYSIS',
        name: 'S2 趋势与风险评估',
        description: '判断趋势方向、风险级别（低/中/高），确定推荐方向与禁止方向',
        estimatedMs: 25000,
        credits: 45,
      },
      {
        id: 'S3_DESIGN',
        name: 'S3 交易方案',
        description: '明确入场价/止损价/目标价/仓位大小/触发条件/时间窗口/风险收益比',
        estimatedMs: 40000,
        credits: 60,
        requiresConfirmation: true,
      },
      {
        id: 'S4_VALIDATE',
        name: 'S4 参数压力测试',
        description: '对 S3 方案做简单压力测试：价格向不利方向移动时的亏损上限与应对预案',
        estimatedMs: 35000,
        credits: 50,
      },
      {
        id: 'S5_EXECUTE',
        name: 'S5 执行清单与提醒',
        description: '产出最终可执行清单：触发条件、委托单类型、注意事项、盯盘窗口、异常退出条件',
        estimatedMs: 15000,
        credits: 30,
      },
    ],
  },
};

// ============================================================
// 规则引擎：基于 graph 状态动态调整 plan
// ============================================================

/** 基于 graphState 动态生成 plan（第一次调用时 state 可能尚未初始化） */
export function generateInitialPlan(ctx: DynamicChainContext): DynamicPlan {
  const template = TEMPLATES[ctx.intent];
  const steps: PlanStep[] = template.steps.map((s, i) => ({
    ...s,
    inputs: i === 0 ? [] : [template.steps[i - 1].id],
  }));

  const totalEstimatedMs = steps.reduce((sum, s) => sum + s.estimatedMs, 0);
  const totalCredits = steps.reduce((sum, s) => sum + s.credits, 0);

  return {
    steps,
    rationale: `[${ctx.intent}] Template-based plan (${steps.length} steps, dynamic planning enabled) — ${template.description}`,
    totalEstimatedMs,
    totalCredits,
    chainId: `dyn-${ctx.sessionId}-${Date.now()}`,
    dynamic: true,
  };
}

/**
 * 读 graph 节点状态 → 决定：
 * 1) 现有步骤跳过：某些步骤 confidence >= 0.85 且无 issues → JUMP
 * 2) 需要重做：某步骤 confidence < 0.45 或 risk > 0.8 或 issues >= 2 → REDO
 * 3) 需要补全：执行链中缺少市场数据节点 → INSERT_BEFORE (S2.5 数据增强)
 * 4) 可提前结束：所有步骤完成且 avg confidence >= 0.75 → EARLY_TERMINATE
 */
export function adjustPlanAfterStep(
  plan: DynamicPlan,
  graphState: GraphReflectionState,
  justExecutedStepId: string,
): {
  shouldSkip: boolean;
  skipTarget?: string; // 接下来应该跳过的步骤（直接到这里）
  shouldRedo: boolean;
  redoStepId?: string;
  shouldInsert?: PlanStep;
  insertBefore?: string;
  shouldTerminateEarly: boolean;
  reason: string;
} {
  // 1) 拿到刚刚完成节点状态
  const justFinished = graphState.architectureNodes.get(justExecutedStepId);
  if (!justFinished) {
    return {
      shouldSkip: false,
      shouldRedo: false,
      shouldTerminateEarly: false,
      reason: `节点 ${justExecutedStepId} 未在 graph 中注册，按默认继续`,
    };
  }

  const conf = justFinished.confidence ?? 0.6;
  const risk = justFinished.riskScore ?? 0.3;
  const issuesCount = justFinished.issuesFound?.length ?? 0;

  // 2) REDO 条件：置信度过低 或 风险过高 或 问题数多
  if (conf < 0.45 || risk > 0.8 || issuesCount >= 3) {
    return {
      shouldSkip: false,
      shouldRedo: true,
      redoStepId: justExecutedStepId,
      shouldTerminateEarly: false,
      reason: `低置信度(${conf.toFixed(2)}) / 高风险(${risk.toFixed(2)}) / 问题数(${issuesCount}) → 重做 ${justExecutedStepId}`,
    };
  }

  // 3) INSERT_BEFORE：如果当前节点内容涉及市场数据但 graph 中缺少市场数据节点
  const hasMarketDataNode = Array.from(graphState.architectureNodes.values()).some(
    (n) => n.status !== 'pending' && (n.toolIterations ?? 0) > 0
  );
  const requiresMarket =
    plan.steps.find((s) => s.id === justExecutedStepId)?.tools?.includes('market') ?? false;

  if (requiresMarket && !hasMarketDataNode && graphState.completedNodes === 1) {
    return {
      shouldSkip: false,
      shouldRedo: false,
      shouldInsert: {
        id: 'S2.5_DATA_AUGMENT',
        name: 'S2.5 数据增强',
        description: '补充最近 N 根 K 线、波动率与支撑阻力的数据验证',
        estimatedMs: 10000,
        credits: 20,
        tools: ['market'],
        inputs: [justExecutedStepId],
      },
      insertBefore:
        plan.steps[plan.steps.findIndex((s) => s.id === justExecutedStepId) + 1]?.id,
      shouldTerminateEarly: false,
      reason: '检测到当前步骤需要工具数据但 graph 中无工具迭代记录 → 插入数据增强步骤',
    };
  }

  // 4) JUMP：如果 S3 高置信度且无问题 → 跳过 S4（对 strategy_verify 不适用）
  if (justExecutedStepId === 'S3_DESIGN' && conf >= 0.85 && issuesCount === 0 && risk < 0.5) {
    return {
      shouldSkip: true,
      skipTarget: 'S5_EXECUTE',
      shouldRedo: false,
      shouldTerminateEarly: false,
      reason: `S3 置信度 ${conf.toFixed(2)}、风险 ${risk.toFixed(2)}、无问题 → 跳过 S4 直接到 S5/SUMMARY`,
    };
  }

  // 5) EARLY_TERMINATE：所有步骤完成且平均置信度高
  const completedNodes = Array.from(graphState.architectureNodes.values()).filter(
    (n) => n.status === 'completed'
  );
  const avgConf =
    completedNodes.reduce((s, n) => s + (n.confidence ?? 0), 0) /
    Math.max(completedNodes.length, 1);
  if (
    completedNodes.length === plan.steps.length &&
    avgConf >= 0.75 &&
    graphState.compressionSignal.highValueNodes.length >= plan.steps.length - 1
  ) {
    return {
      shouldSkip: false,
      shouldRedo: false,
      shouldTerminateEarly: true,
      reason: `所有步骤完成，平均置信度 ${avgConf.toFixed(2)} → 提前结束`,
    };
  }

  return {
    shouldSkip: false,
    shouldRedo: false,
    shouldTerminateEarly: false,
    reason: `节点 ${justExecutedStepId} confidence=${conf.toFixed(2)}, risk=${risk.toFixed(2)}, issues=${issuesCount} → 正常推进`,
  };
}

/** 快速创建初始 graph state（与 graph-reflection-bridge 保持一致） */
export function initGraphState(sessionId: string): GraphReflectionState {
  const state = createGraphReflectionState(sessionId);
  state.dynamicChain.enabled = true;
  return state;
}
