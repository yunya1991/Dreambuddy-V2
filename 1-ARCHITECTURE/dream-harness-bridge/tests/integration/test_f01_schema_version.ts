/**
 * F-01: IPC 契约版本化 + 显式版本协商
 *
 * 测试目标（RED → GREEN）：
 * 1. 每个 IPC 消息必须含 schema_version 字段
 * 2. adapter 启动时与 Python server 做版本握手
 * 3. 不兼容版本 → adapter 拒绝注册 Python tool，走 FAIL-OPEN
 *
 * 来源: SPEC v0.3 七补.1 F-01
 * 调研: RESEARCH_FEASIBILITY_4DIM.md A3 契约式设计 + A6 跨语言通信
 *
 * 注: TS 侧测试只测 TS 逻辑；Python 侧逻辑由 pytest 测试
 *     跨语言集成测试（握手）在 test_f01_handshake_e2e.ts
 */

import { describe, it, expect } from "vitest";
import {
  createProtocolClient,
  ProtocolHandshakeError,
  CURRENT_SCHEMA_VERSION,
} from "../../packages/bridge-core/src/sdk/protocol-client";

const SCHEMA_VERSION_V1 = "1.0.0";
const SCHEMA_VERSION_V2 = "2.0.0";

describe("F-01: IPC 契约版本化 + 显式版本协商", () => {

  describe("1. schema_version 字段", () => {
    it("每个 IPC 请求必须含 schema_version 字段", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });
      const request = client.buildRequest("execute_node", { node_id: "C1" });

      expect(request).toHaveProperty("schema_version");
      expect(request.schema_version).toBe(SCHEMA_VERSION_V1);
    });

    it("每个 IPC 响应必须含 schema_version 字段", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });
      const response = client.buildResponse(true, { result: "test" });

      expect(response).toHaveProperty("schema_version");
      expect(response.schema_version).toBe(SCHEMA_VERSION_V1);
    });

    it("schema_version 格式为 semver (MAJOR.MINOR.PATCH)", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });
      const request = client.buildRequest("ping", {});

      const semverRegex = /^\d+\.\d+\.\d+$/;
      expect(request.schema_version).toMatch(semverRegex);
    });

    it("请求包含 message_type=request", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });
      const request = client.buildRequest("ping", {});

      expect(request.message_type).toBe("request");
    });

    it("请求包含唯一 id", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });
      const req1 = client.buildRequest("ping", {});
      const req2 = client.buildRequest("ping", {});

      expect(req1.id).not.toBe(req2.id);
    });

    it("请求包含 timestamp", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });
      const request = client.buildRequest("ping", {});

      expect(request.timestamp).toBeTruthy();
      expect(new Date(request.timestamp).getTime()).not.toBeNaN();
    });
  });

  describe("2. 版本兼容性检查", () => {
    it("MAJOR 版本不同 = 不兼容", () => {
      const client = createProtocolClient({ version: "1.0.0" });
      const result = client.checkCompatibility("2.0.0");

      expect(result.compatible).toBe(false);
    });

    it("MINOR 版本不同 = 兼容（向后兼容）", () => {
      const client = createProtocolClient({ version: "1.0.0" });
      const result = client.checkCompatibility("1.1.0");

      expect(result.compatible).toBe(true);
    });

    it("PATCH 版本不同 = 兼容", () => {
      const client = createProtocolClient({ version: "1.0.0" });
      const result = client.checkCompatibility("1.0.5");

      expect(result.compatible).toBe(true);
    });

    it("相同版本 = 兼容", () => {
      const client = createProtocolClient({ version: "1.0.0" });
      const result = client.checkCompatibility("1.0.0");

      expect(result.compatible).toBe(true);
    });
  });

  describe("3. 响应解析与版本验证", () => {
    it("缺少 schema_version 的响应 = 抛出 ProtocolHandshakeError", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });

      const malformedMessage = JSON.stringify({
        ok: true,
        result: "test",
        id: "test-id",
      }); // 缺少 schema_version

      expect(() => {
        client.parseResponse(malformedMessage);
      }).toThrow(ProtocolHandshakeError);
    });

    it("MAJOR 版本不兼容的响应 = 抛出 ProtocolHandshakeError", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });

      const incompatibleResponse = JSON.stringify({
        schema_version: SCHEMA_VERSION_V2,
        message_type: "response",
        ok: true,
        result: "test",
        id: "test-id",
        timestamp: new Date().toISOString(),
      });

      expect(() => {
        client.parseResponse(incompatibleResponse);
      }).toThrow(ProtocolHandshakeError);
    });

    it("兼容版本的响应 = 正常解析", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });

      const compatibleResponse = JSON.stringify({
        schema_version: "1.0.5",
        message_type: "response",
        ok: true,
        result: { data: "test" },
        id: "test-id",
        timestamp: new Date().toISOString(),
      });

      const parsed = client.parseResponse(compatibleResponse);
      expect(parsed.ok).toBe(true);
      expect(parsed.result).toEqual({ data: "test" });
    });

    it("非合法 JSON = 抛出 ProtocolHandshakeError", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });

      expect(() => {
        client.parseResponse("not a json");
      }).toThrow(ProtocolHandshakeError);
    });
  });

  describe("4. constraint_passed 字段（F-02 前置）", () => {
    it("交易路径响应应包含 constraint_passed", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });
      const response = client.buildResponse(true, { result: "trade" }, {
        constraintPassed: true,
      });

      expect(response.constraint_passed).toBe(true);
    });

    it("非交易路径响应 constraint_passed 可选", () => {
      const client = createProtocolClient({ version: SCHEMA_VERSION_V1 });
      const response = client.buildResponse(true, { result: "recall" });

      expect(response.constraint_passed).toBeUndefined();
    });
  });

  describe("5. CURRENT_SCHEMA_VERSION 常量", () => {
    it("导出 CURRENT_SCHEMA_VERSION 常量", () => {
      expect(CURRENT_SCHEMA_VERSION).toBeDefined();
      expect(CURRENT_SCHEMA_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
    });
  });
});
