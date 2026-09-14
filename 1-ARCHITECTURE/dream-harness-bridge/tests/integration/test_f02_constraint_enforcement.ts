/**
 * F-02: 协议级不变式强制硬约束
 *
 * 测试目标（RED → GREEN）：
 * 1. 交易路径响应必须含 constraint_passed=true
 * 2. adapter 在缺少 constraint_passed 时拒绝转发交易请求
 * 3. 硬约束未通过时 server 返回 CONSTRAINT_VIOLATION
 * 4. 非交易路径不需要 constraint_passed
 *
 * 来源: SPEC v0.3 七补.1 F-02
 * 调研: A3 契约式设计 + A7 FAIL-OPEN
 */

import { describe, it, expect } from "vitest";
import { createProtocolClient, ProtocolHandshakeError } from "../../packages/bridge-core/src/sdk/protocol-client";
import { enforceConstraint, isTradingMethod, ConstraintViolationError } from "../../packages/bridge-core/src/constraint-enforcer";

describe("F-02: 协议级不变式强制硬约束", () => {

  describe("1. 交易路径识别", () => {
    it("execute_node 是交易路径", () => {
      expect(isTradingMethod("execute_node")).toBe(true);
    });

    it("open_position 是交易路径", () => {
      expect(isTradingMethod("open_position")).toBe(true);
    });

    it("close_position 是交易路径", () => {
      expect(isTradingMethod("close_position")).toBe(true);
    });

    it("modify_position 是交易路径", () => {
      expect(isTradingMethod("modify_position")).toBe(true);
    });

    it("ping 不是交易路径", () => {
      expect(isTradingMethod("ping")).toBe(false);
    });

    it("memory_recall 不是交易路径", () => {
      expect(isTradingMethod("memory_recall")).toBe(false);
    });
  });

  describe("2. constraint_passed 强制检查", () => {
    it("交易路径 constraint_passed=true → 放行", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: { trade: "executed" },
        constraint_passed: true,
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("execute_node", response)).not.toThrow();
    });

    it("交易路径缺少 constraint_passed → 拒绝（ConstraintViolationError）", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: { trade: "executed" },
        // constraint_passed 缺失
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("execute_node", response)).toThrow(
        ConstraintViolationError
      );
    });

    it("交易路径 constraint_passed=false → 拒绝", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: { trade: "executed" },
        constraint_passed: false,
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("execute_node", response)).toThrow(
        ConstraintViolationError
      );
    });

    it("非交易路径缺少 constraint_passed → 放行", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: { data: "recall" },
        // constraint_passed 缺失，但非交易路径
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("memory_recall", response)).not.toThrow();
    });

    it("交易路径 ok=false 但 constraint_passed=true → 放行（执行失败≠约束失败）", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: false,
        error: { code: "EXEC_ERROR", message: "execution failed" },
        constraint_passed: true,
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("execute_node", response)).not.toThrow();
    });

    it("交易路径 ok=false 且 constraint_passed=false → 拒绝", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: false,
        error: { code: "CONSTRAINT_VIOLATION", message: "MAX_TRIAL_POSITIONS" },
        constraint_passed: false,
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("execute_node", response)).toThrow(
        ConstraintViolationError
      );
    });
  });

  describe("3. 分路径 fail 策略（F-05 前置）", () => {
    it("交易路径 constraint_passed 缺失 = FAIL-CLOSED（不交易）", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: {},
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      let blocked = false;
      try {
        enforceConstraint("execute_node", response);
      } catch (e) {
        if (e instanceof ConstraintViolationError) {
          blocked = true;
        }
      }
      expect(blocked).toBe(true); // FAIL-CLOSED
    });

    it("非交易路径 response 缺失 = FAIL-OPEN（降级 no-op）", () => {
      // 非交易路径不检查 constraint_passed
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: {},
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("memory_recall", response)).not.toThrow();
    });
  });
});
