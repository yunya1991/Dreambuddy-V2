/**
 * F-05: 分路径 fail 策略
 *
 * 测试目标:
 * 1. 交易路径 Python 不可达 = FAIL-CLOSED（交易方法被阻止）
 * 2. 非交易路径 Python 不可达 = FAIL-OPEN（降级 no-op，不抛异常）
 * 3. 交易路径 constraint_passed 缺失 = FAIL-CLOSED
 * 4. 非交易路径 constraint_passed 缺失 = 放行（FAIL-OPEN）
 * 5. 交易路径 constraint_passed=false = 拒绝
 * 6. 非交易路径 constraint_passed=false = 放行（不检查）
 *
 * 注: 3-5 在 test_f02_constraint_enforcement.ts 已有覆盖；
 *     6（非交易路径 constraint_passed=false）为新增；
 *     1-2（Python 不可达）为本文件核心新增，通过真实 spawn + stop 模拟 IPC 断裂。
 *
 * 来源: SPEC v0.3 七补.1 F-05
 * 调研: A7 FAIL-OPEN（分路径 fail 策略）
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import type { ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import {
  startPythonIPCServer,
  stopPythonIPCServer,
  isAlive,
} from "../../packages/bridge-core/src/python-ipc";
import {
  enforceConstraint,
  isTradingMethod,
  ConstraintViolationError,
} from "../../packages/bridge-core/src/constraint-enforcer";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

/**
 * 模拟 Python 不可达时的 IPC 响应：
 * - ok=false
 * - error.code=IPC_UNREACHABLE
 * - constraint_passed 缺失（因为 Python 没能产出约束结论）
 */
const UNREACHABLE_RESPONSE = {
  schema_version: "1.0.0",
  message_type: "response" as const,
  ok: false,
  error: { code: "IPC_UNREACHABLE", message: "Python IPC server 不可达" },
  id: "unreachable-id",
  timestamp: new Date().toISOString(),
};

describe("F-05: 分路径 fail 策略", () => {
  let pyServer: ChildProcess | null = null;

  beforeEach(async () => {
    // 启动真实 Python server（用于后续模拟 IPC 断裂）
    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
    });
  });

  afterEach(async () => {
    if (pyServer) {
      await stopPythonIPCServer(pyServer);
      pyServer = null;
    }
  });

  describe("1. Python 不可达 fail 策略", () => {
    it("交易路径 Python 不可达 = FAIL-CLOSED（交易被阻止）", async () => {
      // 模拟 IPC 断裂：停止 Python server
      await stopPythonIPCServer(pyServer!);
      expect(isAlive(pyServer!)).toBe(false);

      // 交易路径：Python 不可达 → 响应无 constraint_passed → 拒绝（FAIL-CLOSED）
      let blocked = false;
      try {
        enforceConstraint("execute_node", UNREACHABLE_RESPONSE);
      } catch (e) {
        if (e instanceof ConstraintViolationError) {
          blocked = true;
        }
      }
      expect(blocked).toBe(true);
    });

    it("非交易路径 Python 不可达 = FAIL-OPEN（降级 no-op）", async () => {
      // 模拟 IPC 断裂
      await stopPythonIPCServer(pyServer!);
      expect(isAlive(pyServer!)).toBe(false);

      // 非交易路径：Python 不可达 → 降级 no-op，不抛异常
      expect(() =>
        enforceConstraint("memory_recall", UNREACHABLE_RESPONSE)
      ).not.toThrow();
    });
  });

  describe("2. constraint_passed 缺失 fail 策略", () => {
    it("交易路径 constraint_passed 缺失 = FAIL-CLOSED", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: {},
        id: "test-id",
        timestamp: new Date().toISOString(),
        // constraint_passed 缺失
      };

      expect(() => enforceConstraint("execute_node", response)).toThrow(
        ConstraintViolationError
      );
    });

    it("非交易路径 constraint_passed 缺失 = 放行（FAIL-OPEN）", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: {},
        id: "test-id",
        timestamp: new Date().toISOString(),
        // constraint_passed 缺失
      };

      expect(() => enforceConstraint("memory_recall", response)).not.toThrow();
    });
  });

  describe("3. constraint_passed=false fail 策略", () => {
    it("交易路径 constraint_passed=false = 拒绝", () => {
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: {},
        constraint_passed: false,
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("execute_node", response)).toThrow(
        ConstraintViolationError
      );
    });

    it("非交易路径 constraint_passed=false = 放行（不检查）", () => {
      // 非交易路径根本不检查 constraint_passed，即使为 false 也放行
      const response = {
        schema_version: "1.0.0",
        message_type: "response" as const,
        ok: true,
        result: {},
        constraint_passed: false,
        id: "test-id",
        timestamp: new Date().toISOString(),
      };

      expect(() => enforceConstraint("memory_recall", response)).not.toThrow();
    });
  });

  describe("4. 分路径策略路由正确性", () => {
    it("交易方法被识别为交易路径", () => {
      expect(isTradingMethod("execute_node")).toBe(true);
      expect(isTradingMethod("open_position")).toBe(true);
      expect(isTradingMethod("close_position")).toBe(true);
      expect(isTradingMethod("modify_position")).toBe(true);
    });

    it("非交易方法被识别为非交易路径", () => {
      expect(isTradingMethod("ping")).toBe(false);
      expect(isTradingMethod("memory_recall")).toBe(false);
    });
  });
});
