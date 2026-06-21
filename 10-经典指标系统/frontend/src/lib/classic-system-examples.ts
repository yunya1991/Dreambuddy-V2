/**
 * 使用示例：Dreambuddy-v2 S思维链输出 → classic-system 治理流程
 *
 * 这些函数在 React 组件或 S思维链完成钩子中调用。
 * 展示：如何从策略链结果生成 Draft、推送至经典系统。
 */

import type { CompleteStrategyChain } from "./classic-system-bridge";
import {
  runStrategyPipeline,
  StrategyLibraryAPI,
  SystemMonitorAPI,
  type PipelineState,
  type PipelineOptions,
} from "./classic-system-pipeline";

/**
 * 场景1：S思维链完成后，自动推送策略到 classic-system
 *
 * 通常在 S5 (Execute) 步骤完成或链控制器完成钩子中调用
 */
export async function onStrategyChainComplete(
  chainResult: CompleteStrategyChain,
  options: PipelineOptions = {}
): Promise<void> {
  console.log(`[Dreambuddy] 策略研究完成: ${chainResult.scope}`);
  console.log(`[Dreambuddy] 推送至 classic-system 治理流程...`);

  const result = await runStrategyPipeline(chainResult, {
    runBacktest: false,
    autoApproval: true,
    onProgress: (state: PipelineState) => {
      console.log(`[Pipeline/${state.phase}] ${state.success ? "✅" : "❌"} ${state.message}`);
    },
    ...options,
  });

  if (result.success) {
    console.log(`[Pipeline] ✅ 策略成功部署: ${result.strategyName}`);
    console.log(`[Pipeline] 追踪ID: ${result.traceId}`);
    console.log(`[Pipeline] 变更集: ${result.changesetId || "N/A"}`);
  } else {
    console.error(`[Pipeline] ❌ 策略部署失败: ${result.error}`);
    console.error(`[Pipeline] 失败步骤:`, result.steps.find(s => !s.success));
  }
}

/**
 * 场景2：Dreambuddy 从 classic-system 策略库获取参考策略
 *
 * 用于在 S1/S2 研究阶段，查询经典系统已有策略作为知识参考
 */
export async function fetchStrategyKnowledge(
  scope: string,
  search?: string
): Promise<any[]> {
  try {
    const result = await StrategyLibraryAPI.listStrategies({
      scope,
      status: "active",
      search,
    });

    if (result?.ok && result?.strategies) {
      console.log(`[知识库] 获取到 ${result.strategies.length} 个参考策略`);
      return result.strategies;
    }
    return [];
  } catch (error) {
    console.error(`[知识库] 查询失败:`, error);
    return [];
  }
}

/**
 * 场景3：查询系统监控（审批状态、回滚点等）
 *
 * 用于监控界面，展示当前治理流程状态
 */
export async function fetchSystemStatus(): Promise<{
  approvals: any[];
  rollbackPoints: any[];
  health: any;
}> {
  const [approvals, rollback, health] = await Promise.allSettled([
    SystemMonitorAPI.listApprovals("pending"),
    SystemMonitorAPI.listRollbackPoints(),
    SystemMonitorAPI.healthCheck(),
  ]);

  return {
    approvals: approvals.status === "fulfilled" ? approvals.value?.approvals || [] : [],
    rollbackPoints: rollback.status === "fulfilled" ? rollback.value?.points || [] : [],
    health: health.status === "fulfilled" ? health.value : { ok: false },
  };
}

/**
 * 使用示例数据
 */
export function createSampleStrategyChain(): CompleteStrategyChain {
  return {
    scope: "BTC_USDT_15m",
    sessionId: `session-${Date.now()}`,
    traceId: `dream-${Date.now()}`,
    s1: {
      symbol: "BTCUSDT",
      displayName: "Bitcoin",
      price: 89500.50,
      priceChange24h: 2.35,
      support: "88000",
      resistance: "91000",
      indicators: {
        rsi: 58,
        macd: { value: 125, signal: 110, histogram: 15 },
        trend: "bullish" as const,
      },
      sentiment: {
        fearGreedIndex: 72,
        fundingRate: 0.012,
      },
      summary: "BTC处于上升趋势，技术指标强势",
    },
    s2: {
      trend: {
        shortTerm: "bullish" as const,
        mediumTerm: "bullish" as const,
        longTerm: "neutral" as const,
      },
      keyLevels: {
        entryRange: "89000-89800",
        stopLoss: "87500",
        takeProfit: "92500",
      },
      risks: ["周线阻力位可能承压", "市场情绪过热风险"],
      confidence: 82,
      conclusion: "趋势明确，适合构建多头策略",
    },
    s3: {
      strategyName: "BTC_USDT_15m_Trend_Bullish_v1",
      entryPlan: {
        entryPoint: "89300-89800",
        positionSize: 0.05,
        addRules: "回调至EMA20加仓",
      },
      riskManagement: {
        stopLoss: "87500",
        takeProfit: "92500",
        riskRewardRatio: "2.5",
      },
      scenarios: [
        { scenario: "突破阻力", probability: 0.65, outcome: "快速上涨至95000" },
        { scenario: "区间震荡", probability: 0.25, outcome: "维持88000-91000" },
        { scenario: "回调修正", probability: 0.10, outcome: "下探85000支撑" },
      ],
      confidence: 78,
    },
    s4: {
      backtest: {
        period: "2024-01至2025-06",
        winRate: 68.5,
        profitFactor: 2.15,
        maxDrawdown: 12.3,
        sharpeRatio: 1.85,
      },
      riskAssessment: {
        var95: 8.5,
        maxDailyLoss: 4.2,
        consecutiveLosses: 3,
      },
      verdict: "回测表现优秀，风险可控",
      recommend: true,
    },
    summary: "完整策略研究：BTC 15分钟周期趋势策略",
  };
}
