/**
 * S2 拆解器单测：KR 数量边界、字段完整性、双策略与降级路径。
 */

import {
  decomposeTask,
  readDecomposeStrategy,
  readVerifyThreshold,
  DEFAULT_VERIFY_CONFIDENCE_THRESHOLD,
} from "./decompose";
import type { PlanCard } from "@/lib/agent/plancard";

function card(steps: Array<{ action: string; tool: string }>): PlanCard {
  return {
    id: "pc-test",
    intent: "test",
    plan_steps: steps.map((step, index) => ({ step: index + 1, ...step })),
    validation: { evaluator_refs: ["45.heuristic@1.0.0"] },
  };
}

describe("decomposeTask 确定性策略", () => {
  it("deep 产出 2-5 个 KR，且每个 KR 字段齐全", async () => {
    const result = await decomposeTask(
      {
        taskId: "t1",
        text: "对比三只标的的基本面并回测策略",
        intent: "strategy_verify",
        level: "deep",
        score: 6,
      },
      {},
      {},
    );

    expect(result.strategy).toBe("deterministic");
    expect(result.degraded).toBe(false);
    expect(result.skip_dispatch).toBe(false);
    expect(result.krs.length).toBeGreaterThanOrEqual(2);
    expect(result.krs.length).toBeLessThanOrEqual(5);

    for (const kr of result.krs) {
      expect(kr.criteria.trim().length).toBeGreaterThan(0);
      expect(kr.verify).toBe("evidence_backed");
      expect(kr.owner_domain).toBe("domain:strategy");
      expect(kr.capability_ids?.length).toBeGreaterThan(0);
      expect(kr.evidence_id).toBeTruthy();
    }
    expect(result.objective.required_verdict_level).toBe("U2");
  });

  it("standard 产出 2-3 个 KR", async () => {
    const result = await decomposeTask(
      {
        taskId: "t2",
        text: "看一下当前持仓风险",
        intent: "risk_alert",
        level: "standard",
        score: 2,
      },
      {},
      {},
    );
    expect(result.krs.length).toBeGreaterThanOrEqual(2);
    expect(result.krs.length).toBeLessThanOrEqual(3);
  });

  it("quick 只产出 1 个 KR 并跳过派发", async () => {
    const result = await decomposeTask(
      {
        taskId: "t3",
        text: "现在比特币多少钱",
        intent: "market_query",
        level: "quick",
        score: 1,
      },
      {},
      {},
    );
    expect(result.krs).toHaveLength(1);
    expect(result.skip_dispatch).toBe(true);
    expect(result.krs[0].verify).toBe("c_action");
    expect(result.objective.required_verdict_level).toBe("U0");
  });
});

describe("decomposeTask LLM 策略", () => {
  it("按 PlanCard 归并 KR 并遵守数量上限", async () => {
    const result = await decomposeTask(
      {
        taskId: "t4",
        text: "多步分析",
        intent: "deep_analysis",
        level: "deep",
        score: 5,
      },
      {
        planCard: async () =>
          card([
            { action: "拉取行情", tool: "l0.market.mcp.price" },
            { action: "拉取K线", tool: "l0.market.mcp.series" },
            { action: "计算指标", tool: "l0.market.mcp.technical_indicator" },
            { action: "交叉验证", tool: "l0.analysis.mcp.data_insight" },
            { action: "回测验证", tool: "l0.trading.mcp.backtest" },
            { action: "风险检查", tool: "l0.dsh.mcp.risk" },
            { action: "输出图表", tool: "l0.chart.mcp.visual_capabilities" },
          ]),
      },
      { DECOMPOSE_STRATEGY: "llm" },
    );

    expect(result.strategy).toBe("llm");
    expect(result.degraded).toBe(false);
    expect(result.model).toBe("decomposer:llm");
    expect(result.krs.length).toBeGreaterThanOrEqual(2);
    expect(result.krs.length).toBeLessThanOrEqual(5);
  });

  it("PlanCard 失败时降级为确定性模板并标记 degraded", async () => {
    const result = await decomposeTask(
      {
        taskId: "t5",
        text: "深度分析",
        intent: "deep_analysis",
        level: "deep",
        score: 5,
      },
      {
        planCard: async () => {
          throw new Error("planner down");
        },
      },
      { DECOMPOSE_STRATEGY: "llm" },
    );

    expect(result.degraded).toBe(true);
    expect(result.strategy).toBe("deterministic");
    expect(result.krs.length).toBeGreaterThanOrEqual(2);
  });
});

describe("全局配置读取", () => {
  it("策略只认 llm，其余回落 deterministic", () => {
    expect(readDecomposeStrategy({ DECOMPOSE_STRATEGY: "llm" })).toBe("llm");
    expect(readDecomposeStrategy({ DECOMPOSE_STRATEGY: "LLM" })).toBe("llm");
    expect(readDecomposeStrategy({ DECOMPOSE_STRATEGY: "p2" })).toBe(
      "deterministic",
    );
  });

  it("验收阈值默认 0.7，越界/非法回落默认值", () => {
    expect(readVerifyThreshold({})).toBe(DEFAULT_VERIFY_CONFIDENCE_THRESHOLD);
    expect(readVerifyThreshold({ AGENT_VERIFY_CONFIDENCE_THRESHOLD: "0.85" })).toBe(0.85);
    expect(readVerifyThreshold({ AGENT_VERIFY_CONFIDENCE_THRESHOLD: "abc" })).toBe(
      DEFAULT_VERIFY_CONFIDENCE_THRESHOLD,
    );
    expect(readVerifyThreshold({ AGENT_VERIFY_CONFIDENCE_THRESHOLD: "2" })).toBe(1);
  });
});
