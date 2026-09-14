/**
 * V1-C: C 层 Reflector plugin 契约测试
 *
 * 验证 cordis-plugin-reflector:
 *   1. 模块导出契约 (name, apply, Config, inject)
 *   2. deriveReflectionDecision 决策推导逻辑
 *   3. mapDecisionToAction 5 种决策→动作映射
 *   4. degradedDecision FAIL-OPEN 结构
 *   5. apply() 注册 agent/step/end listener 并在异常时降级
 */

import { describe, it, expect } from "vitest";
import {
  name,
  apply,
  Config,
  inject,
  deriveReflectionDecision,
  buildDecideParams,
  mapDecisionToAction,
  applyReflectionControl,
  degradedDecision,
  VALID_DECISIONS,
} from "../../packages/cordis-plugin-reflector/lib/index.js";

describe("V1-C: Reflector plugin 契约", () => {
  describe("1. 模块导出契约", () => {
    it("name 应为 dreambuddy-reflector", () => {
      expect(name).toBe("dreambuddy-reflector");
    });

    it("inject 应为空数组（纯 listener）", () => {
      expect(Array.isArray(inject)).toBe(true);
      expect(inject.length).toBe(0);
    });

    it("Config 应为 schemastery object (函数)", () => {
      expect(Config).toBeDefined();
      expect(typeof Config).toBe("function");
    });

    it("apply 应为函数", () => {
      expect(typeof apply).toBe("function");
    });

    it("VALID_DECISIONS 包含 5 种决策", () => {
      expect(VALID_DECISIONS).toHaveLength(5);
      expect(VALID_DECISIONS).toContain("CONTINUE");
      expect(VALID_DECISIONS).toContain("REDO");
      expect(VALID_DECISIONS).toContain("INSERT_BEFORE");
      expect(VALID_DECISIONS).toContain("JUMP_TO");
      expect(VALID_DECISIONS).toContain("EARLY_TERMINATE");
    });
  });

  describe("2. deriveReflectionDecision 决策推导", () => {
    it("普通输入 → CONTINUE", () => {
      const result = deriveReflectionDecision({ messages: ["分析一下 BTC"], step: 1 });
      expect(result.decision).toBe("CONTINUE");
    });

    it("含 redo 关键词 → REDO", () => {
      const result = deriveReflectionDecision({ messages: ["请重做这个分析"], step: 2 });
      expect(result.decision).toBe("REDO");
    });

    it("含 terminate 关键词且 step>=2 → EARLY_TERMINATE", () => {
      const result = deriveReflectionDecision({ messages: ["信息足够了，结束吧"], step: 3 });
      expect(result.decision).toBe("EARLY_TERMINATE");
    });

    it("含 terminate 关键词但 step<2 → CONTINUE（不提前终止）", () => {
      const result = deriveReflectionDecision({ messages: ["结束"], step: 0 });
      expect(result.decision).toBe("CONTINUE");
    });

    it("空 messages → CONTINUE", () => {
      const result = deriveReflectionDecision({ messages: [], step: 1 });
      expect(result.decision).toBe("CONTINUE");
    });
  });

  describe("3. mapDecisionToAction 映射", () => {
    it("CONTINUE → continue 动作", () => {
      const action = mapDecisionToAction("CONTINUE", {});
      expect(action.type).toBe("continue");
    });

    it("REDO → redo 动作", () => {
      const action = mapDecisionToAction("REDO", {});
      expect(action.type).toBe("redo");
    });

    it("INSERT_BEFORE → insert_before 动作（含 target_step）", () => {
      const action = mapDecisionToAction("INSERT_BEFORE", { target_step: 3 });
      expect(action.type).toBe("insert_before");
      expect(action.label).toContain("3");
    });

    it("JUMP_TO → jump_to 动作（含 target_step）", () => {
      const action = mapDecisionToAction("JUMP_TO", { target_step: "step-5" });
      expect(action.type).toBe("jump_to");
      expect(action.label).toContain("step-5");
    });

    it("EARLY_TERMINATE → early_terminate 动作", () => {
      const action = mapDecisionToAction("EARLY_TERMINATE", {});
      expect(action.type).toBe("early_terminate");
    });

    it("未知决策 → 降级为 continue", () => {
      const action = mapDecisionToAction("UNKNOWN", {});
      expect(action.type).toBe("continue");
    });
  });

  describe("4. degradedDecision 降级结构", () => {
    it("应返回 CONTINUE + _source=plugin_fail_open", () => {
      const d = degradedDecision("IPC timeout");
      expect(d.decision).toBe("CONTINUE");
      expect(d._source).toBe("plugin_fail_open");
      expect(d.reason).toContain("IPC timeout");
    });
  });

  describe("5. apply() listener 注册 + FAIL-OPEN", () => {
    it("apply 应注册 agent/step/end 和 dispose listener", () => {
      const listeners = {};
      const mockCtx = {
        on: (event, handler) => {
          listeners[event] = handler;
        },
      };

      apply(mockCtx, { enabled: true });

      expect(listeners["agent/step/end"]).toBeDefined();
      expect(typeof listeners["agent/step/end"]).toBe("function");
      expect(listeners["dispose"]).toBeDefined();
    });

    it("enabled=false 时不注册 listener", () => {
      const listeners = {};
      const mockCtx = {
        on: (event, handler) => {
          listeners[event] = handler;
        },
      };

      apply(mockCtx, { enabled: false });

      expect(listeners["agent/step/end"]).toBeUndefined();
    });

    it("step/end handler 在 IPC 不可用时 FAIL-OPEN 并写入降级决策", async () => {
      const listeners = {};
      const mockCtx = {
        on: (event, handler) => {
          listeners[event] = handler;
        },
      };

      apply(mockCtx, {
        enabled: true,
        pythonExecutable: "/nonexistent/python",
      });

      const handler = listeners["agent/step/end"];
      const session = { messages: ["分析 BTC"], step: 1 };
      const next = async () => "next-called";

      const result = await handler(session, next);

      // FAIL-OPEN: 继续执行 next
      expect(result).toBe("next-called");
      // session 应写入降级决策
      expect(session.dreamosReflection).toBeDefined();
      expect(session.dreamosReflection.decision).toBe("CONTINUE");
      expect(session.dreamosReflection._source).toBe("plugin_fail_open");
    });
  });

  describe("6. Phase 2: buildDecideParams 上下文构建", () => {
    it("应返回 mode=decide 并包含所需字段", () => {
      const session = {
        messages: [{ content: "BTC 趋势看涨，建议 LONG" }],
        step: 3,
        dreamosPlan: {
          selected_nodes: ["C1", "C2", "A2"],
          budget: { total_budget: 100, used: 30, remaining: 70 },
        },
      };
      const params = buildDecideParams(session);
      expect(params.mode).toBe("decide");
      expect(params.current_node_id).toBeDefined();
      expect(typeof params.confidence).toBe("number");
      expect(params.executed_count).toBe(3);
      expect(params.max_nodes).toBe(3);
      expect(params.budget_remaining_ratio).toBeCloseTo(0.7);
      expect(params.status).toBe("SUCCESS");
    });

    it("从消息文本提取 LONG 方向", () => {
      const session = {
        messages: [{ content: "看涨，建议买入做多" }],
        step: 1,
      };
      const params = buildDecideParams(session);
      expect(params.direction).toBe("LONG");
      expect(params.confidence).toBeGreaterThanOrEqual(0.7);
    });

    it("从消息文本提取 SHORT 方向", () => {
      const session = {
        messages: [{ content: "看跌，建议做空卖出" }],
        step: 1,
      };
      const params = buildDecideParams(session);
      expect(params.direction).toBe("SHORT");
    });

    it("无方向关键词时 direction 为 null", () => {
      const session = {
        messages: [{ content: "市场震荡，等待信号" }],
        step: 1,
      };
      const params = buildDecideParams(session);
      expect(params.direction).toBeNull();
    });

    it("无 dreamosPlan 时 max_nodes 默认 5，budget 为 null", () => {
      const session = { messages: [], step: 0 };
      const params = buildDecideParams(session);
      expect(params.max_nodes).toBe(5);
      expect(params.budget_remaining_ratio).toBeNull();
    });

    it("从 session.dreamosNodeResults 提取前序结果", () => {
      const session = {
        messages: [],
        step: 2,
        dreamosNodeResults: {
          C1: { direction: "LONG", confidence: 0.85 },
          C2: { direction: "SHORT", confidence: 0.6 },
        },
      };
      const params = buildDecideParams(session);
      expect(params.prev_results).toHaveLength(2);
      const directions = params.prev_results.map((r) => r.direction).sort();
      expect(directions).toEqual(["LONG", "SHORT"]);
    });
  });

  describe("7. Phase 3: applyReflectionControl agent loop 控制", () => {
    it("CONTINUE → 清除控制标记并调用 next", async () => {
      const session = { step: 1, dreamosControl: { action: "redo" } };
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
        return "next-result";
      };
      const ctx = { emit: () => {} };

      const result = await applyReflectionControl(ctx, session, "CONTINUE", {}, next);

      expect(nextCalled).toBe(true);
      expect(result).toBe("next-result");
      expect(session.dreamosControl).toBeNull();
    });

    it("REDO → 设置 dreamosControl={action:'redo'} 并调用 next", async () => {
      const session = { step: 2 };
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
      };
      const ctx = { emit: () => {} };

      await applyReflectionControl(ctx, session, "REDO", { reason: "低置信度" }, next);

      expect(nextCalled).toBe(true);
      expect(session.dreamosControl).toBeDefined();
      expect(session.dreamosControl.action).toBe("redo");
      expect(session.dreamosControl.step).toBe(2);
      expect(session.dreamosControl.reason).toContain("低置信度");
    });

    it("JUMP_TO → 设置 target_node_id 并调用 next", async () => {
      const session = { step: 3 };
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
      };
      const ctx = { emit: () => {} };

      await applyReflectionControl(
        ctx,
        session,
        "JUMP_TO",
        { jump_to: "A9", reason: "预算不足" },
        next
      );

      expect(nextCalled).toBe(true);
      expect(session.dreamosControl.action).toBe("jump_to");
      expect(session.dreamosControl.target_node_id).toBe("A9");
    });

    it("INSERT_BEFORE → 设置 insert_node_id 并调用 next", async () => {
      const session = { step: 4 };
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
      };
      const ctx = { emit: () => {} };

      await applyReflectionControl(
        ctx,
        session,
        "INSERT_BEFORE",
        { insert_node_id: "A0", reason: "方向矛盾" },
        next
      );

      expect(nextCalled).toBe(true);
      expect(session.dreamosControl.action).toBe("insert_before");
      expect(session.dreamosControl.insert_node_id).toBe("A0");
    });

    it("EARLY_TERMINATE → emit turn-stopping 且不调用 next", async () => {
      const session = { step: 5 };
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
      };
      let emittedEvent = null;
      const ctx = {
        emit: (event, payload) => {
          emittedEvent = { event, payload };
        },
      };

      const result = await applyReflectionControl(
        ctx,
        session,
        "EARLY_TERMINATE",
        { reason: "已有足够信息" },
        next
      );

      expect(nextCalled).toBe(false);
      expect(result).toBeUndefined();
      expect(emittedEvent).not.toBeNull();
      expect(emittedEvent.event).toBe("agent/turn-stopping");
      expect(emittedEvent.payload.reason).toContain("已有足够信息");
      expect(emittedEvent.payload.source).toBe("dreamos_reflector");
    });

    it("未知决策 → FAIL-OPEN 清除标记并调用 next", async () => {
      const session = { step: 1, dreamosControl: { action: "redo" } };
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
      };
      const ctx = { emit: () => {} };

      await applyReflectionControl(ctx, session, "UNKNOWN_DECISION", {}, next);

      expect(nextCalled).toBe(true);
      expect(session.dreamosControl).toBeNull();
    });
  });

  describe("8. Phase 3: agent/pre-step 控制标记检测", () => {
    it("无控制标记时直接 next", async () => {
      const listeners = {};
      const mockCtx = {
        on: (event, handler) => {
          listeners[event] = handler;
        },
        emit: () => {},
      };

      apply(mockCtx, {
        enabled: true,
        pythonExecutable: "/nonexistent/python",
      });

      const handler = listeners["agent/pre-step"];
      expect(handler).toBeDefined();

      const session = {};
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
      };

      await handler(session, next);
      expect(nextCalled).toBe(true);
    });

    it("REDO 标记 → 设置 _dreamosRedoStep 并清除 dreamosControl", async () => {
      const listeners = {};
      const mockCtx = {
        on: (event, handler) => {
          listeners[event] = handler;
        },
        emit: () => {},
      };

      apply(mockCtx, {
        enabled: true,
        pythonExecutable: "/nonexistent/python",
      });

      const handler = listeners["agent/pre-step"];
      const session = {
        dreamosControl: { action: "redo", step: 3, reason: "低置信度" },
      };
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
      };

      await handler(session, next);

      expect(nextCalled).toBe(true);
      expect(session.dreamosControl).toBeNull();
      expect(session._dreamosRedoStep).toBe(3);
    });

    it("JUMP_TO 标记 → 设置 _dreamosJumpTo 并清除 dreamosControl", async () => {
      const listeners = {};
      const mockCtx = {
        on: (event, handler) => {
          listeners[event] = handler;
        },
        emit: () => {},
      };

      apply(mockCtx, {
        enabled: true,
        pythonExecutable: "/nonexistent/python",
      });

      const handler = listeners["agent/pre-step"];
      const session = {
        dreamosControl: { action: "jump_to", target_node_id: "C5", step: 2 },
      };
      let nextCalled = false;
      const next = async () => {
        nextCalled = true;
      };

      await handler(session, next);

      expect(nextCalled).toBe(true);
      expect(session.dreamosControl).toBeNull();
      expect(session._dreamosJumpTo).toBe("C5");
    });
  });
});
