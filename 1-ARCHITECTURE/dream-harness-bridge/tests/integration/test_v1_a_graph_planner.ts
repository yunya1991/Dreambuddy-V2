/**
 * V1-A: A 层 GraphPlanner plugin 契约测试
 *
 * 验证 cordis-plugin-graph-planner:
 *   1. 模块导出契约 (name, apply, Config, inject)
 *   2. deriveGraphPlannerParams 意图→链路映射逻辑
 *   3. emptyPlan FAIL-OPEN 降级结构
 *   4. apply() 注册 agent/pre-step listener 并在异常时降级
 */

import { describe, it, expect } from "vitest";
import {
  name,
  apply,
  Config,
  inject,
  deriveGraphPlannerParams,
  emptyPlan,
} from "../../packages/cordis-plugin-graph-planner/lib/index.js";

describe("V1-A: GraphPlanner plugin 契约", () => {
  describe("1. 模块导出契约", () => {
    it("name 应为 dreambuddy-graph-planner", () => {
      expect(name).toBe("dreambuddy-graph-planner");
    });

    it("inject 应为空数组（不注入 tools，纯 listener）", () => {
      expect(Array.isArray(inject)).toBe(true);
      expect(inject.length).toBe(0);
    });

    it("Config 应为 schemastery object", () => {
      expect(Config).toBeDefined();
      // schemastery z.object() 返回函数（schema 构造器）
      expect(typeof Config).toBe("function");
    });

    it("apply 应为函数", () => {
      expect(typeof apply).toBe("function");
    });

    it("deriveGraphPlannerParams 应为导出函数", () => {
      expect(typeof deriveGraphPlannerParams).toBe("function");
    });

    it("emptyPlan 应为导出函数", () => {
      expect(typeof emptyPlan).toBe("function");
    });
  });

  describe("2. deriveGraphPlannerParams 意图映射", () => {
    it("交易执行类输入 → A 链 + TRADE_EXECUTION", () => {
      const params = deriveGraphPlannerParams("帮我买入 BTC");
      expect(params.recommended_chain).toBe("A");
      expect(params.intent_type).toBe("TRADE_EXECUTION");
      expect(params.confidence).toBeGreaterThanOrEqual(0.7);
    });

    it("趋势跟踪类输入 → A 链 + TREND_FOLLOWING", () => {
      const params = deriveGraphPlannerParams("分析 BTC 趋势");
      expect(params.recommended_chain).toBe("A");
      expect(params.intent_type).toBe("TREND_FOLLOWING");
    });

    it("反转类输入 → F 链 + REVERSAL", () => {
      const params = deriveGraphPlannerParams("ETH 是不是要反转了");
      expect(params.recommended_chain).toBe("F");
      expect(params.intent_type).toBe("REVERSAL");
    });

    it("查询类输入 → C 链 + POSITION_QUERY", () => {
      const params = deriveGraphPlannerParams("查询我的持仓");
      expect(params.recommended_chain).toBe("C");
      expect(params.intent_type).toBe("POSITION_QUERY");
    });

    it("扫描类输入 → C 链 + SCANNING", () => {
      const params = deriveGraphPlannerParams("扫描强势币种");
      expect(params.recommended_chain).toBe("C");
      expect(params.intent_type).toBe("SCANNING");
    });

    it("空输入 → 默认 C 链 + MARKET_ANALYSIS", () => {
      const params = deriveGraphPlannerParams("");
      expect(params.recommended_chain).toBe("C");
      expect(params.intent_type).toBe("MARKET_ANALYSIS");
      expect(params.confidence).toBeLessThan(0.7);
    });
  });

  describe("3. emptyPlan 降级结构", () => {
    it("应返回合法的 ExecutionPlan 结构", () => {
      const plan = emptyPlan("test failure");
      expect(plan.planned_chain).toBe("C");
      expect(Array.isArray(plan.selected_nodes)).toBe(true);
      expect(plan.selected_nodes.length).toBe(0);
      expect(plan._source).toBe("plugin_fail_open");
      expect(plan.rationale).toContain("test failure");
    });

    it("budget 字段存在", () => {
      const plan = emptyPlan("timeout");
      expect(plan.budget).toBeDefined();
      expect(plan.budget.total).toBe(0);
    });
  });

  describe("4. apply() listener 注册 + FAIL-OPEN", () => {
    it("apply 应注册 agent/pre-step 和 dispose listener", () => {
      const listeners: Record<string, Function> = {};
      const mockCtx = {
        on: (event: string, handler: Function) => {
          listeners[event] = handler;
        },
      };

      apply(mockCtx as any, { enabled: true });

      expect(listeners["agent/pre-step"]).toBeDefined();
      expect(typeof listeners["agent/pre-step"]).toBe("function");
      expect(listeners["dispose"]).toBeDefined();
    });

    it("enabled=false 时不注册 listener", () => {
      const listeners: Record<string, Function> = {};
      const mockCtx = {
        on: (event: string, handler: Function) => {
          listeners[event] = handler;
        },
      };

      apply(mockCtx as any, { enabled: false });

      expect(listeners["agent/pre-step"]).toBeUndefined();
    });

    it("pre-step handler 在 IPC 不可用时 FAIL-OPEN 并写入空计划", async () => {
      const listeners: Record<string, Function> = {};
      const mockCtx = {
        on: (event: string, handler: Function) => {
          listeners[event] = handler;
        },
      };

      apply(mockCtx as any, {
        enabled: true,
        pythonExecutable: "/nonexistent/python",
      });

      const handler = listeners["agent/pre-step"] as Function;
      const session: any = { messages: ["买入 BTC"] };
      const next = async () => "next-called";

      const result = await handler(session, next);

      // FAIL-OPEN: 继续执行 next
      expect(result).toBe("next-called");
      // session 应写入降级 plan
      expect(session.dreamosPlan).toBeDefined();
      expect(session.dreamosPlan._source).toBe("plugin_fail_open");
    });
  });
});
