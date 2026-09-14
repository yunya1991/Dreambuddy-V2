/**
 * F-03: 写入链路断裂的跨语言检测（链路活性测试）
 *
 * 测试目标（RED → GREEN）：
 * 1. 每个 IPC 方法验证 TS adapter → Python → 响应完整流转
 * 2. Python 收到请求（验证 stdin 写入成功）
 * 3. 响应回到 TS（验证 stdout 读取成功）
 * 4. session log 记录（验证事件流完整）
 *
 * 来源: SPEC v0.3 七补.1 F-03
 * 调研: 记忆 VM-1789171650348（写入链路断裂反模式跨语言下更高发）
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { spawn, ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import { createProtocolClient, CURRENT_SCHEMA_VERSION } from "../../packages/bridge-core/src/sdk/protocol-client";
import { startPythonIPCServer, stopPythonIPCServer } from "../../packages/bridge-core/src/python-ipc";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

describe("F-03: 链路活性测试（跨语言写入链路断裂检测）", () => {
  let pyServer: ChildProcess | null = null;
  let client: ReturnType<typeof createProtocolClient>;

  beforeEach(async () => {
    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
    });
    client = createProtocolClient({ version: CURRENT_SCHEMA_VERSION });
  });

  afterEach(async () => {
    if (pyServer) {
      await stopPythonIPCServer(pyServer);
      pyServer = null;
    }
  });

  describe("1. 请求-响应完整流转", () => {
    it("ping 请求 → Python 收到 → 响应回到 TS", async () => {
      const request = client.buildRequest("ping", {});
      const response = await sendAndReceive(pyServer!, request);

      expect(response).toBeDefined();
      expect(response.schema_version).toBe(CURRENT_SCHEMA_VERSION);
      expect(response.message_type).toBe("response");
      expect(response.ok).toBe(true);
    });

    it("execute_node 请求 → Python 收到 → constraint_passed 响应回到 TS", async () => {
      const request = client.buildRequest("execute_node", { node_id: "C1" });
      const response = await sendAndReceive(pyServer!, request);

      expect(response.ok).toBe(true);
      expect(response.constraint_passed).toBe(true);
    });

    it("memory_recall 请求 → Python 收到 → 无 constraint_passed 响应回到 TS", async () => {
      const request = client.buildRequest("memory_recall", { query: "test" });
      const response = await sendAndReceive(pyServer!, request);

      expect(response.ok).toBe(true);
      // 非交易路径不应该有 constraint_passed
      expect(response.constraint_passed).toBeFalsy();
    });
  });

  describe("2. stdin 写入验证（Python 收到请求）", () => {
    it("TS 写入 stdin → Python 读到并处理", async () => {
      const request = client.buildRequest("ping", { test: "linkage" });
      const response = await sendAndReceive(pyServer!, request);

      // 如果 Python 没收到请求，response 会超时或为 null
      expect(response).toBeDefined();
      expect(response.ok).toBe(true);
      // 验证 echo 回来的参数
      const result = response.result as { echo?: { params?: Record<string, unknown> } };
      expect(result.echo?.params?.test).toBe("linkage");
    });
  });

  describe("3. stdout 读取验证（响应回到 TS）", () => {
    it("Python stdout → TS 读到并解析", async () => {
      const request = client.buildRequest("ping", {});
      const rawLine = await sendAndReadRaw(pyServer!, request);

      expect(rawLine).not.toBeNull();
      const parsed = JSON.parse(rawLine!);
      expect(parsed.schema_version).toBe(CURRENT_SCHEMA_VERSION);
      expect(parsed.message_type).toBe("response");
    });
  });

  describe("4. 多请求连续流转（链路稳定性）", () => {
    it("连续 3 个请求都能完整流转", async () => {
      for (let i = 0; i < 3; i++) {
        const request = client.buildRequest("ping", { seq: i });
        const response = await sendAndReceive(pyServer!, request);
        expect(response.ok).toBe(true);
        const result = response.result as { echo?: { params?: Record<string, unknown> } };
        expect(result.echo?.params?.seq).toBe(i);
      }
    });
  });

  describe("5. 错误传播链路", () => {
    it("缺少 schema_version 的请求 → Python 返回错误响应", async () => {
      const malformedRequest = JSON.stringify({
        message_type: "request",
        method: "ping",
        params: {},
        id: "test-id",
        // 缺少 schema_version
      });

      const rawLine = await sendAndReadRaw(pyServer!, malformedRequest);
      expect(rawLine).not.toBeNull();
      const parsed = JSON.parse(rawLine!);
      expect(parsed.ok).toBe(false);
      expect(parsed.error.code).toBe("MISSING_SCHEMA_VERSION");
    });
  });
});

/**
 * 辅助函数：发送请求并接收解析后的响应
 */
async function sendAndReceive(
  pyServer: ChildProcess,
  request: Record<string, unknown>
): Promise<{
  schema_version: string;
  message_type: string;
  ok: boolean;
  result?: unknown;
  error?: { code: string; message: string };
  constraint_passed?: boolean;
  id: string;
  timestamp: string;
}> {
  const rawLine = await sendAndReadRaw(pyServer, JSON.stringify(request));
  if (!rawLine) {
    throw new Error("Python server 无响应（链路断裂）");
  }
  return JSON.parse(rawLine);
}

/**
 * 辅助函数：发送原始 JSON 字符串并读取一行响应
 */
async function sendAndReadRaw(
  pyServer: ChildProcess,
  rawMessage: string
): Promise<string | null> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      resolve(null);
    }, 5000);

    if (!pyServer.stdin || !pyServer.stdout) {
      clearTimeout(timeout);
      reject(new Error("Python server stdin/stdout 不可用"));
      return;
    }

    const onData = (chunk: Buffer) => {
      clearTimeout(timeout);
      pyServer.stdout?.removeListener("data", onData);
      resolve(chunk.toString().trim());
    };

    pyServer.stdout.once("data", onData);
    pyServer.stdin.write(rawMessage + "\n");
  });
}
