/**
 * P0-2b-S3: 算法识别 IPC 闭环集成测试
 *
 * 验证 TS → IPC → Python → DreamOS 算法识别 → TS 完整链路
 *
 * 测试场景:
 * 1. T0 简单查询（"BTC多少钱"）→ tier=T0
 * 2. T1 单域问题（"BTC现在能做多吗"）→ tier=T1
 * 3. T3 深度分析（"深度分析这波回调"）→ tier=T3 + agent_takeover_needed=True
 * 4. 功能开关关闭（ENABLE_ALGORITHM_LAYER=0）→ degraded=True
 * 5. FAIL-OPEN（Python server 不可用）→ degraded=True
 *
 * 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-2b
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { spawn, ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import { startPythonIPCServer, stopPythonIPCServer } from "../../packages/bridge-core/src/python-ipc";
import { recognizeViaAlgorithm } from "../../packages/bridge-core/src/algorithm-listener";

const PYTHON_SERVER_PATH = resolve(
  __dirname,
  "..",
  "..",
  "packages",
  "python-server",
  "server.py"
);

describe("P0-2b: 算法识别 IPC 闭环", () => {
  let pyServer: ChildProcess | null = null;

  afterEach(async () => {
    if (pyServer) {
      await stopPythonIPCServer(pyServer);
      pyServer = null;
    }
  });

  it("TC-1: T0 简单查询 → tier=T0", async () => {
    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
      env: { ENABLE_ALGORITHM_LAYER: "1" },
    });

    const result = await recognizeViaAlgorithm(pyServer, {
      user_message: "BTC多少钱",
    });

    expect(result.degraded).toBe(false);
    expect(result.tier).toBe("T0");
  });

  it("TC-2: T1 单域问题 → tier=T1", async () => {
    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
      env: { ENABLE_ALGORITHM_LAYER: "1" },
    });

    const result = await recognizeViaAlgorithm(pyServer, {
      user_message: "BTC现在能做多吗",
    });

    expect(result.degraded).toBe(false);
    expect(result.tier).toBe("T1");
  });

  it("TC-3: T3 深度分析 → tier=T3 + agent_takeover_needed=True", async () => {
    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
      env: { ENABLE_ALGORITHM_LAYER: "1" },
    });

    const result = await recognizeViaAlgorithm(pyServer, {
      user_message: "深度分析这波回调",
    });

    expect(result.degraded).toBe(false);
    expect(result.tier).toBe("T3");
    expect(result.agent_takeover_needed).toBe(true);
  });

  it("TC-4: 功能开关关闭 → degraded=True", async () => {
    pyServer = await startPythonIPCServer({
      serverPath: PYTHON_SERVER_PATH,
      // 默认 ENABLE_ALGORITHM_LAYER=0
    });

    const result = await recognizeViaAlgorithm(pyServer, {
      user_message: "BTC多少钱",
    });

    expect(result.degraded).toBe(true);
    expect(result.reason).toContain("algorithm_layer_disabled");
  });

  it("TC-5: FAIL-OPEN — Python server 不可用 → degraded=True", async () => {
    // 使用一个不存在的 server 路径触发启动失败
    const fakeProcess = spawn("python3", ["-c", "import sys; sys.exit(1)"], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    // 等待进程退出
    await new Promise<void>((resolve) => {
      fakeProcess.on("exit", () => resolve());
    });

    const result = await recognizeViaAlgorithm(fakeProcess, {
      user_message: "BTC多少钱",
    });

    expect(result.degraded).toBe(true);
  }, 15000);  // 15s 超时（recognizeViaAlgorithm 内部 10s 超时 + 缓冲）
});
