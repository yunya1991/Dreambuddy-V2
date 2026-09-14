/**
 * V1: 并行化 + 降级链验证（TS 侧 IPC 链路测试）
 *
 * V1-1: 并行 vs 串行延迟对比
 *   - 并行调用 technical_indicators + fundamental_analysis
 *   - 串行调用同样方法
 *   - 验证 parallel_latency < serial_latency
 *
 * V1-2: 故障注入（FAIL-OPEN）
 *   - 8092/3456 不可达时返回中性默认值
 *   - 单个 API 故障不影响另一个
 *
 * V1-3 前置: session_consumer 方法可用
 *
 * 来源: PHASE1_SPEC.md 2.1~2.4 节
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { spawn, ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import { createProtocolClient, CURRENT_SCHEMA_VERSION } from "../../packages/bridge-core/src/sdk/protocol-client";
import { startPythonIPCServer, stopPythonIPCServer } from "../../packages/bridge-core/src/python-ipc";
import { writeFileSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

describe("V1: 并行化 + 降级链验证", () => {
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

  describe("V1-1: 并行 vs 串行延迟对比", () => {
    it("technical_indicators 方法链路活跃", async () => {
      const request = client.buildRequest("technical_indicators", { symbol: "BTC" });
      const response = await sendAndReceive(pyServer!, request);

      expect(response.ok).toBe(true);
      const result = response.result as Record<string, unknown>;
      expect(result.node_id).toBe("technical_indicators");
      // 8092 未运行 → degraded
      expect(result.status).toBe("degraded");
    });

    it("fundamental_analysis 方法链路活跃", async () => {
      const request = client.buildRequest("fundamental_analysis", { symbol: "BTC" });
      const response = await sendAndReceive(pyServer!, request);

      expect(response.ok).toBe(true);
      const result = response.result as Record<string, unknown>;
      expect(result.node_id).toBe("fundamental_analysis");
      // 3456 未运行 → degraded
      expect(result.status).toBe("degraded");
    });

    it("并行调用延迟显著低于串行", async () => {
      // 串行调用
      const serialStart = Date.now();
      const r1 = await sendAndReceive(pyServer!, client.buildRequest("technical_indicators", { symbol: "BTC" }));
      const r2 = await sendAndReceive(pyServer!, client.buildRequest("fundamental_analysis", { symbol: "BTC" }));
      const serialLatency = Date.now() - serialStart;

      // 并行调用（两个 stdin 写入后等两个 stdout 响应）
      const parallelStart = Date.now();
      const [p1, p2] = await Promise.all([
        sendAndReceive(pyServer!, client.buildRequest("technical_indicators", { symbol: "ETH" })),
        sendAndReceive(pyServer!, client.buildRequest("fundamental_analysis", { symbol: "ETH" })),
      ]);
      const parallelLatency = Date.now() - parallelStart;

      console.log(`  串行: ${serialLatency}ms, 并行: ${parallelLatency}ms`);
      expect(r1.ok).toBe(true);
      expect(r2.ok).toBe(true);
      expect(p1.ok).toBe(true);
      expect(p2.ok).toBe(true);
      expect(parallelLatency).toBeLessThan(serialLatency);
    });
  });

  describe("V1-2: 故障注入 — FAIL-OPEN", () => {
    it("technical_indicators 返回中性默认值（8092 不可达）", async () => {
      const request = client.buildRequest("technical_indicators", { symbol: "BTC" });
      const response = await sendAndReceive(pyServer!, request);

      expect(response.ok).toBe(true);
      const result = response.result as Record<string, unknown>;
      expect(result.status).toBe("degraded");
      expect((result.neutral_default as Record<string, unknown>)?.signal).toBe("neutral");
    });

    it("fundamental_analysis 返回中性默认值（3456 不可达）", async () => {
      const request = client.buildRequest("fundamental_analysis", { symbol: "BTC" });
      const response = await sendAndReceive(pyServer!, request);

      expect(response.ok).toBe(true);
      const result = response.result as Record<string, unknown>;
      expect(result.status).toBe("degraded");
      expect((result.neutral_default as Record<string, unknown>)?.signal).toBe("neutral");
    });

    it("单个 API 故障不影响另一个（独立降级）", async () => {
      const [r1, r2] = await Promise.all([
        sendAndReceive(pyServer!, client.buildRequest("technical_indicators", { symbol: "BTC" })),
        sendAndReceive(pyServer!, client.buildRequest("fundamental_analysis", { symbol: "BTC" })),
      ]);

      // 两个都成功返回（IPC 层面），即使数据源不可达
      expect(r1.ok).toBe(true);
      expect(r2.ok).toBe(true);
      // 各自独立 degraded
      const tiResult = r1.result as Record<string, unknown>;
      const faResult = r2.result as Record<string, unknown>;
      expect(tiResult.status).toBe("degraded");
      expect(faResult.status).toBe("degraded");
    });
  });

  describe("V1-3 前置: session_consumer 方法", () => {
    it("session_consumer 写入投影文件", async () => {
      const request = client.buildRequest("session_consumer", {
        event_type: "node_execution",
        event_data: { original_type: "tool/call", seq: 1, payload: { tool: "c1_scan" } },
        session_id: "test-session-ts-001",
      });
      const response = await sendAndReceive(pyServer!, request);

      expect(response.ok).toBe(true);
      const result = response.result as Record<string, unknown>;
      expect(result.status).toBe("ok");
      expect(result.written).toBe(true);

      // 验证投影文件存在且有内容
      const projectionPath = resolve(
        __dirname,
        "..",
        "..",
        "packages",
        ".session-projections",
        "g_layer_events.jsonl"
      );
      expect(existsSync(projectionPath)).toBe(true);

      const content = readFileSync(projectionPath, "utf-8").trim();
      const lines = content.split("\n");
      expect(lines.length).toBeGreaterThan(0);

      const lastEntry = JSON.parse(lines[lines.length - 1]);
      expect(lastEntry.event_type).toBe("node_execution");
      expect(lastEntry.session_id).toBe("test-session-ts-001");
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
    }, 15000); // 15s 超时（fundamental_analysis timeout=10s）

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
